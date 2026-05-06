import os
import mercadopago

sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))

def crear_link_pago(producto_nombre: str, precio: int, pedido_id: int) -> str:
    preference_data = {
        "items": [
            {
                "title": producto_nombre,
                "quantity": 1,
                "unit_price": precio,
                "currency_id": "MXN",
            }
        ],
        # MercadoPago notificará a esta URL cuando el pago sea exitoso
        "notification_url": f"{os.environ.get('BASE_URL')}/webhook/mercadopago",
        # ID de tu pedido para identificarlo cuando llegue la notificación
        "external_reference": str(pedido_id),
        "back_urls": {
            "success": "https://chatbot-production-17d4.up.railway.app",
            "failure": "https://chatbot-production-17d4.up.railway.app",
        }
    }

    result = sdk.preference().create(preference_data)
    print(f"DEBUG MP - resultado completo: {result}")
    preference = result["response"]

    # init_point es el link de pago real
    # sandbox_init_point es el link de prueba
    return preference["init_point"]