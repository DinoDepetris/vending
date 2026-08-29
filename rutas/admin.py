"""
Rutas del panel de reposición: login, ver y reponer stock, cerrar
sesión. Todo lo que tiene que ver con la contraseña y la sesión vive
acá, separado por completo de las rutas del cliente.
"""

from flask import Blueprint, render_template, request, session, redirect, Response
import csv
import io

from datos.inventario import obtener_inventario_completo, reponer_stock
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

    inventario = obtener_inventario_completo()
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
