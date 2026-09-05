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

from config import ARDUINO_HABILITADO, ARDUINO_PUERTO


class ArduinoSimulado:
    def accionar_motor(self, slot):
        # Este método representa SOLO la parte mecánica: girar el motor
        # o mover el solenoide que empuja el producto. Puede fallar por
        # causas eléctricas o mecánicas (falta de torque, engranaje
        # trabado) — nada que el software pueda arreglar, solo detectar.
        #
        # Reintentamos hasta 2 veces, como haría un controlador real
        # ante un motor que no giró del todo la primera vez.
        for _ in range(2):
            time.sleep(0.5)
            if random.random() < 0.92:
                return True
        return False

    def confirmar_entrega(self, slot):
        # Este método representa el sensor (infrarrojo, de peso, o un
        # microswitch) que confirma que el producto REALMENTE cayó —
        # separado del motor a propósito. Un motor puede girar
        # perfecto y aun así el producto quedar trabado a mitad de
        # camino (el clásico caso del paquete que queda "colgado").
        time.sleep(0.3)
        return random.random() < 0.97

    def abrir_compuerta(self, slot):
        # Esta sigue siendo la función que llama el resto del proyecto
        # (rutas/cliente.py no cambia nada) — por dentro, ahora
        # encadena los dos pasos reales: primero el motor, después el
        # sensor. Si el motor ni siquiera pudo accionar, ni tiene
        # sentido preguntarle al sensor.
        if not self.accionar_motor(slot):
            return False

        return self.confirmar_entrega(slot)


def autorizar_pago_en_servidor(monto):
    time.sleep(0.5)
    return random.random() < 0.85


# Según lo que diga config.ARDUINO_HABILITADO, "arduino" termina
# siendo o bien el simulador de siempre, o bien la clase que habla de
# verdad con el hardware por puerto serie (definida en
# arduino_real.py). El resto del proyecto (rutas/cliente.py) no
# necesita saber cuál de las dos es — solo llama a
# arduino.abrir_compuerta(slot) sin distinción.
if ARDUINO_HABILITADO:
    from arduino_real import ArduinoReal
    arduino = ArduinoReal(ARDUINO_PUERTO)
else:
    arduino = ArduinoSimulado()
