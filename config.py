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

# Cuando el stock de un producto llega a este número o menos, se
# dispara la alerta de stock bajo.
UMBRAL_STOCK_BAJO = 2

# Si un pago con MercadoPago queda "pendiente" (ni aprobado ni
# rechazado) más de esta cantidad de segundos, lo cancelamos
# activamente en vez de dejar al cliente esperando indefinidamente.
UMBRAL_SEGUNDOS_PAGO_PENDIENTE = 60

# Las credenciales de email son datos sensibles de verdad — mucho más
# que la contraseña del panel de admin — así que viven en un archivo
# APARTE, config_secretos.py, que está en el .gitignore y nunca se sube
# a Git. Si ese archivo todavía no existe (por ejemplo, en una compu
# nueva donde no lo creaste todavía), el except de abajo deja las
# alertas por email simplemente desactivadas, sin romper nada del
# resto del sistema.
try:
    from config_secretos import (
        EMAIL_HABILITADO, EMAIL_REMITENTE, EMAIL_PASSWORD,
        EMAIL_DESTINATARIO, EMAIL_SMTP_HOST, EMAIL_SMTP_PORT
    )
except ImportError:
    EMAIL_HABILITADO = False
    EMAIL_REMITENTE = None
    EMAIL_PASSWORD = None
    EMAIL_DESTINATARIO = None
    EMAIL_SMTP_HOST = "smtp.gmail.com"
    EMAIL_SMTP_PORT = 587

# Mismo patrón para el Access Token de MercadoPago: nunca en este
# archivo, siempre en config_secretos.py (que está en el .gitignore).
try:
    from config_secretos import MERCADOPAGO_ACCESS_TOKEN
    MERCADOPAGO_HABILITADO = True
except ImportError:
    MERCADOPAGO_ACCESS_TOKEN = None
    MERCADOPAGO_HABILITADO = False
