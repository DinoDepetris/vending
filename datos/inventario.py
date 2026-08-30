"""
Todo el acceso al CATÁLOGO de productos vive en este archivo: qué
productos existen, su precio, su stock. Ya no incluye el slot físico
—eso ahora vive en datos/slots.py, separado a propósito— porque son dos
preguntas distintas: "¿qué es la Coca de 500ml y cuánto vale?" (esto) vs
"¿en qué compuerta física está puesta ahora mismo?" (slots).
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
            precio INTEGER NOT NULL,
            stock INTEGER NOT NULL
        )
    """)

    cantidad = conn.execute("SELECT COUNT(*) FROM inventario").fetchone()[0]

    if cantidad == 0:
        productos_iniciales = [
            ("coca_500", 800, 4),
            ("agua_500", 600, 2),
            ("papas_150", 1200, 3),
        ]
        conn.executemany(
            "INSERT INTO inventario (producto, precio, stock) VALUES (?, ?, ?)",
            productos_iniciales
        )
        conn.commit()

    # --- MIGRACIÓN: agregar la columna alerta_enviada si no existe ------
    # A diferencia de otros cambios de estructura que hicimos antes (que
    # te pedían borrar vending.db y arrancar de cero), esta vez usamos
    # una técnica distinta: intentamos agregar la columna nueva, y si ya
    # existe (porque ya corriste esta versión antes), SQLite tira un
    # error que simplemente ignoramos. Así, tu base de datos existente
    # se actualiza sola, sin perder nada de lo que ya tenías.
    try:
        conn.execute("ALTER TABLE inventario ADD COLUMN alerta_enviada INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        # "duplicate column name" — significa que esto ya se había
        # corrido antes en esta base de datos. No hay nada que hacer.
        pass

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


def crear_o_actualizar_producto(producto, precio, stock):
    conn = obtener_conexion()

    # Esto se llama "upsert" (update + insert): si el producto ya existe
    # (mismo nombre), actualiza su precio y stock; si no existe, lo crea.
    # ON CONFLICT detecta el choque contra la clave primaria (producto)
    # y decide qué hacer en ese caso, en una sola consulta.
    conn.execute("""
        INSERT INTO inventario (producto, precio, stock)
        VALUES (?, ?, ?)
        ON CONFLICT(producto) DO UPDATE SET precio = excluded.precio, stock = excluded.stock
    """, (producto, precio, stock))
    conn.commit()
    conn.close()


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

    # Al reponer, asumimos que el stock ya volvió a un nivel razonable
    # — reseteamos la marca de "alerta ya enviada", para que si vuelve a
    # bajar del umbral más adelante, te vuelva a avisar. Sin este
    # reset, una vez mandada la primera alerta nunca más te avisaría
    # de nada para ese producto.
    conn.execute(
        "UPDATE inventario SET alerta_enviada = 0 WHERE producto = ?", (producto,)
    )
    conn.commit()
    conn.close()


def marcar_alerta_enviada(producto):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE inventario SET alerta_enviada = 1 WHERE producto = ?", (producto,)
    )
    conn.commit()
    conn.close()


def retirar_stock(producto, cantidad):
    conn = obtener_conexion()

    # MAX(stock - ?, 0) calcula la resta y, si el resultado sería
    # negativo, se queda en 0 en su lugar. Esto evita que un retiro más
    # grande que el stock actual (por ejemplo, un typo: poner 500 en vez
    # de 5) deje un número negativo guardado, que no tendría sentido
    # para una cantidad de productos físicos.
    conn.execute(
        "UPDATE inventario SET stock = MAX(stock - ?, 0) WHERE producto = ?",
        (cantidad, producto)
    )
    conn.commit()
    conn.close()


def obtener_productos_en_venta():
    conn = obtener_conexion()

    # JOIN combina filas de dos tablas distintas que comparten un dato en
    # común — acá, el nombre del producto. Le pedimos: "traeme cada slot
    # que tenga un producto puesto, junto con el precio y stock de ESE
    # producto desde la tabla inventario". Si un slot está vacío
    # (producto NULL), simplemente no aparece en el resultado — es
    # justo el filtro que hace que la tienda no muestre nada sin asignar.
    filas = conn.execute("""
        SELECT inventario.producto, inventario.precio, inventario.stock, slots.id AS slot
        FROM slots
        JOIN inventario ON slots.producto = inventario.producto
        WHERE slots.producto IS NOT NULL
        ORDER BY slots.id
    """).fetchall()
    conn.close()
    return {fila["producto"]: dict(fila) for fila in filas}
