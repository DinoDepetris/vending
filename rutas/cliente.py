"""
Rutas que usa el cliente que compra. El pago ahora puede ser real, vía
MercadoPago (QR + polling), o simulado como antes — depende de si
config_secretos.py tiene el Access Token cargado. Esto es a propósito:
si algo del lado de MercadoPago fallara, el vending sigue pudiendo
"vender" en modo simulado en vez de quedar totalmente roto.
"""

from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for

from datos.inventario import obtener_productos_en_venta, obtener_producto, descontar_stock, marcar_alerta_enviada
from datos.slots import obtener_slot_por_producto
from datos.ventas import registrar_venta
from simuladores import arduino, autorizar_pago_en_servidor
from notificaciones import enviar_alerta_stock_bajo
from config import UMBRAL_STOCK_BAJO, MERCADOPAGO_HABILITADO
from pagos_mercadopago import crear_pago_con_qr, verificar_pago_aprobado

cliente_bp = Blueprint("cliente", __name__)


def _obtener_carrito():
    return session.setdefault("carrito", {})


def _resumen_carrito():
    carrito = _obtener_carrito()
    lineas = []
    total = 0

    for producto, cantidad in carrito.items():
        datos_producto = obtener_producto(producto)
        precio = datos_producto["precio"] if datos_producto else 0
        subtotal = precio * cantidad
        total += subtotal
        lineas.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": subtotal
        })

    return {
        "lineas": lineas,
        "total": total,
        "cantidad_total": sum(carrito.values())
    }


def _entregar_carrito(detalles):
    # Esta es la misma lógica de entrega que antes vivía adentro de
    # carrito_pagar(), ahora separada en su propia función porque dos
    # caminos distintos la necesitan: el pago simulado (que entrega
    # apenas se "aprueba") y el pago real con MercadoPago (que entrega
    # recién cuando el polling confirma que el QR ya se pagó, que puede
    # ser bastante después de haber armado el carrito).
    entregas = []
    productos_fallidos = []

    for detalle in detalles:
        entregados_de_este = 0

        for _ in range(detalle["cantidad"]):
            entregado = arduino.abrir_compuerta(detalle["slot"])

            if entregado:
                descontar_stock(detalle["producto"])
                registrar_venta(detalle["producto"], detalle["precio"])
                entregados_de_este += 1

                producto_actualizado = obtener_producto(detalle["producto"])
                if (producto_actualizado["stock"] <= UMBRAL_STOCK_BAJO
                        and not producto_actualizado["alerta_enviada"]):
                    enviar_alerta_stock_bajo(detalle["producto"], producto_actualizado["stock"])
                    marcar_alerta_enviada(detalle["producto"])
            else:
                productos_fallidos.append(detalle["producto"])

        if entregados_de_este > 0:
            entregas.append({
                "producto": detalle["producto"],
                "cantidad": entregados_de_este,
                "slot": detalle["slot"]
            })

    return entregas, sorted(set(productos_fallidos))


def _validar_carrito(carrito):
    # También separado en su propia función: valida cada línea del
    # carrito contra la base de datos (existe, tiene slot, hay stock) y
    # devuelve el detalle completo listo para cobrar — o, si algo no
    # está bien, devuelve directamente la redirección que corresponde.
    detalles = []
    monto_total = 0

    for producto, cantidad in carrito.items():
        if cantidad <= 0:
            continue

        datos_producto = obtener_producto(producto)
        if datos_producto is None:
            session["carrito"] = {}
            return None, None, redirect(url_for("cliente.pagina_principal", mensaje=f"'{producto}' ya no existe, carrito vaciado"))

        slot_id = obtener_slot_por_producto(producto)
        if slot_id is None:
            session["carrito"] = {}
            return None, None, redirect(url_for("cliente.pagina_principal", mensaje=f"'{producto}' ya no está disponible, carrito vaciado"))

        if datos_producto["stock"] < cantidad:
            return None, None, redirect(url_for("cliente.ver_carrito"))

        monto_total += datos_producto["precio"] * cantidad
        detalles.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": datos_producto["precio"],
            "slot": slot_id
        })

    return detalles, monto_total, None


@cliente_bp.route("/")
def pagina_principal():
    productos = obtener_productos_en_venta()
    resumen = _resumen_carrito()
    mensaje_inicial = request.args.get("mensaje", "Esperando tu selección...")

    return render_template(
        "tienda.html",
        inventario=productos,
        resumen=resumen,
        mensaje_inicial=mensaje_inicial
    )


