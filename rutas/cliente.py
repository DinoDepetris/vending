"""
Rutas que usa el cliente que compra. El pago ahora puede ser real, vía
MercadoPago (QR + polling), o simulado como antes — depende de si
config_secretos.py tiene el Access Token cargado. Esto es a propósito:
si algo del lado de MercadoPago fallara, el vending sigue pudiendo
"vender" en modo simulado en vez de quedar totalmente roto.
"""

import time
import threading
import queue
import uuid

from flask import Blueprint, render_template, jsonify, request, session, redirect, url_for

from datos.inventario import (
    obtener_productos_en_venta, obtener_producto, descontar_stock, marcar_alerta_enviada,
    obtener_productos_en_venta_por_categorias, obtener_productos_en_venta_sin_categoria
)
from datos.slots import obtener_slot_por_producto
from datos.ventas import registrar_venta
from datos.categorias import (
    obtener_categorias_raiz_con_productos, obtener_ids_con_descendientes, obtener_categoria,
    obtener_subcategorias_directas, contar_subcategorias
)
from simuladores import arduino, autorizar_pago_en_servidor
from notificaciones import enviar_alerta_stock_bajo
from config import UMBRAL_STOCK_BAJO, MERCADOPAGO_HABILITADO, UMBRAL_SEGUNDOS_PAGO_PENDIENTE, TIEMPO_INACTIVIDAD_SEGUNDOS
from pagos_mercadopago import crear_pago_con_qr, obtener_pagos_de_referencia, cancelar_pago
from datos.incidentes import registrar_incidente

cliente_bp = Blueprint("cliente", __name__)


# ---------------------------------------------------------------------------
# RUTA TEMPORAL DE DIAGNÓSTICO — sacar cuando ya no haga falta
# ---------------------------------------------------------------------------
# Sirve para una sola cosa: que la propia tablet nos diga en qué medida
# real está mostrando la página, en vez de adivinarlo desde la ficha
# técnica del fabricante (que da los píxeles FÍSICOS, no los que
# realmente usa el navegador para calcular tamaños).
@cliente_bp.route("/debug-pantalla")
def debug_pantalla():
    return render_template("debug_pantalla.html")


def _obtener_carrito():
    return session.setdefault("carrito", {})


def _resumen_carrito():
    carrito = _obtener_carrito()
    lineas = []
    total = 0

    for producto, cantidad in carrito.items():
        datos_producto = obtener_producto(producto)
        precio = datos_producto["precio"] if datos_producto else 0
        stock = datos_producto["stock"] if datos_producto else 0
        subtotal = precio * cantidad
        total += subtotal
        lineas.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": precio,
            "subtotal": subtotal,
            "stock": stock
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


# Acá guardamos, en memoria, el estado de cada entrega que está
# corriendo en un hilo aparte. Un hilo de Python no tiene acceso
# directo a la sesión del navegador (la sesión es propia de cada
# request HTTP) — por eso usamos un "token" como puente: se lo
# guardamos al cliente en su sesión, y con ese token después puede
# preguntar acá adentro cómo va su entrega.
_entregas_en_progreso = {}

# Un "lock" evita que dos hilos lean/escriban este diccionario al
# mismo tiempo y lo dejen en un estado inconsistente.
_entregas_lock = threading.Lock()

# Cola FIFO ("primero que entra, primero que sale"): todas las
# entregas pasan por acá, y las procesa UN SOLO hilo trabajador, una
# por vez, en el mismo orden en que llegaron. Esto refleja la
# realidad física del sistema: hay un solo carro y un solo Arduino, así
# que no tiene sentido (ni es seguro) que dos entregas le hablen al
# mismo tiempo — mejor que hagan fila, como harían dos clientes reales
# parados frente a la máquina.
_cola_entregas = queue.Queue()


def _trabajador_de_entregas():
    # Este hilo vive para siempre, corriendo de fondo desde que
    # arranca la app. queue.get() se queda esperando sin gastar CPU
    # hasta que aparezca algo nuevo en la cola; lo procesa, y vuelve a
    # esperar el siguiente — uno por vez, en orden de llegada.
    while True:
        token, detalles = _cola_entregas.get()

        # Recién ahora, cuando el trabajador efectivamente empieza a
        # ocuparse de ESTA entrega (y no antes, mientras esperaba su
        # turno en la cola), la marcamos como "en_progreso". Antes de
        # esto estaba en "en_cola" — la diferencia es lo que le
        # permite a la pantalla del cliente mostrar "hay un pedido
        # antes que el tuyo" en vez de "preparando tu pedido" cuando
        # todavía ni arrancó.
        with _entregas_lock:
            _entregas_en_progreso[token]["estado"] = "en_progreso"

        entregas, fallidos = _entregar_carrito(detalles)

        with _entregas_lock:
            _entregas_en_progreso[token] = {
                "estado": "completo",
                "entregas": entregas,
                "fallidos": fallidos
            }

        _cola_entregas.task_done()


