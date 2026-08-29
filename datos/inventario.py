"""
Todo el acceso a la base de datos vive en este archivo. Ninguna otra
parte del proyecto debería escribir SQL directamente — le piden los
datos a estas funciones, con nombres que ya explican qué hacen
(obtener_producto, descontar_stock), sin necesitar saber cómo están
guardados por dentro.

Esta es la misma lógica que ya tenías en servidor_vending.py — no
cambió ni una línea de SQL, solo cambió DÓNDE vive el código.
"""

import sqlite3

from config import DB_PATH


def obtener_conexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_base_de_datos():
    conn = obtener_conexion()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventario (
            producto TEXT PRIMARY KEY,
            slot INTEGER NOT NULL,
            precio INTEGER NOT NULL,
            stock INTEGER NOT NULL
        )
    """)

    cantidad = conn.execute("SELECT COUNT(*) FROM inventario").fetchone()[0]

    if cantidad == 0:
        productos_iniciales = [
            ("coca_500", 3, 800, 4),
            ("agua_500", 5, 600, 2),
            ("papas_150", 7, 1200, 3),
        ]
        conn.executemany(
            "INSERT INTO inventario (producto, slot, precio, stock) VALUES (?, ?, ?, ?)",
            productos_iniciales
        )
        conn.commit()

    conn.close()


def obtener_inventario_completo():
    conn = obtener_conexion()
    filas = conn.execute("SELECT * FROM inventario").fetchall()
    conn.close()
    return {fila["producto"]: dict(fila) for fila in filas}


def obtener_producto(producto):
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT * FROM inventario WHERE producto = ?", (producto,)
    ).fetchone()
    conn.close()
    return dict(fila) if fila else None


def descontar_stock(producto):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE inventario SET stock = stock - 1 WHERE producto = ?", (producto,)
    )
    conn.commit()
    conn.close()


def reponer_stock(producto, cantidad):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE inventario SET stock = stock + ? WHERE producto = ?",
        (cantidad, producto)
    )
    conn.commit()
    conn.close()