@cliente_bp.route("/estado")
def estado_actual():
    return jsonify(obtener_productos_en_venta())


@cliente_bp.route("/carrito/agregar", methods=["POST"])
def carrito_agregar():
    datos = request.get_json()
    producto = datos.get("producto")
    cantidad = int(datos.get("cantidad", 0))

    if cantidad > 0:
        carrito = _obtener_carrito()
        carrito[producto] = carrito.get(producto, 0) + cantidad
        session["carrito"] = carrito

    return jsonify(_resumen_carrito())


@cliente_bp.route("/carrito/quitar", methods=["POST"])
def carrito_quitar():
    datos = request.get_json()
    producto = datos.get("producto")

    carrito = _obtener_carrito()
    carrito.pop(producto, None)
    session["carrito"] = carrito

    return jsonify(_resumen_carrito())


@cliente_bp.route("/carrito/quitar-form", methods=["POST"])
def carrito_quitar_form():
    producto = request.form.get("producto")

    carrito = _obtener_carrito()
    carrito.pop(producto, None)
    session["carrito"] = carrito

    return redirect(url_for("cliente.ver_carrito"))


@cliente_bp.route("/carrito")
def ver_carrito():
    resumen = _resumen_carrito()
    return render_template("carrito.html", resumen=resumen)


@cliente_bp.route("/carrito/pagar", methods=["POST"])
def carrito_pagar():
    carrito = _obtener_carrito()

    if not carrito:
        return redirect(url_for("cliente.ver_carrito"))

    detalles, monto_total, redireccion_si_error = _validar_carrito(carrito)
    if redireccion_si_error:
        return redireccion_si_error

    # --- Camino real: MercadoPago configurado -----------------------
    if MERCADOPAGO_HABILITADO:
        try:
            pago = crear_pago_con_qr(monto_total)

            # Guardamos en la sesión QUÉ hay que entregar cuando el
            # pago se confirme — todavía no entregamos nada, porque
            # todavía no sabemos si el cliente va a pagar de verdad.
            session["pago_pendiente"] = {
                "referencia": pago["referencia"],
                "detalles": detalles
            }
            session["carrito"] = {}

            return render_template(
                "pagando.html",
                qr_base64=pago["qr_base64"],
                link_de_pago=pago["link_de_pago"]
            )
        except Exception as error:
            # Si MercadoPago falla (sin internet, token mal puesto),
            # avisamos en la consola y caemos al modo simulado, en vez
            # de dejar al cliente sin poder comprar nada.
            print(f"[MERCADOPAGO] Error creando el pago, usando modo simulado: {error}")

    # --- Camino simulado: como antes ---------------------------------
    aprobado = autorizar_pago_en_servidor(monto_total)

    if not aprobado:
        session["carrito"] = {}
        return redirect(url_for("cliente.pagina_principal", mensaje="Pago rechazado, probá de nuevo"))

    entregas, fallidos = _entregar_carrito(detalles)
    session["carrito"] = {}

    return render_template("confirmacion.html", entregas=entregas, fallidos=fallidos)


@cliente_bp.route("/carrito/estado-pago")
def estado_pago():
    pago_pendiente = session.get("pago_pendiente")

    if not pago_pendiente:
        return jsonify({"aprobado": False, "error": "No hay ningún pago en curso"})

    try:
        aprobado = verificar_pago_aprobado(pago_pendiente["referencia"])
    except Exception as error:
        # Este es el arreglo clave: si la consulta a MercadoPago falla
        # por lo que sea (un hipo de red, una respuesta rara), NO
        # queremos que toda la ruta explote — eso es lo que mataba el
        # polling en silencio. Devolvemos "todavía no" y dejamos que el
        # próximo intento, en unos segundos, lo resuelva solo.
        print(f"[MERCADOPAGO] Error consultando el estado del pago, reintentando: {error}")
        return jsonify({"aprobado": False})

    if not aprobado:
        return jsonify({"aprobado": False})

    entregas, fallidos = _entregar_carrito(pago_pendiente["detalles"])

    session["resultado_pago"] = {"entregas": entregas, "fallidos": fallidos}
    session.pop("pago_pendiente", None)

    return jsonify({"aprobado": True})


@cliente_bp.route("/carrito/resultado")
def ver_resultado_pago():
    resultado = session.pop("resultado_pago", None)

    if resultado is None:
        return redirect(url_for("cliente.pagina_principal"))

    return render_template(
        "confirmacion.html",
        entregas=resultado["entregas"],
        fallidos=resultado["fallidos"]
    )