# Arrancamos el único hilo trabajador acá mismo, una sola vez, apenas
# se importa este archivo (que ocurre una vez por proceso, cuando
# Flask arma la aplicación). daemon=True para que este hilo no le
# impida cerrar al proceso si hiciera falta.
threading.Thread(target=_trabajador_de_entregas, daemon=True).start()


def _iniciar_entrega_en_segundo_plano(detalles):
    # Ya no arranca un hilo nuevo por cada compra (eso era lo que
    # permitía que dos entregas corrieran "en paralelo" compitiendo
    # por el mismo Arduino). En cambio, anota esta entrega en la cola
    # FIFO, y el único hilo trabajador (_trabajador_de_entregas) la va
    # a ir tomando cuando le toque el turno. Devuelve un token, igual
    # que antes, para poder consultar el progreso desde
    # /carrito/estado-entrega.
    token = uuid.uuid4().hex

    with _entregas_lock:
        _entregas_en_progreso[token] = {"estado": "en_cola"}

    _cola_entregas.put((token, detalles))

    return token


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
    # Esta ya no muestra productos directamente — muestra la botonera
    # de categorías (Bebidas, Snacks, etc.), y solo las que tienen al
    # menos un producto a la venta ahora mismo.
    categorias = obtener_categorias_raiz_con_productos()
    resumen = _resumen_carrito()
    mensaje = request.args.get("mensaje")

    return render_template(
        "categorias.html",
        categorias=categorias,
        resumen=resumen,
        mensaje=mensaje,
        tiempo_inactividad=TIEMPO_INACTIVIDAD_SEGUNDOS
    )


@cliente_bp.route("/categoria/<categoria_id>")
def ver_categoria(categoria_id):
    if categoria_id == "otros":
        productos = obtener_productos_en_venta_sin_categoria()
        resumen = _resumen_carrito()
        return render_template(
            "tienda.html",
            inventario=productos,
            categoria_nombre="Otros",
            volver_a="/",
            resumen=resumen,
            tiempo_inactividad=TIEMPO_INACTIVIDAD_SEGUNDOS
        )

    categoria_id_numero = int(categoria_id)
    categoria = obtener_categoria(categoria_id_numero)
    nombre_categoria = categoria["nombre"] if categoria else "Categoría"

    # A dónde tiene que volver el botón "atrás": si esta categoría tiene
    # padre, vuelve a la pantalla de subcategorías de ese padre. Si no
    # tiene padre (es una categoría raíz), vuelve directo al inicio.
    padre_id = categoria["categoria_padre_id"] if categoria else None
    volver_a = f"/categoria/{padre_id}" if padre_id is not None else "/"

    subcategorias = obtener_subcategorias_directas(categoria_id_numero)
    resumen = _resumen_carrito()

    if subcategorias:
        # Nivel intermedio: esta categoría tiene hijas, así que
        # mostramos SUS botones — no bajamos directo a productos
        # todavía. También traemos los productos asignados
        # DIRECTAMENTE a esta categoría (sin pasar por ninguna
        # subcategoría), por si hay alguno — si no, esa lista queda
        # vacía y la plantilla simplemente no muestra esa sección.
        productos_directos = obtener_productos_en_venta_por_categorias({categoria_id_numero})

        return render_template(
            "subcategorias.html",
            categoria_nombre=nombre_categoria,
            subcategorias=subcategorias,
            productos_directos=productos_directos,
            volver_a=volver_a,
            resumen=resumen,
            tiempo_inactividad=TIEMPO_INACTIVIDAD_SEGUNDOS
        )

    # Nivel hoja: esta categoría no tiene hijas, así que mostramos sus
    # productos directamente — no hace falta juntar descendientes,
    # porque no tiene ninguno.
    productos = obtener_productos_en_venta_por_categorias({categoria_id_numero})

    return render_template(
        "tienda.html",
        inventario=productos,
        categoria_nombre=nombre_categoria,
        volver_a=volver_a,
        resumen=resumen,
        tiempo_inactividad=TIEMPO_INACTIVIDAD_SEGUNDOS
    )


@cliente_bp.route("/estado")
def estado_actual():
    return jsonify(obtener_productos_en_venta())


