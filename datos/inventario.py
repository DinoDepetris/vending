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

    # Misma técnica para la columna de categoría: se agrega sola, sin
    # perder nada de lo que ya tenías guardado.
    try:
        conn.execute("ALTER TABLE inventario ADD COLUMN categoria_id INTEGER")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Misma técnica para la foto del producto: guardamos solo el NOMBRE
    # del archivo (por ejemplo "coca_500.jpg"), no la imagen en sí. El
    # archivo real vive en la carpeta static/productos/ — cuando tengas
    # las fotos, las copiás ahí directamente, sin tocar código ni base
    # de datos de nuevo.
    try:
        conn.execute("ALTER TABLE inventario ADD COLUMN imagen TEXT")
        conn.commit()
    except sqlite3.OperationalError:
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


def crear_o_actualizar_producto(producto, precio, stock, categoria_id=None, imagen=None):
    conn = obtener_conexion()

    conn.execute("""
        INSERT INTO inventario (producto, precio, stock, categoria_id, imagen)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(producto) DO UPDATE SET
            precio = excluded.precio,
            stock = excluded.stock,
            categoria_id = excluded.categoria_id,
            imagen = excluded.imagen
    """, (producto, precio, stock, categoria_id, imagen))
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
        SELECT inventario.producto, inventario.precio, inventario.stock,
               inventario.categoria_id, inventario.imagen, slots.id AS slot
        FROM slots
        JOIN inventario ON slots.producto = inventario.producto
        WHERE slots.producto IS NOT NULL
        ORDER BY slots.id
    """).fetchall()
    conn.close()
    return {fila["producto"]: dict(fila) for fila in filas}


def obtener_productos_en_venta_por_categorias(categoria_ids):
    # Variante de la función de arriba, pero filtrada a un conjunto de
    # categorías puntual. La usa la pantalla de "productos dentro de
    # una categoría" — categoria_ids ya viene calculado desde
    # datos/categorias.py incluyendo la categoría elegida MÁS todas sus
    # subcategorías, para que tocar "Bebidas" muestre también lo que
    # esté en "Gaseosas" o "Aguas" sin que el cliente tenga que navegar
    # un nivel más.
    if not categoria_ids:
        return {}

    conn = obtener_conexion()

    # "?, ?, ?" repetido tantas veces como categorías tengamos — SQLite
    # no permite pasar una lista directamente en un IN (...), hay que
    # armar la cantidad exacta de signos de pregunta de antemano.
    signos_de_pregunta = ",".join("?" for _ in categoria_ids)

    filas = conn.execute(f"""
        SELECT inventario.producto, inventario.precio, inventario.stock,
               inventario.categoria_id, inventario.imagen, slots.id AS slot
        FROM slots
        JOIN inventario ON slots.producto = inventario.producto
        WHERE slots.producto IS NOT NULL
          AND inventario.categoria_id IN ({signos_de_pregunta})
        ORDER BY slots.id
    """, list(categoria_ids)).fetchall()
    conn.close()
    return {fila["producto"]: dict(fila) for fila in filas}


def obtener_productos_en_venta_sin_categoria():
    # Los productos que están a la venta pero todavía no tienen
    # categoría asignada — por ejemplo, los que ya tenías cargados
    # antes de que existiera este sistema de categorías. Sin esta
    # función, esos productos se volverían invisibles de golpe al
    # pasar a navegación por categorías, sin que nadie se diera cuenta.
    conn = obtener_conexion()
    filas = conn.execute("""
        SELECT inventario.producto, inventario.precio, inventario.stock,
               inventario.categoria_id, inventario.imagen, slots.id AS slot
        FROM slots
        JOIN inventario ON slots.producto = inventario.producto
        WHERE slots.producto IS NOT NULL AND inventario.categoria_id IS NULL
        ORDER BY slots.id
    """).fetchall()
    conn.close()
    return {fila["producto"]: dict(fila) for fila in filas}
