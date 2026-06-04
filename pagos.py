import os
import mercadopago
from datetime import datetime, timedelta

sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))

def crear_link_pago(items: list, orden_id: str) -> str:
    preference_data = {
        "items": items,
        "notification_url": f"{os.environ.get('BASE_URL')}/webhook/mercadopago", # MercadoPago notificará a esta URL cuando el pago sea exitoso
        "external_reference": str(orden_id), # ID de tu pedido para identificarlo cuando llegue la notificación
        "expires": True,
        "expiration_date_from": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000-06:00"),
        "expiration_date_to": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000-06:00"),
        "date_of_expiration": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S.000-06:00"),
    }

    result = sdk.preference().create(preference_data)
    print(f"DEBUG MP - resultado completo: {result}")
    preference = result["response"]

    # init_point es el link de pago real //// sandbox_init_point es el link de prueba
    return preference["init_point"]