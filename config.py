"""
Configuración centralizada del proyecto.

Juntar acá los valores que podrían cambiar según dónde corra el programa
(tu compu ahora, la Raspberry Pi después) o que son sensibles (claves,
contraseñas) hace que sea fácil encontrarlos y cambiarlos sin tener que
buscar entre todo el código para dar con ellos.
"""

# Flask necesita esta clave para firmar las cookies de sesión (así
# detecta si alguien intentó manipular una cookie a mano). En un
# proyecto real, esto NO se escribe así en el código — se lee de una
# variable de entorno o un archivo separado que nunca se sube a un
# repositorio público. Para aprender, esta versión simple alcanza.
SECRET_KEY = "clave-de-desarrollo-cambiar-en-produccion"

# Contraseña del panel de reposición. Mismo comentario que arriba: en el
# proyecto real esto se guardaría "hasheado" (una huella digital de la
# contraseña, no la contraseña en sí) en la base de datos, no en texto
# plano en el código.
CONTRASEÑA_ADMIN = "reponer123"

# Nombre del archivo donde vive la base de datos SQLite.
DB_PATH = "vending.db"
