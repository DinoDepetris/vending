"""
Registro de "incidentes de pago" — casos donde cancelamos un pago por
tardar demasiado, pero existe la posibilidad real de que MercadoPago lo
haya terminado aprobando igual (por una demora en procesar la
cancelación, o porque el cliente ya tenía la tarjeta cargada en otra
pestaña). Sin este registro, esa plata quedaría cobrada sin que nadie
se entere de qué había que entregar a cambio.

Esta tabla no intenta resolver el problema sola — es un rastro para que
vos, como admin, puedas revisar manualmente en tu cuenta de MercadoPago
si alguno de estos terminó cobrado de verdad, y decidir qué hacer
(entregar el producto igual, reembolsar, etc.).
"""

import json
import sqlite3
from datetime import datetime

from config import DB_PATH


def obtener_conexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_tabla_incidentes():
    conn = obtener_conexion()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS incidentes_pago (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referencia TEXT NOT NULL,
            detalles_json TEXT NOT NULL,
            monto INTEGER NOT NULL,
            motivo TEXT NOT NULL,
            fecha_hora TEXT NOT NULL,
            revisado INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def registrar_incidente(referencia, detalles, motivo):
    conn = obtener_conexion()

    monto_total = sum(d["precio"] * d["cantidad"] for d in detalles)

    # json.dumps convierte la lista de productos (con sus cantidades y
    # slots) a un texto que SQLite sí puede guardar en una sola columna
    # — una base de datos como esta no tiene una forma nativa de
    # guardar "una lista de diccionarios" directamente.
    conn.execute("""
        INSERT INTO incidentes_pago (referencia, detalles_json, monto, motivo, fecha_hora)
        VALUES (?, ?, ?, ?, ?)
    """, (referencia, json.dumps(detalles), monto_total, motivo, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def obtener_incidentes():
    conn = obtener_conexion()
    filas = conn.execute(
        "SELECT * FROM incidentes_pago ORDER BY fecha_hora DESC"
    ).fetchall()
    conn.close()

    incidentes = []
    for fila in filas:
        incidente = dict(fila)
        # Deshacemos el json.dumps de arriba, para volver a tener la
        # lista de productos como datos usables en vez de texto plano.
        incidente["detalles"] = json.loads(incidente["detalles_json"])
        incidentes.append(incidente)

    return incidentes


def marcar_incidente_revisado(incidente_id):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE incidentes_pago SET revisado = 1 WHERE id = ?", (incidente_id,)
    )
    conn.commit()
    conn.close()
