"""
Rutas que usa el cliente que compra. Ahora el flujo tiene tres
pantallas distintas (tienda, carrito, confirmación), así que el carrito
ya no puede vivir solo en la memoria del navegador como antes — tiene
que sobrevivir a la navegación entre páginas. Por eso lo guardamos en
la SESIÓN de Flask, la misma herramienta que ya usa el login del panel
de admin: una cookie que identifica a este navegador puntual, con datos
guardados del lado del servidor asociados a esa cookie.
"""

from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for

from datos.inventario import obtener_productos_en_venta, obtener_producto, descontar_stock
from datos.slots import obtener_slot_por_producto
from datos.ventas import registrar_venta
from simuladores import arduino, autorizar_pago_en_servidor

cliente_bp = Blueprint("cliente", __name__)


def _obtener_carrito():
    # session.setdefault: si esta sesión todavía no tiene un carrito
    # guardado (primera visita), le crea uno vacío. Si ya tenía uno, lo
    # devuelve tal cual — así el resto del código no tiene que chequear
    # "¿existe o no?" en cada lugar donde usa el carrito.
    return session.setdefault("carrito", {})


def _resumen_carrito():
    # Arma la información completa del carrito (nombre, cantidad,
    # precio ACTUAL, subtotal) a partir del diccionario simple que
    # guardamos en la sesión (que solo tiene producto -> cantidad). El
    # precio se busca fresco en la base de datos cada vez, nunca se
    # guarda en la sesión — así, si un precio cambia, el carrito
    # siempre refleja el valor real, no uno viejo.
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

    # Ojo con este detalle: la clave se llama "lineas", NO "items". Un
    # diccionario de Python ya tiene un método llamado .items() de
    # fábrica — si la clave se llamara igual, en las plantillas HTML
    # "resumen.items" agarraría ESE método en vez de nuestro dato,
    # rompiendo todo de una forma bastante confusa de diagnosticar.
    return {
        "lineas": lineas,
        "total": total,
        "cantidad_total": sum(carrito.values())
    }


@cliente_bp.route("/")
def pagina_principal():
    productos = obtener_productos_en_venta()
    resumen = _resumen_carrito()

    # Si venimos de un pago rechazado, ver_carrito nos manda de vuelta
    # acá con un mensaje en la URL (?mensaje=...) — lo leemos para
    # mostrarlo apenas carga la página, en vez del texto genérico.
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
    # Esta ruta la llama JavaScript (fetch) desde la tienda, sin recargar
    # la página — por eso devuelve JSON, no una página HTML.
    datos = request.get_json()
    producto = datos.get("producto")
    cantidad = int(datos.get("cantidad", 0))

    if cantidad > 0:
        carrito = _obtener_carrito()
        carrito[producto] = carrito.get(producto, 0) + cantidad

        # Reasignar session["carrito"] (en vez de solo mutar el
        # diccionario que ya teníamos) es necesario para que Flask se
        # entere de que la sesión cambió y la vuelva a guardar en la
        # cookie. Mutar un diccionario "in place" a veces no alcanza
        # para que Flask detecte el cambio solo.
        session["carrito"] = carrito

    return jsonify(_resumen_carrito())


@cliente_bp.route("/carrito/quitar", methods=["POST"])
def carrito_quitar():
    # Versión JSON, para el botón "Quitar" de la vista previa rápida
    # (la que se despliega desde el ícono del carrito, sin cambiar de
    # página).
    datos = request.get_json()
    producto = datos.get("producto")

    carrito = _obtener_carrito()
    carrito.pop(producto, None)
    session["carrito"] = carrito

    return jsonify(_resumen_carrito())


@cliente_bp.route("/carrito/quitar-form", methods=["POST"])
def carrito_quitar_form():
    # Versión "de formulario normal", para el botón "Quitar" de la
    # pantalla completa del carrito — ahí no usamos JavaScript, es un
    # <form> HTML común que recarga la página al enviarse.
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

    # --- PASO 1: validar todo antes de cobrar, igual que antes ----------
    detalles = []
    monto_total = 0

    for producto, cantidad in carrito.items():
        if cantidad <= 0:
            continue

        datos_producto = obtener_producto(producto)
        if datos_producto is None:
            session["carrito"] = {}
            return redirect(url_for("cliente.pagina_principal", mensaje=f"'{producto}' ya no existe, carrito vaciado"))

        slot_id = obtener_slot_por_producto(producto)
        if slot_id is None:
            session["carrito"] = {}
            return redirect(url_for("cliente.pagina_principal", mensaje=f"'{producto}' ya no está disponible, carrito vaciado"))

        if datos_producto["stock"] < cantidad:
            # Este caso sí lo dejamos volver al carrito (no a la
            # tienda), para que puedas ajustar la cantidad vos mismo en
            # vez de perder todo lo demás que ya habías elegido.
            return redirect(url_for("cliente.ver_carrito"))

        monto_total += datos_producto["precio"] * cantidad
        detalles.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": datos_producto["precio"],
            "slot": slot_id
        })

    # --- PASO 2: un único cobro por el total del carrito -----------------
    aprobado = autorizar_pago_en_servidor(monto_total)

    if not aprobado:
        # Pago rechazado: vaciamos el carrito y volvemos directo a la
        # tienda con el aviso, tal como pediste.
        session["carrito"] = {}
        return redirect(url_for("cliente.pagina_principal", mensaje="Pago rechazado, probá de nuevo"))

    # --- PASO 3: entregar cada unidad, anotando en qué puerta salió cada una ---
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
            else:
                productos_fallidos.append(detalle["producto"])

        if entregados_de_este > 0:
            entregas.append({
                "producto": detalle["producto"],
                "cantidad": entregados_de_este,
                "slot": detalle["slot"]
            })

    session["carrito"] = {}

    # A diferencia de las otras rutas, acá no redirigimos — mostramos
    # directamente la pantalla de confirmación con el detalle completo
    # (qué se entregó, de qué puerta). Desde ahí, un temporizador en
    # JavaScript se encarga de volver solo a la tienda después de unos
    # segundos.
    return render_template(
        "confirmacion.html",
        entregas=entregas,
        fallidos=sorted(set(productos_fallidos))
    )
