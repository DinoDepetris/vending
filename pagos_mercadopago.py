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
        "external_reference": referencia
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


def verificar_pago_aprobado(referencia):
    sdk = mercadopago.SDK(MERCADOPAGO_ACCESS_TOKEN)

    # Le pedimos a MercadoPago: "buscame todos los pagos que tengan
    # esta referencia externa". Si el cliente ya pagó, va a aparecer
    # acá con status "approved".
    resultado = sdk.payment().search({"external_reference": referencia})
    pagos = resultado["response"]["results"]

    return any(pago["status"] == "approved" for pago in pagos)
