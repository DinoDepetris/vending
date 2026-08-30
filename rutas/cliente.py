"""
Rutas que usa el cliente que compra: la página principal, hacer un
pedido (ahora un CARRITO con varios productos y cantidades, no uno
solo), y consultar el estado del stock (para el polling automático).

Estas rutas no saben nada de contraseñas ni de sesiones — ese tema es
responsabilidad exclusiva de admin.py.
"""

from flask import Blueprint, render_template, jsonify, request

from datos.inventario import obtener_productos_en_venta, obtener_producto, descontar_stock
from datos.slots import obtener_slot_por_producto
from datos.ventas import registrar_venta
from simuladores import arduino, autorizar_pago_en_servidor

cliente_bp = Blueprint("cliente", __name__)


@cliente_bp.route("/")
def pagina_principal():
    productos = obtener_productos_en_venta()
    return render_template("tienda.html", inventario=productos)


@cliente_bp.route("/estado")
def estado_actual():
    return jsonify(obtener_productos_en_venta())


@cliente_bp.route("/pedido", methods=["POST"])
def procesar_pedido_web():
    # Ahora el cuerpo del pedido no es {"producto": "..."} sino
    # {"items": [{"producto": "...", "cantidad": N}, ...]} — una lista,
    # porque el carrito puede traer varios productos distintos a la vez.
    datos_pedido = request.get_json()
    items = datos_pedido.get("items", [])

    if not items:
        return jsonify({"ok": False, "mensaje": "El carrito está vacío"})

    # --- PASO 1: validar TODO el carrito antes de cobrar un solo peso ---
    # Recorremos cada línea del carrito y juntamos sus datos reales
    # (precio, slot) desde la base de datos — nunca confiamos en el
    # precio que pueda venir del navegador, solo en el nombre del
    # producto y la cantidad pedida. Si cualquier línea falla, cortamos
    # acá, antes de tocar el pago o el stock de nada.
    detalles = []
    monto_total = 0

    for item in items:
        producto = item.get("producto")
        cantidad = item.get("cantidad", 0)

        if cantidad <= 0:
            continue

        datos_producto = obtener_producto(producto)
        if datos_producto is None:
            return jsonify({"ok": False, "mensaje": f"'{producto}' no existe"})

        slot_id = obtener_slot_por_producto(producto)
        if slot_id is None:
            return jsonify({"ok": False, "mensaje": f"'{producto}' ya no está disponible"})

        if datos_producto["stock"] < cantidad:
            return jsonify({
                "ok": False,
                "mensaje": f"No hay suficiente stock de {producto} (quedan {datos_producto['stock']})"
            })

        monto_total += datos_producto["precio"] * cantidad
        detalles.append({
            "producto": producto,
            "cantidad": cantidad,
            "precio": datos_producto["precio"],
            "slot": slot_id
        })

    if not detalles:
        return jsonify({"ok": False, "mensaje": "El carrito está vacío"})

    # --- PASO 2: un único cobro por el total del carrito -----------------
    # Cobramos UNA sola vez, por la suma de todo — así es como funciona
    # un carrito real: no tiene sentido autorizar el pago producto por
    # producto si el cliente está comprando varias cosas juntas.
    aprobado = autorizar_pago_en_servidor(monto_total)
    if not aprobado:
        return jsonify({"ok": False, "mensaje": "Pago rechazado, probá de nuevo"})

    # --- PASO 3: entregar cada unidad de cada producto --------------------
    # Ya con el pago aprobado, vamos slot por slot. Guardamos qué se
    # entregó bien y qué no, porque en la vida real un carrito con 3
    # productos puede fallar en la entrega de uno solo (un atasco), y el
    # cliente necesita saber exactamente qué sí retiró y qué no.
    entregados = 0
    productos_fallidos = []

    for detalle in detalles:
        for _ in range(detalle["cantidad"]):
            entregado = arduino.abrir_compuerta(detalle["slot"])

            if entregado:
                descontar_stock(detalle["producto"])
                registrar_venta(detalle["producto"], detalle["precio"])
                entregados += 1
            else:
                productos_fallidos.append(detalle["producto"])

    if productos_fallidos:
        fallidos_unicos = ", ".join(sorted(set(productos_fallidos)))
        mensaje = (
            f"Se entregaron {entregados} producto(s). "
            f"Hubo un problema entregando: {fallidos_unicos}. Contactá soporte."
        )
    else:
        mensaje = f"¡Listo! Retirá tus {entregados} producto(s)."

    return jsonify({"ok": True, "mensaje": mensaje})
