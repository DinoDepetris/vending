"""
Envío de alertas por email cuando el stock de un producto baja del
umbral definido en config.py. Usa smtplib, que viene incluido en
Python — no hace falta instalar ninguna librería nueva para esto.
"""

import smtplib
from email.mime.text import MIMEText

from config import (
    EMAIL_HABILITADO, EMAIL_REMITENTE, EMAIL_PASSWORD,
    EMAIL_DESTINATARIO, EMAIL_SMTP_HOST, EMAIL_SMTP_PORT
)


def enviar_alerta_stock_bajo(producto, stock_actual):
    if not EMAIL_HABILITADO:
        # Si todavía no configuraste config_secretos.py, no intentamos
        # mandar nada — dejamos el aviso en la consola nomás, para que
        # puedas seguir probando el resto del sistema sin que esto
        # rompa una venta por faltar credenciales.
        print(f"[ALERTA] Stock bajo de {producto}: quedan {stock_actual} unidades. "
              f"(Email deshabilitado — configurá config_secretos.py para activarlo)")
        return

    asunto = f"Alerta de stock bajo: {producto}"
    cuerpo = (
        f"El producto '{producto}' tiene solo {stock_actual} unidad(es) en stock.\n"
        f"Conviene reponerlo pronto."
    )

    # MIMEText arma el mensaje con el formato que espera el protocolo de
    # email (asunto, remitente, destinatario y cuerpo, todo en un solo
    # objeto listo para mandar).
    mensaje = MIMEText(cuerpo)
    mensaje["Subject"] = asunto
    mensaje["From"] = EMAIL_REMITENTE
    mensaje["To"] = EMAIL_DESTINATARIO

    try:
        with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT) as servidor:
            # starttls() cifra la conexión ANTES de mandar la
            # contraseña — sin esto, viajaría en texto plano por la red.
            servidor.starttls()
            servidor.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
            servidor.send_message(mensaje)
        print(f"[ALERTA] Email enviado por stock bajo de {producto}")
    except Exception as error:
        # Si el envío falla (credenciales mal puestas, sin internet, el
        # proveedor rechazó la conexión), NO queremos que se caiga toda
        # la venta por esto — el cliente ya pagó y ya retiró su
        # producto, ese proceso no puede depender de que un email salga
        # bien. Solo avisamos en la consola y seguimos.
        print(f"[ALERTA] No se pudo enviar el email de stock bajo: {error}")
