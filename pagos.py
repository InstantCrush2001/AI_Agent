import os
import mercadopago
from datetime import datetime, timedelta

sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))

def crear_link_pago(titulo: str, precio: float, orden_id: str, fecha_cita=None, hora_cita=None) -> str:
    if orden_id.startswith("v_") and fecha_cita and hora_cita:
        # Visita — expira 2 horas antes de la cita
        if isinstance(hora_cita, str): #verifica si hora_cita es str
            hora_cita = datetime.strptime(hora_cita, "%H:%M").time()
        fecha_hora_cita = datetime.combine(fecha_cita, hora_cita)
        expiracion = fecha_hora_cita - timedelta(hours=2)
    else:
        expiracion = datetime.now() + timedelta(hours=24) # Servicio — expira en 24 horas después de mandar la cotización

    preference_data = {
        "items": [{
            "title": titulo,
            "quantity": 1,
            "unit_price": precio,
            "currency_id": "MXN"
        }],
        "notification_url": f"{os.environ.get('BASE_URL')}/webhook/mercadopago", # MercadoPago notificará a esta URL cuando el pago sea exitoso
        "external_reference": str(orden_id), # ID de tu pedido para identificarlo cuando llegue la notificación
        "expires": True,
        "expiration_date_from": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.000-06:00"),
        "expiration_date_to": expiracion.strftime("%Y-%m-%dT%H:%M:%S.000-06:00"),
        "date_of_expiration": expiracion.strftime("%Y-%m-%dT%H:%M:%S.000-06:00"),
    }
    result = sdk.preference().create(preference_data)
    print(f"DEBUG MP - resultado completo: {result}")
    preference = result["response"]
    return preference["init_point"] # init_point es el link de pago real //// sandbox_init_point es el link de prueba