"""
Acá viven los "actores falsos": el Arduino y el servidor de pagos
externo, simulados con código que se comporta parecido a como lo harían
de verdad.

Agruparlos en su propio archivo, separado de las rutas y de la base de
datos, deja bien marcado: "esto es exactamente lo que hay que reemplazar
el día que conectemos hardware y proveedores de pago reales" — todo lo
demás del proyecto (rutas, plantillas, base de datos) no tiene que
cambiar ni una línea ese día.
"""

import time
import random


class ArduinoSimulado:
    def abrir_compuerta(self, slot):
        time.sleep(1)
        return random.random() < 0.9


def autorizar_pago_en_servidor(monto):
    time.sleep(0.5)
    return random.random() < 0.85


# Una sola instancia del Arduino simulado, compartida por todo el
# proyecto — la importan las rutas que la necesiten, en vez de crear una
# nueva cada vez.
arduino = ArduinoSimulado()
