"""
Plantilla de credenciales de email para las alertas de stock bajo.

Este archivo SÍ se sube a Git — es solo un ejemplo, sin ninguna
contraseña real. Para usarlo de verdad:

1. Copiá este archivo y renombrá la copia a config_secretos.py
   (sin el ".example").
2. Completá tus datos reales ahí adentro.
3. config_secretos.py está en el .gitignore a propósito — nunca se va
   a subir a tu repositorio, porque ese sí va a tener una contraseña
   real.

Para Gmail: necesitás generar una "contraseña de aplicación" en
myaccount.google.com/apppasswords (requiere tener activada la
verificación en dos pasos). NO uses tu contraseña normal de Gmail acá.
"""

EMAIL_HABILITADO = True
EMAIL_REMITENTE = "tu_correo@gmail.com"
EMAIL_PASSWORD = "la contraseña de aplicación de 16 caracteres, no tu contraseña normal"
EMAIL_DESTINATARIO = "adonde_quieras_que_lleguen_las_alertas@gmail.com"
EMAIL_SMTP_HOST = "smtp.gmail.com"
EMAIL_SMTP_PORT = 587
