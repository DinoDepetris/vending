"""
Todo el acceso a la tabla de categorías vive en este archivo. Una sola
tabla modela tanto categorías como subcategorías: cada fila puede tener
un "padre" (otra fila de esta misma tabla) o no tenerlo. Sin padre =
categoría raíz (ej: "Bebidas"). Con padre = subcategoría (ej:
"Gaseosas", cuyo padre es "Bebidas"). El mismo mecanismo sirve para
cualquier cantidad de niveles, no solo dos.
"""

import sqlite3

from config import DB_PATH


def obtener_conexion():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def inicializar_tabla_categorias():
    conn = obtener_conexion()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categorias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            categoria_padre_id INTEGER
        )
    """)
    conn.commit()
    conn.close()


def crear_categoria(nombre, categoria_padre_id=None):
    conn = obtener_conexion()
    conn.execute(
        "INSERT INTO categorias (nombre, categoria_padre_id) VALUES (?, ?)",
        (nombre, categoria_padre_id)
    )
    conn.commit()
    conn.close()


def obtener_categorias_ordenadas():
    # Esta función arma el orden "en árbol" que viste en el mockup del
    # desplegable (Bebidas, luego sus hijas Gaseosas y Aguas debajo,
    # después Snacks, luego sus hijas...) — no alcanza con pedirle a
    # SQL "ordename por nombre", porque eso mezclaría todo sin respetar
    # la jerarquía. Por eso lo armamos acá en Python, con una función
    # que se llama a sí misma (recursión) para bajar nivel por nivel.
    conn = obtener_conexion()
    filas = conn.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
    conn.close()
    categorias = [dict(fila) for fila in filas]

    # Agrupamos las categorías por su padre, para no tener que recorrer
    # la lista completa una y otra vez buscando "¿quién es hijo de
    # quién?" — lo dejamos precalculado en un diccionario.
    hijas_de = {}
    for categoria in categorias:
        padre_id = categoria["categoria_padre_id"]
        hijas_de.setdefault(padre_id, []).append(categoria)

    resultado = []

    def agregar_nivel(padre_id, nivel):
        # None como padre_id representa "las categorías raíz, sin
        # padre" — el punto de partida de la recursión.
        for categoria in hijas_de.get(padre_id, []):
            resultado.append({**categoria, "nivel": nivel})
            # Acá está la recursión: para cada categoría, buscamos sus
            # propias hijas, un nivel más profundo. Si "Gaseosas" a su
            # vez tuviera una subcategoría "Cola", aparecería acá,
            # anidada un nivel más — sin que hiciera falta escribir
            # código nuevo para ese tercer nivel.
            agregar_nivel(categoria["id"], nivel + 1)

    agregar_nivel(None, 0)
    return resultado


def obtener_categoria(categoria_id):
    conn = obtener_conexion()
    fila = conn.execute(
        "SELECT * FROM categorias WHERE id = ?", (categoria_id,)
    ).fetchone()
    conn.close()
    return dict(fila) if fila else None


def contar_subcategorias(categoria_id):
    conn = obtener_conexion()
    cantidad = conn.execute(
        "SELECT COUNT(*) FROM categorias WHERE categoria_padre_id = ?", (categoria_id,)
    ).fetchone()[0]
    conn.close()
    return cantidad


def eliminar_categoria(categoria_id):
    conn = obtener_conexion()

    # Cualquier producto que tuviera esta categoría asignada queda SIN
    # categoría (no se borra el producto en sí — solo pierde la
    # etiqueta). Es el mismo espíritu que vaciar_slot(): borrar una
    # organización no debería borrar los datos que organiza.
    conn.execute(
        "UPDATE inventario SET categoria_id = NULL WHERE categoria_id = ?", (categoria_id,)
    )
    conn.execute("DELETE FROM categorias WHERE id = ?", (categoria_id,))
    conn.commit()
    conn.close()


def renombrar_categoria(categoria_id, nuevo_nombre):
    conn = obtener_conexion()
    conn.execute(
        "UPDATE categorias SET nombre = ? WHERE id = ?", (nuevo_nombre, categoria_id)
    )
    conn.commit()
    conn.close()
