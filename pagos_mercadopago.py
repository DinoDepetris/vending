"""
Integración con MercadoPago para cobrar de verdad (en modo de prueba
por ahora) en vez de simular el pago con random.random().

Usa el "Checkout Pro" de MercadoPago: le pedimos que arme una "orden de
cobro" (esto se llama "preferencia"), nos devuelve un link de pago, y
ese link lo convertimos en un código QR para que el cliente lo escanee
con el celular. Después, en vez de esperar a que MercadoPago nos avise
solo, le vamos PREGUNTANDO nosotros "¿ya pagaron?" cada pocos segundos
— la misma técnica de polling que ya usamos para el stock.
"""

import base64
import io
import uuid

import qrcode
import mercadopago

from config import MERCADOPAGO_ACCESS_TOKEN, MERCADOPAGO_HABILITADO


def crear_pago_con_qr(monto_total):
    # external_reference es un identificador ÚNICO que nosotros
    # inventamos para esta compra puntual — es lo que después vamos a
    # usar para preguntarle a MercadoPago "¿la compra CON ESTE número
    # ya se pagó?", en vez de confundirla con cualquier otra compra que
    # esté pasando al mismo tiempo en otra pestaña.
    referencia = str(uuid.uuid4())

    sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)

    datos_preferencia = {
        "items": [{
            "title": "Compra en vending",
            "quantity": 1,
            "unit_price": float(monto_total)
        }],
        "external_reference": referencia,

        # Excluimos los métodos de pago offline (Rapipago, Pago Fácil y
        # similares) — son formas de pago en efectivo, en OTRO lugar
        # físico, pensadas para compras online donde el cliente puede
        # esperar días. En un vending eso no tiene sentido: nadie va a
        # ir a pagar a un Rapipago y volver después a buscar el
        # producto. Con esto, MercadoPago solo ofrece tarjeta y saldo
        # de cuenta, que en la vida real resuelven casi siempre al
        # instante — reduce mucho la chance de quedar "pendiente".
        "payment_methods": {
            "excluded_payment_types": [
                {"id": "ticket"},
                {"id": "atm"}
            ]
        }
    }

    respuesta = sdk.preference().create(datos_preferencia)
    preferencia = respuesta["response"]

    # Este es el detalle que causaba el error "una de las partes es de
    # prueba": MercadoPago devuelve DOS links distintos en la misma
    # respuesta — init_point (para cuentas reales) y sandbox_init_point
    # (específico para probar con credenciales de prueba). Si mezclás
    # un token de prueba con el link de producción, MercadoPago detecta
    # la inconsistencia y rechaza todo el intento de pago.
    if MERCADOPAGO_ACCESS_TOKEN.startswith("TEST-"):
        link_de_pago = preferencia.get("sandbox_init_point", preferencia["init_point"])
    else:
        link_de_pago = preferencia["init_point"]

    imagen_qr = qrcode.make(link_de_pago)

    # Convertimos la imagen a un formato de texto (base64) que se puede
    # meter directo en un <img> de HTML sin necesitar guardar ningún
    # archivo en el disco — la imagen "vive" en la respuesta misma.
    buffer = io.BytesIO()
    imagen_qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return {
        "referencia": referencia,
        "link_de_pago": link_de_pago,
        "qr_base64": qr_base64
    }


def obtener_pagos_de_referencia(referencia):
    sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)

    # Le pedimos a MercadoPago: "buscame todos los pagos que tengan esta
    # referencia externa". Devolvemos la lista completa (no solo un
    # sí/no) porque ahora necesitamos más detalle: no solo si algo se
    # aprobó, sino también los "id" de los pagos que quedaron en
    # pendiente, para poder cancelarlos si tardan demasiado.
    resultado = sdk.payment().search({"external_reference": referencia})
    return resultado["response"]["results"]


def cancelar_pago(payment_id):
    # Cancelar un pago pendiente/en revisión le dice a MercadoPago
    # "este intento no va más" — libera esa transacción del lado de
    # ellos, para que el cliente pueda reintentar de cero en vez de
    # quedar con un pago fantasma que capaz se resuelve solo, horas
    # después, cuando el cliente ya se fue de la máquina.
    sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)
    sdk.payment().update(payment_id, {"status": "cancelled"})