def _ajustar_cantidad_carrito(producto, delta):
    # Función interna que usan TODAS las rutas que cambian una cantidad
    # (agregar, sumar de a uno, restar de a uno) — es el único lugar
    # donde vive la regla "nunca más de lo que hay en stock". Si esta
    # regla viviera repetida en cada ruta, alguna se nos podría escapar
    # y quedaría un agujero por donde comprar de más.
    datos_producto = obtener_producto(producto)
    stock_disponible = datos_producto["stock"] if datos_producto else 0

    carrito = _obtener_carrito()
    cantidad_actual = carrito.get(producto, 0)
    nueva_cantidad = cantidad_actual + delta

    # max(0, ...) evita que baje de cero; min(..., stock_disponible)
    # evita que suba más del stock real, sin importar cuántas veces se
    # apriete "+" — el límite se aplica siempre, no solo la primera vez.
    nueva_cantidad = max(0, min(nueva_cantidad, stock_disponible))

    if nueva_cantidad <= 0:
        carrito.pop(producto, None)
    else:
        carrito[producto] = nueva_cantidad

    session["carrito"] = carrito


@cliente_bp.route("/carrito/agregar", methods=["POST"])
def carrito_agregar():
    datos = request.get_json()
    producto = datos.get("producto")
    cantidad = int(datos.get("cantidad", 0))

    if cantidad > 0:
        _ajustar_cantidad_carrito(producto, cantidad)

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


@cliente_bp.route("/carrito/ajustar", methods=["POST"])
def carrito_ajustar():
    datos = request.get_json()
    producto = datos.get("producto")
    delta = int(datos.get("delta", 0))

    _ajustar_cantidad_carrito(producto, delta)

    return jsonify(_resumen_carrito())


@cliente_bp.route("/carrito/ajustar-form", methods=["POST"])
def carrito_ajustar_form():
    producto = request.form.get("producto")
    delta = int(request.form.get("delta", 0))

    _ajustar_cantidad_carrito(producto, delta)

    return redirect(url_for("cliente.ver_carrito"))


@cliente_bp.route("/carrito")
def ver_carrito():
    resumen = _resumen_carrito()
    return render_template(
        "carrito.html",
        resumen=resumen,
        tiempo_inactividad=TIEMPO_INACTIVIDAD_SEGUNDOS
    )


