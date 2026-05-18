import os
import mercadopago

sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))

def crear_link_pago(items: list, pedido_id: int) -> str:
    preference_data = {
        "items": items,
        "notification_url": f"{os.environ.get('BASE_URL')}/webhook/mercadopago", # MercadoPago notificará a esta URL cuando el pago sea exitoso
        "external_reference": str(pedido_id), # ID de tu pedido para identificarlo cuando llegue la notificación
    }

    result = sdk.preference().create(preference_data)
    print(f"DEBUG MP - resultado completo: {result}")
    preference = result["response"]

    # init_point es el link de pago real //// sandbox_init_point es el link de prueba
    return preference["init_point"]