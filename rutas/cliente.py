"""
Rutas que usa el cliente que compra: la página principal, hacer un
pedido, y consultar el estado del stock (para el polling automático).

Estas rutas no saben nada de contraseñas ni de sesiones — ese tema es
responsabilidad exclusiva de admin.py. Cada archivo de rutas se ocupa
solo de "su" tipo de usuario.
"""

from flask import Blueprint, render_template, jsonify, request

from datos.inventario import obtener_inventario_completo, obtener_producto, descontar_stock
from datos.ventas import registrar_venta
from simuladores import arduino, autorizar_pago_en_servidor

# Un Blueprint es un "grupo de rutas" que se define acá, separado del
# resto, y que después se conecta a la aplicación principal en app.py
# con app.register_blueprint(). Es la pieza de Flask que permite partir
# las rutas en varios archivos en vez de tenerlas todas juntas en uno.
cliente_bp = Blueprint("cliente", __name__)


@cliente_bp.route("/")
def pagina_principal():
    inventario = obtener_inventario_completo()

    # render_template (a diferencia de render_template_string, que
    # usábamos antes) busca el HTML en un ARCHIVO dentro de la carpeta
    # templates/ — esto separa el HTML del Python de una vez por todas,
    # y de paso le pasamos el inventario para que la plantilla arme los
    # botones ella misma con un bucle {% for %}, en vez de que Python
    # tenga que armar el HTML a mano concatenando strings.
    return render_template("tienda.html", inventario=inventario)


@cliente_bp.route("/estado")
def estado_actual():
    return jsonify(obtener_inventario_completo())


@cliente_bp.route("/pedido", methods=["POST"])
def procesar_pedido_web():
    datos_pedido = request.get_json()
    producto = datos_pedido.get("producto")

    slot = obtener_producto(producto)

    if slot is None:
        return jsonify({"ok": False, "mensaje": "Ese producto no existe"})

    if slot["stock"] <= 0:
        return jsonify({"ok": False, "mensaje": "Sin stock disponible"})

    aprobado = autorizar_pago_en_servidor(slot["precio"])
    if not aprobado:
        return jsonify({"ok": False, "mensaje": "Pago rechazado, probá de nuevo"})

    entregado = arduino.abrir_compuerta(slot["slot"])
    if not entregado:
        return jsonify({"ok": False, "mensaje": "Se cobró pero no se detectó la entrega. Contactá soporte"})

    descontar_stock(producto)

    # Justo acá, con la venta ya 100% confirmada (pago aprobado y
    # entrega detectada por el sensor), la anotamos en el historial.
    # Este es el único lugar de todo el proyecto donde se escribe en la
    # tabla ventas — así nunca puede quedar una venta anotada que en
    # realidad no se entregó.
    registrar_venta(producto, slot["precio"])

    slot_actualizado = obtener_producto(producto)
    return jsonify({
        "ok": True,
        "mensaje": f"Listo, retirá tu {producto}. Stock restante: {slot_actualizado['stock']}"
    })
