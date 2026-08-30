"""
Punto de entrada del proyecto. Este archivo debería poder leerse de
arriba a abajo en 10 segundos y entender "qué hay" en el proyecto, sin
tener que meterse en los detalles de cada parte — esa es la señal de
que separar responsabilidades funcionó.

Para correrlo: python app.py
Después abrí en el navegador: http://localhost:5000
"""

from flask import Flask

from config import SECRET_KEY
from datos.inventario import inicializar_base_de_datos
from datos.slots import inicializar_tabla_slots
from datos.ventas import inicializar_tabla_ventas
from datos.categorias import inicializar_tabla_categorias
from rutas.cliente import cliente_bp
from rutas.admin import admin_bp


def crear_app():
    # Empaquetar la creación de la app en una función es un patrón común
    # en Flask llamado "application factory". Para tu nivel actual no
    # hace falta profundizar en el porqué — alcanza con saber que existe
    # y usarlo así.
    app = Flask(__name__)
    app.secret_key = SECRET_KEY

    # register_blueprint conecta cada grupo de rutas (definido en otro
    # archivo) a esta aplicación principal. Es literalmente decirle a
    # Flask: "todas las rutas que armaste en cliente.py, sumalas acá",
    # y lo mismo para admin.py, esta vez agregándole el prefijo
    # "/admin" delante de cada una de sus rutas.
    app.register_blueprint(cliente_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app


app = crear_app()

if __name__ == "__main__":
    inicializar_base_de_datos()

    # Arrancamos con 5 slots físicos, y de entrada asignamos los tres
    # productos de ejemplo a los primeros tres (dejando el 4 y el 5
    # vacíos a propósito) — así, apenas corras esto, vas a ver en la
    # tienda solo 3 botones, no 5, confirmando que el filtro funciona.
    inicializar_tabla_slots(
        cantidad_inicial=5,
        productos_iniciales=["coca_500", "agua_500", "papas_150"]
    )

    inicializar_tabla_ventas()
    inicializar_tabla_categorias()
    app.run(debug=True, host="0.0.0.0", port=5000)
