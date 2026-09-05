"""
Acá vive la versión REAL del Arduino, la que reemplaza a
ArduinoSimulado (de simuladores.py) cuando ARDUINO_HABILITADO = True
en config.py.

Mantiene EXACTAMENTE la misma "forma" que ArduinoSimulado (los mismos
tres métodos: accionar_motor, confirmar_entrega, abrir_compuerta) a
propósito: así, rutas/cliente.py puede seguir llamando
arduino.abrir_compuerta(slot) sin enterarse de si del otro lado hay
un Arduino de verdad o un dado tirado al azar.
"""

import time
import serial  # pyserial - se instala con: pip install pyserial --break-system-packages


class ArduinoReal:
    def __init__(self, puerto, baudios=9600, timeout_segundos=10):
        # Guardamos estos datos por si en algún momento hay que
        # reconectar (ver _reconectar más abajo)
        self.puerto = puerto
        self.baudios = baudios
        self.timeout_segundos = timeout_segundos
        self.conexion = None

        self._conectar()

    def _conectar(self):
        # Separado en su propio método porque lo vamos a poder llamar
        # de nuevo más adelante si la conexión se corta en algún momento
        # (por ejemplo, si alguien desenchufa el cable USB sin querer).
        try:
            self.conexion = serial.Serial(self.puerto, self.baudios, timeout=self.timeout_segundos)

            # El Arduino se reinicia solo cada vez que se abre una
            # conexión serie nueva, y tarda un par de segundos en estar
            # listo para recibir comandos. Sin esta espera, el primer
            # comando que mandemos se podría perder.
            time.sleep(2)

            print(f"[ARDUINO] Conectado correctamente en {self.puerto}")
        except Exception as error:
            # Si el Arduino no está enchufado, o el puerto está mal
            # escrito, no queremos que esto tire abajo TODO el servidor
            # Flask al arrancar — mejor avisar por consola y que
            # abrir_compuerta() simplemente falle más adelante,
            # devolviendo False (como si el motor no hubiese
            # respondido), en vez de romper la aplicación entera.
            print(f"[ARDUINO] No se pudo conectar en {self.puerto}: {error}")
            self.conexion = None

    def accionar_motor(self, slot):
        # Representa el mismo paso que en ArduinoSimulado: la parte
        # mecánica (mover el carro y desbloquear la puerta). Acá, en
        # vez de tirar un dado, le mandamos el comando real por serie
        # y esperamos la respuesta "OK" que el sketch del Arduino
        # contesta cuando termina de llegar a la posición pedida.
        if self.conexion is None:
            print("[ARDUINO] No hay conexión activa, no se puede accionar el motor")
            return False

        try:
            # Vaciamos cualquier dato viejo que haya quedado esperando
            # en el buffer de entrada, para no leer por error una
            # respuesta de un comando anterior
            self.conexion.reset_input_buffer()

            # OJO: los slots en la base de datos empiezan en 1 (slot 1,
            # slot 2, ...), pero las puertas físicas en el Arduino están
            # numeradas empezando en 0 (puerta 0, puerta 1, ...). Por
            # eso restamos 1 acá — es el único lugar de todo el
            # proyecto donde hace falta este ajuste.
            numero_puerta = slot - 1
            comando = f"IR:{numero_puerta}\n"
            self.conexion.write(comando.encode("utf-8"))

            # El Arduino imprime varios mensajes de diagnóstico ANTES
            # de la respuesta final (ej: "Moviendo a puerta 0",
            # "Moviendo servo a DESBLOQUEO...", etc.) y recién al final
            # manda "OK" o "ERROR: ...". Si leyéramos una sola línea
            # con readline(), agarraríamos el primer mensaje de
            # diagnóstico y nunca el "OK" real — por eso leemos en
            # bucle, descartando las líneas que no sean la respuesta
            # final, hasta encontrarla (o hasta quedarnos sin líneas
            # nuevas, si el Arduino nunca contesta).
            respuesta = ""
            intentos_de_lectura = 0
            maximo_intentos_de_lectura = 15  # margen de sobra para todas las líneas intermedias

            while intentos_de_lectura < maximo_intentos_de_lectura:
                linea = self.conexion.readline().decode("utf-8").strip()
                intentos_de_lectura += 1

                if linea == "":
                    # readline() se quedó sin nada nuevo durante todo
                    # el timeout configurado: el Arduino dejó de
                    # mandar líneas, cortamos acá
                    break

                if linea == "OK" or linea.startswith("ERROR"):
                    respuesta = linea
                    break

                # Cualquier otra línea es un mensaje de diagnóstico
                # del Arduino (no es la respuesta final) — la
                # ignoramos y seguimos leyendo la siguiente
                print(f"[ARDUINO] (mensaje intermedio) {linea}")

            if respuesta == "OK":
                return True

            # Puede llegar "ERROR: numero de puerta invalido" (si el
            # slot no corresponde a ninguna puerta configurada en el
            # sketch) o simplemente nada, si el Arduino no contestó
            # a tiempo (se agota el timeout_segundos configurado arriba)
            print(f"[ARDUINO] Respuesta inesperada para slot {slot} (puerta {numero_puerta}): '{respuesta}'")
            return False

        except Exception as error:
            print(f"[ARDUINO] Error comunicando con el Arduino: {error}")
            return False

    def confirmar_entrega(self, slot):
        # TODO: cuando sumemos el pulsador que detecta que la puerta
        # quedó cerrada después de que el cliente la empujó, ACÁ es
        # donde va a ir esa verificación real (leyendo por serie si el
        # Arduino confirma "puerta cerrada" o algo similar).
        #
        # Por ahora, en esta primera etapa sin sensores puerta a
        # puerta, confiamos en que si el motor llegó bien a la
        # posición (accionar_motor devolvió True), el producto se
        # entregó correctamente.
        return True

    def abrir_compuerta(self, slot):
        # Misma lógica que en ArduinoSimulado: si el motor ni siquiera
        # pudo moverse, ni tiene sentido preguntar por la entrega.
        if not self.accionar_motor(slot):
            return False

        return self.confirmar_entrega(slot)