@cliente_bp.route("/reposo")
def pantalla_reposo():
    # Esta pantalla es a propósito la única que NO incluye el
    # temporizador de inactividad — ya está en reposo, no tiene a
    # dónde más "caer". Cualquier toque la manda de vuelta al inicio.
    return render_template("reposo.html")


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
                "detalles": detalles,
                "creado_en": time.time()
            }
            session["carrito"] = {}

            return render_template(
                "pagando.html",
                qr_base64=pago["qr_base64"],
                link_de_pago=pago["link_de_pago"],
                referencia=pago["referencia"],
                umbral_segundos=UMBRAL_SEGUNDOS_PAGO_PENDIENTE
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

    token = _iniciar_entrega_en_segundo_plano(detalles)
    session["token_entrega"] = token
    session["carrito"] = {}

    return render_template("confirmacion.html", detalles=detalles)


# ---------------------------------------------------------------------------
# BOTÓN TEMPORAL DE PRUEBA — sacar antes de producción
# ---------------------------------------------------------------------------
# Este camino existe solo para poder seguir probando el resto del sistema
# (entrega, stock, ventas, alertas) mientras el sandbox de MercadoPago
# anda fallando. A diferencia del camino simulado normal (que igual
# depende de un "dado" al azar, para poder ver el caso de rechazo), este
# aprueba SIEMPRE, sin excepción — para no perder tiempo reintentando
# si te toca el 15% de rechazo justo cuando querés probar otra cosa.
@cliente_bp.route("/carrito/pagar-simulado", methods=["POST"])
def carrito_pagar_simulado():
    carrito = _obtener_carrito()

    if not carrito:
        return redirect(url_for("cliente.ver_carrito"))

    detalles, monto_total, redireccion_si_error = _validar_carrito(carrito)
    if redireccion_si_error:
        return redireccion_si_error

    token = _iniciar_entrega_en_segundo_plano(detalles)
    session["token_entrega"] = token
    session["carrito"] = {}

    return render_template("confirmacion.html", detalles=detalles)


@cliente_bp.route("/carrito/estado-pago")
def estado_pago():
    pago_pendiente = session.get("pago_pendiente")

    if not pago_pendiente:
        return jsonify({"aprobado": False, "error": "No hay ningún pago en curso"})

    try:
        pagos = obtener_pagos_de_referencia(pago_pendiente["referencia"])
    except Exception as error:
        # Este es el arreglo clave del otro día: si la consulta a
        # MercadoPago falla por lo que sea (un hipo de red, una
        # respuesta rara), NO queremos que toda la ruta explote — eso
        # es lo que mataba el polling en silencio. Devolvemos "todavía
        # no" y dejamos que el próximo intento lo resuelva solo.
        print(f"[MERCADOPAGO] Error consultando el estado del pago, reintentando: {error}")
        return jsonify({"aprobado": False})

    if any(pago["status"] == "approved" for pago in pagos):
        detalles = pago_pendiente["detalles"]
        token = _iniciar_entrega_en_segundo_plano(detalles)

        # Guardamos el token (para consultar el progreso) y los
        # detalles (para poder mostrar la lista de productos/puertas
        # en la pantalla de confirmación desde el primer instante,
        # sin tener que esperar a que la entrega termine para saber
        # qué se estaba entregando).
        session["token_entrega"] = token
        session["detalles_entrega"] = detalles
        session.pop("pago_pendiente", None)

        return jsonify({"aprobado": True})

    # Todavía no está aprobado. Antes de simplemente decir "seguí
    # esperando", chequeamos cuánto tiempo pasó desde que se creó este
    # pago — un vending no puede dejar a alguien parado esperando para
    # siempre a que MercadoPago termine de decidir.
    tiempo_transcurrido = time.time() - pago_pendiente["creado_en"]

    if tiempo_transcurrido > UMBRAL_SEGUNDOS_PAGO_PENDIENTE:
        # Cancelamos activamente cualquier pago que haya quedado en
        # pending/in_process — esto es lo que libera al cliente para
        # reintentar YA, en vez de dejar la transacción "flotando" del
        # lado de MercadoPago hasta que se resuelva sola, horas después.
        for pago in pagos:
            if pago["status"] in ("pending", "in_process"):
                try:
                    cancelar_pago(pago["id"])
                except Exception as error:
                    print(f"[MERCADOPAGO] No se pudo cancelar el pago {pago['id']}: {error}")

        # Antes de descartar la sesión, dejamos un rastro de qué había
        # que entregar. Cancelar de nuestro lado no garantiza al 100%
        # que MercadoPago no termine cobrando igual (por una demora en
        # procesar la cancelación, o porque el cliente ya tenía la
        # tarjeta cargada en otra pestaña) — sin este registro, esa
        # plata podría quedar cobrada sin que nadie sepa qué se le
        # debía al cliente a cambio.
        registrar_incidente(
            referencia=pago_pendiente["referencia"],
            detalles=pago_pendiente["detalles"],
            motivo="Cancelado por demora — revisar manualmente si MercadoPago lo cobró igual"
        )

        session.pop("pago_pendiente", None)
        return jsonify({"aprobado": False, "cancelado": True})

    return jsonify({"aprobado": False})


@cliente_bp.route("/carrito/resultado")
def ver_resultado_pago():
    detalles = session.pop("detalles_entrega", None)

    if detalles is None:
        return redirect(url_for("cliente.pagina_principal"))

    return render_template("confirmacion.html", detalles=detalles)


@cliente_bp.route("/carrito/estado-entrega")
def estado_entrega():
    # Mismo patrón que estado_pago(): esta ruta la consulta el
    # JavaScript de confirmacion.html cada 1 segundo, preguntando si
    # el hilo de fondo que abre las puertas ya terminó.
    token = session.get("token_entrega")

    if not token:
        return jsonify({"estado": "error"})

    with _entregas_lock:
        resultado = _entregas_en_progreso.get(token)

    if resultado is None:
        return jsonify({"estado": "error"})

    if resultado["estado"] == "completo":
        # Una vez que el cliente ya se enteró del resultado final,
        # limpiamos — ni la sesión ni el diccionario en memoria
        # necesitan seguir guardando esto.
        session.pop("token_entrega", None)
        with _entregas_lock:
            _entregas_en_progreso.pop(token, None)

        return jsonify({
            "estado": "completo",
            "entregas": resultado["entregas"],
            "fallidos": resultado["fallidos"]
        })

    # Acá puede venir "en_cola" (todavía no le tocó el turno) o
    # "en_progreso" (el hilo trabajador ya está con esta entrega ahora
    # mismo) — se lo pasamos tal cual al navegador, así la pantalla
    # puede distinguir un caso del otro.
    return jsonify({"estado": resultado["estado"]})
