"""
Todo el acceso a la tabla de ventas vive en este archivo — el "diario"
de cada venta confirmada, separado a propósito de datos/inventario.py.

La diferencia de fondo entre las dos tablas: inventario es una FOTO del
presente (cuánto stock queda ahora mismo, un solo número por producto
que se pisa cada vez que cambia). ventas es un DIARIO de todo lo que
pasó (una fila nueva por cada venta, que nunca se borra ni se pisa) —
por eso necesitan vivir en tablas, y hasta en archivos, separados.
"""

import sqlite3
from datetime import datetime, timedelta

from config import DB_PATH


def obtener_conexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_tabla_ventas():
    conn = obtener_conexion()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            producto TEXT NOT NULL,
            precio INTEGER NOT NULL,
            fecha_hora TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def registrar_venta(producto, precio):
    conn = obtener_conexion()

    # datetime.now().isoformat() guarda la fecha y hora como texto en un
    # formato estándar, por ejemplo "2026-08-29T14:32:07". La ventaja de
    # ese formato puntual es que ordenar alfabéticamente ese texto da el
    # mismo resultado que ordenar cronológicamente — por eso las
    # consultas de "más reciente primero" más abajo funcionan con un
    # simple ORDER BY, sin tener que convertir nada.
    conn.execute(
        "INSERT INTO ventas (producto, precio, fecha_hora) VALUES (?, ?, ?)",
        (producto, precio, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def obtener_ventas_recientes(limite=20):
    conn = obtener_conexion()
    filas = conn.execute(
        "SELECT * FROM ventas ORDER BY fecha_hora DESC LIMIT ?", (limite,)
    ).fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def obtener_todas_las_ventas():
    # Sin límite — la usa la exportación a CSV, que necesita el
    # historial completo, no solo las últimas 20.
    conn = obtener_conexion()
    filas = conn.execute(
        "SELECT * FROM ventas ORDER BY fecha_hora DESC"
    ).fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def obtener_resumen_por_producto():
    conn = obtener_conexion()

    # GROUP BY producto junta todas las filas de un mismo producto en
    # una sola fila de resultado. COUNT(*) cuenta cuántas ventas hubo de
    # ese producto, SUM(precio) suma todo el dinero que generó. Esto es
    # lo que en SQL se llama una consulta "agregada" — le pedimos a la
    # base de datos que haga la cuenta por nosotros, en vez de traer
    # todas las filas a Python y sumarlas ahí (más lento y más código).
    filas = conn.execute("""
        SELECT producto, COUNT(*) as cantidad, SUM(precio) as total
        FROM ventas
        GROUP BY producto
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def obtener_total_general():
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT COUNT(*) as cantidad, COALESCE(SUM(precio), 0) as total FROM ventas"
    ).fetchone()
    conn.close()
    return dict(fila)


def _resumen_desde(fecha_desde_iso):
    # Función interna (el guion bajo adelante es una convención de
    # Python para decir "esto es un detalle interno de este archivo, no
    # lo uses desde afuera") — las tres funciones de abajo la reusan,
    # cada una calculando un punto de partida distinto.
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT COUNT(*) as cantidad, COALESCE(SUM(precio), 0) as total FROM ventas WHERE fecha_hora >= ?",
        (fecha_desde_iso,)
    ).fetchone()
    conn.close()
    return dict(fila)


def obtener_total_hoy():
    # strftime da la fecha de hoy sin la hora (ej: "2026-08-30"), y le
    # agregamos "T00:00:00" para comparar contra el mismo formato que
    # usa fecha_hora en la tabla. Cualquier venta de hoy, sea a la
    # medianoche o a las 23:59, va a ser "mayor o igual" a ese punto de
    # arranque del día.
    inicio_de_hoy = datetime.now().strftime("%Y-%m-%dT00:00:00")
    return _resumen_desde(inicio_de_hoy)


def obtener_total_semana():
    hace_7_dias = (datetime.now() - timedelta(days=7)).isoformat()
    return _resumen_desde(hace_7_dias)


def obtener_total_mes():
    hace_30_dias = (datetime.now() - timedelta(days=30)).isoformat()
    return _resumen_desde(hace_30_dias)
