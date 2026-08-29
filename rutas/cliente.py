"""
Rutas que usa el cliente que compra: la página principal, hacer un
pedido, y consultar el estado del stock (para el polling automático).

Estas rutas no saben nada de contraseñas ni de sesiones — ese tema es
responsabilidad exclusiva de admin.py. Cada archivo de rutas se ocupa
solo de "su" tipo de usuario.
"""

from flask import Blueprint, render_template, jsonify, request

from datos.inventario import obtener_productos_en_venta, obtener_producto, descontar_stock
from datos.slots import obtener_slot_por_producto
from datos.ventas import registrar_venta
from simuladores import arduino, autorizar_pago_en_servidor

cliente_bp = Blueprint("cliente", __name__)


@cliente_bp.route("/")
def pagina_principal():
    # obtener_productos_en_venta() (no obtener_inventario_completo())
    # es la clave de todo este cambio: solo trae productos que ESTÁN
    # puestos en algún slot ahora mismo. Un producto que existe en el
    # catálogo pero no está asignado a ninguna compuerta, simplemente no
    # aparece acá — la tienda nunca se entera de que existe.
    productos = obtener_productos_en_venta()
    return render_template("tienda.html", inventario=productos)


@cliente_bp.route("/estado")
def estado_actual():
    return jsonify(obtener_productos_en_venta())


@cliente_bp.route("/pedido", methods=["POST"])
def procesar_pedido_web():
    datos_pedido = request.get_json()
    producto = datos_pedido.get("producto")

    datos_producto = obtener_producto(producto)

    if datos_producto is None:
        return jsonify({"ok": False, "mensaje": "Ese producto no existe"})

    # Este chequeo es nuevo y es justo el que evita el problema que
    # charlamos: aunque alguien intente comprar un producto directamente
    # (sin pasar por los botones de la tienda), si ese producto ya no
    # tiene un slot asignado, la venta se rechaza acá — nunca se le
    # cobra a nadie algo que no hay dónde entregar.
    slot_id = obtener_slot_por_producto(producto)
    if slot_id is None:
        return jsonify({"ok": False, "mensaje": "Ese producto ya no está disponible"})

    if datos_producto["stock"] <= 0:
        return jsonify({"ok": False, "mensaje": "Sin stock disponible"})

    aprobado = autorizar_pago_en_servidor(datos_producto["precio"])
    if not aprobado:
        return jsonify({"ok": False, "mensaje": "Pago rechazado, probá de nuevo"})

    entregado = arduino.abrir_compuerta(slot_id)
    if not entregado:
        return jsonify({"ok": False, "mensaje": "Se cobró pero no se detectó la entrega. Contactá soporte"})

    descontar_stock(producto)
    registrar_venta(producto, datos_producto["precio"])

    producto_actualizado = obtener_producto(producto)
    return jsonify({
        "ok": True,
        "mensaje": f"Listo, retirá tu {producto}. Stock restante: {producto_actualizado['stock']}"
    })
