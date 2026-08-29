"""
Todo el acceso a la tabla de slots vive en este archivo. Un slot
representa un espacio físico real de la máquina (una compuerta, un
motor) — existe independientemente de si tiene un producto asignado o
no. Por eso vive separado de datos/inventario.py: inventario es el
CATÁLOGO de productos (qué existe, precio, stock), slots es el MAPA
FÍSICO de la máquina (qué compuertas hay, y qué producto tiene cada una
puesto, si tiene alguno).
"""

import sqlite3

from config import DB_PATH


def obtener_conexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_tabla_slots(cantidad_inicial=5, productos_iniciales=None):
    conn = obtener_conexion()

    # producto puede ser NULL — eso es justamente lo que representa un
    # slot vacío, sin nada asignado todavía. No hay ninguna fila especial
    # para "vacío", es simplemente ausencia de valor en esa columna.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS slots (
            id INTEGER PRIMARY KEY,
            producto TEXT
        )
    """)

    cantidad = conn.execute("SELECT COUNT(*) FROM slots").fetchone()[0]

    if cantidad == 0:
        productos_iniciales = productos_iniciales or []
        for numero in range(1, cantidad_inicial + 1):
            # Si hay productos de ejemplo para precargar, se los asignamos
            # a los primeros slots; el resto queda vacío (producto=None,
            # que SQLite guarda como NULL) — así arrancás viendo tanto
            # slots ocupados como vacíos desde el primer momento.
            indice = numero - 1
            producto = productos_iniciales[indice] if indice < len(productos_iniciales) else None
            conn.execute(
                "INSERT INTO slots (id, producto) VALUES (?, ?)",
                (numero, producto)
            )
        conn.commit()

    conn.close()


def obtener_todos_los_slots():
    conn = obtener_conexion()
    filas = conn.execute("SELECT * FROM slots ORDER BY id").fetchall()
    conn.close()
    return [dict(fila) for fila in filas]


def asignar_producto_a_slot(slot_id, producto):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE slots SET producto = ? WHERE id = ?", (producto, slot_id)
    )
    conn.commit()
    conn.close()


def vaciar_slot(slot_id):
    # Ojo: esto solo desasigna el producto de ESTE slot. El producto en
    # sí (su precio, su stock, su historial de ventas) sigue existiendo
    # en la tabla inventario — simplemente deja de estar a la venta
    # porque ningún slot físico lo tiene puesto.
    conn = obtener_conexion()
    conn.execute("UPDATE slots SET producto = NULL WHERE id = ?", (slot_id,))
    conn.commit()
    conn.close()


def agregar_slots_nuevos(cantidad):
    # Este es el ejercicio de "sumar 5 slots más": no toca ni una fila
    # existente, solo agrega filas nuevas, vacías, siguiendo la
    # numeración donde haya quedado. Ideal simulación de "instalé
    # compuertas nuevas en la máquina".
    conn = obtener_conexion()

    # COALESCE(MAX(id), 0): si la tabla estuviera vacía, MAX(id) daría
    # NULL — COALESCE lo reemplaza por 0 para que el rango de abajo
    # arranque en 1, no se rompa.
    maximo = conn.execute("SELECT COALESCE(MAX(id), 0) FROM slots").fetchone()[0]

    for numero in range(maximo + 1, maximo + 1 + cantidad):
        conn.execute("INSERT INTO slots (id, producto) VALUES (?, NULL)", (numero,))

    conn.commit()
    conn.close()


def obtener_slot_por_producto(producto):
    # La usa el momento de la venta: sabiendo qué producto se compró,
    # necesitamos encontrar QUÉ compuerta física abrir. Si el producto
    # no está asignado a ningún slot ahora mismo, devuelve None.
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT id FROM slots WHERE producto = ?", (producto,)
    ).fetchone()
    conn.close()
    return fila["id"] if fila else None
