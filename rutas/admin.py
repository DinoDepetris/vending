"""
Rutas del panel de reposición: login, ver y reponer stock, cerrar
sesión. Todo lo que tiene que ver con la contraseña y la sesión vive
acá, separado por completo de las rutas del cliente.
"""

from flask import Blueprint, render_template, request, session, redirect, Response
import csv
import io

from datos.inventario import obtener_productos_en_venta, reponer_stock, retirar_stock, crear_o_actualizar_producto
from datos.slots import obtener_todos_los_slots, asignar_producto_a_slot, vaciar_slot, agregar_slots_nuevos
from datos.ventas import obtener_resumen_por_producto, obtener_total_general, obtener_ventas_recientes, obtener_todas_las_ventas
from config import CONTRASEÑA_ADMIN

admin_bp = Blueprint("admin", __name__)

# Ojo: en app.py, este blueprint se registra con url_prefix="/admin".
# Eso significa que la ruta "/" definida acá abajo en realidad termina
# siendo "/admin", "/login" termina siendo "/admin/login", etc. — así
# no hace falta repetir "/admin" en cada decorador de este archivo.


@admin_bp.route("")
def panel_admin():
    if not session.get("autenticado"):
        return render_template("admin_login.html")

    # Cambio clave: antes usaba obtener_inventario_completo(), que trae
    # TODO el catálogo exista o no en algún slot. Eso causaba el bug que
    # reportaste — un producto recién vaciado de su slot seguía
    # apareciendo acá para reponerle stock, aunque ya no estuviera a la
    # venta en ningún lado. obtener_productos_en_venta() es la misma
    # función que ya usa la tienda: solo trae lo que tiene slot asignado
    # ahora mismo, así las dos pantallas quedan siempre consistentes.
    inventario = obtener_productos_en_venta()
    return render_template("admin_panel.html", inventario=inventario)


@admin_bp.route("/login", methods=["POST"])
def admin_login():
    contraseña_ingresada = request.form.get("contraseña")

    if contraseña_ingresada == CONTRASEÑA_ADMIN:
        session["autenticado"] = True

    return redirect("/admin")


@admin_bp.route("/logout")
def admin_logout():
    session.pop("autenticado", False)
    return redirect("/admin")


@admin_bp.route("/reponer", methods=["POST"])
def admin_reponer():
    # Chequeamos la sesión ACÁ TAMBIÉN, no solo en panel_admin(). Si
    # alguien mandara un pedido directo a esta ruta sin pasar por el
    # panel, sin este chequeo podría reponer stock sin haber puesto la
    # contraseña nunca. Cada ruta que modifica datos se protege a sí
    # misma — nunca confiamos en que "seguro pasó primero por la otra".
    if not session.get("autenticado"):
        return redirect("/admin")

    producto = request.form.get("producto")
    cantidad = int(request.form.get("cantidad", 0))

    if cantidad > 0:
        reponer_stock(producto, cantidad)

    return redirect("/admin")


@admin_bp.route("/retirar", methods=["POST"])
def admin_retirar():
    if not session.get("autenticado"):
        return redirect("/admin")

    producto = request.form.get("producto")
    cantidad = int(request.form.get("cantidad", 0))

    if cantidad > 0:
        retirar_stock(producto, cantidad)

    return redirect("/admin")


@admin_bp.route("/ventas")
def panel_ventas():
    if not session.get("autenticado"):
        return redirect("/admin")

    resumen = obtener_resumen_por_producto()
    total = obtener_total_general()
    recientes = obtener_ventas_recientes(20)

    return render_template(
        "admin_ventas.html",
        resumen=resumen,
        total=total,
        recientes=recientes
    )


@admin_bp.route("/ventas/exportar")
def exportar_ventas():
    if not session.get("autenticado"):
        return redirect("/admin")

    ventas = obtener_todas_las_ventas()

    # io.StringIO() crea un "archivo de texto en memoria" — se comporta
    # como un archivo (le podés escribir líneas), pero vive en RAM en
    # vez de en el disco, porque este CSV es descartable: se genera al
    # vuelo para esta descarga puntual y no necesitamos guardarlo.
    buffer = io.StringIO()
    escritor = csv.writer(buffer)

    # La primera fila de un CSV son los nombres de columna — Excel la
    # usa para poner los encabezados arriba de cada columna.
    escritor.writerow(["fecha_hora", "producto", "precio"])

    for venta in ventas:
        escritor.writerow([venta["fecha_hora"], venta["producto"], venta["precio"]])

    # Response arma la respuesta HTTP a mano, en vez del jsonify o
    # render_template que veníamos usando. El header Content-Disposition
    # con "attachment" es lo que le dice al navegador "esto no es para
    # mostrar en pantalla, es para descargar como archivo" — y
    # filename=ventas.csv define el nombre que va a tener al bajarlo.
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ventas.csv"}
    )


@admin_bp.route("/slots")
def panel_slots():
    if not session.get("autenticado"):
        return redirect("/admin")

    slots = obtener_todos_los_slots()
    return render_template("admin_slots.html", slots=slots)


@admin_bp.route("/slots/asignar", methods=["POST"])
def slots_asignar():
    if not session.get("autenticado"):
        return redirect("/admin")

    slot_id = int(request.form.get("slot_id"))
    producto = request.form.get("producto")
    precio = int(request.form.get("precio", 0))
    stock = int(request.form.get("stock", 0))

    # crear_o_actualizar_producto es el "upsert" que vimos: si el nombre
    # ya existe en el catálogo (por ejemplo, reasignás "coca_500" a otro
    # slot), actualiza su precio/stock; si es un nombre nuevo, lo crea.
    # Así, un solo formulario cubre tanto "poner un producto que ya
    # tenía" como "dar de alta uno completamente nuevo".
    crear_o_actualizar_producto(producto, precio, stock)
    asignar_producto_a_slot(slot_id, producto)

    return redirect("/admin/slots")


@admin_bp.route("/slots/vaciar", methods=["POST"])
def slots_vaciar():
    if not session.get("autenticado"):
        return redirect("/admin")

    slot_id = int(request.form.get("slot_id"))
    vaciar_slot(slot_id)

    return redirect("/admin/slots")


@admin_bp.route("/slots/agregar", methods=["POST"])
def slots_agregar():
    if not session.get("autenticado"):
        return redirect("/admin")

    cantidad = int(request.form.get("cantidad", 0))
    if cantidad > 0:
        agregar_slots_nuevos(cantidad)

    return redirect("/admin/slots")
