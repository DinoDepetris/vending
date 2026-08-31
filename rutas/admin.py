"""
Rutas del panel de reposición: login, ver y reponer stock, cerrar
sesión. Todo lo que tiene que ver con la contraseña y la sesión vive
acá, separado por completo de las rutas del cliente.
"""

from flask import Blueprint, render_template, request, session, redirect, Response, url_for
import csv
import io

from datos.inventario import obtener_productos_en_venta, reponer_stock, retirar_stock, crear_o_actualizar_producto
from datos.slots import obtener_todos_los_slots, asignar_producto_a_slot, vaciar_slot, agregar_slots_nuevos
from datos.ventas import (
    obtener_resumen_por_producto, obtener_total_general, obtener_ventas_recientes,
    obtener_todas_las_ventas, obtener_total_hoy, obtener_total_semana, obtener_total_mes
)
from datos.categorias import (
    obtener_categorias_ordenadas, crear_categoria, contar_subcategorias,
    eliminar_categoria, renombrar_categoria
)
from datos.incidentes import obtener_incidentes, marcar_incidente_revisado
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
        recientes=recientes,
        total_hoy=obtener_total_hoy(),
        total_semana=obtener_total_semana(),
        total_mes=obtener_total_mes()
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
    categorias = obtener_categorias_ordenadas()
    return render_template("admin_slots.html", slots=slots, categorias=categorias)


@admin_bp.route("/slots/asignar", methods=["POST"])
def slots_asignar():
    if not session.get("autenticado"):
        return redirect("/admin")

    slot_id = int(request.form.get("slot_id"))
    producto = request.form.get("producto")
    precio = int(request.form.get("precio", 0))
    stock = int(request.form.get("stock", 0))

    # El desplegable manda un string vacío si elegiste "Sin categoría"
    # (o directamente no lo tocaste). "" or None da None — así queda
    # guardado como "sin categoría asignada" en vez de un string vacío
    # sin sentido en la base de datos.
    categoria_id = request.form.get("categoria_id") or None
    if categoria_id:
        categoria_id = int(categoria_id)

    # Igual que categoria_id: si el campo queda vacío, guardamos None
    # (sin foto asignada todavía) en vez de un string vacío.
    imagen = request.form.get("imagen") or None

    crear_o_actualizar_producto(producto, precio, stock, categoria_id, imagen)
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


@admin_bp.route("/categorias")
def panel_categorias():
    if not session.get("autenticado"):
        return redirect("/admin")

    categorias = obtener_categorias_ordenadas()
    mensaje = request.args.get("mensaje")
    return render_template("admin_categorias.html", categorias=categorias, mensaje=mensaje)


@admin_bp.route("/categorias/crear", methods=["POST"])
def categorias_crear():
    if not session.get("autenticado"):
        return redirect("/admin")

    nombre = request.form.get("nombre")
    categoria_padre_id = request.form.get("categoria_padre_id") or None
    if categoria_padre_id:
        categoria_padre_id = int(categoria_padre_id)

    icono = request.form.get("icono") or None

    if nombre:
        crear_categoria(nombre, categoria_padre_id, icono)

    return redirect("/admin/categorias")


@admin_bp.route("/categorias/editar", methods=["POST"])
def categorias_editar():
    if not session.get("autenticado"):
        return redirect("/admin")

    categoria_id = int(request.form.get("categoria_id"))
    nuevo_nombre = request.form.get("nuevo_nombre")

    if nuevo_nombre:
        renombrar_categoria(categoria_id, nuevo_nombre)

    return redirect("/admin/categorias")


@admin_bp.route("/categorias/eliminar", methods=["POST"])
def categorias_eliminar():
    if not session.get("autenticado"):
        return redirect("/admin")

    categoria_id = int(request.form.get("categoria_id"))

    # Esta es la protección clave: si la categoría tiene subcategorías
    # colgando de ella, no la dejamos eliminar sin más — quedarían esas
    # subcategorías "huérfanas" apuntando a un padre que ya no existe.
    # Le pedimos al admin que las borre o reasigne primero, a propósito.
    if contar_subcategorias(categoria_id) > 0:
        return redirect(url_for(
            "admin.panel_categorias",
            mensaje="Esta categoría tiene subcategorías. Eliminalas o movelas primero."
        ))

    eliminar_categoria(categoria_id)
    return redirect("/admin/categorias")


@admin_bp.route("/incidentes")
def panel_incidentes():
    if not session.get("autenticado"):
        return redirect("/admin")

    incidentes = obtener_incidentes()
    return render_template("admin_incidentes.html", incidentes=incidentes)


@admin_bp.route("/incidentes/revisar", methods=["POST"])
def incidentes_revisar():
    if not session.get("autenticado"):
        return redirect("/admin")

    incidente_id = int(request.form.get("incidente_id"))
    marcar_incidente_revisado(incidente_id)

    return redirect("/admin/incidentes")
