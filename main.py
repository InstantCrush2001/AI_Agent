from fastapi import FastAPI, Form, Response, Request
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from database import SessionLocal, Historial, Visitas, crear_tablas
import mercadopago
import os
from pagos import crear_link_pago
from datetime import datetime
import json

load_dotenv()

app = FastAPI()
crear_tablas()  # crea las tablas al arrancar el servidor
cliente = Anthropic()
historial = []

SERVICIOS_TEXTO = """
- Plomería
- Instalaciones eléctricas
- Pintura
- Carpintería
- Herrería
- Jardinería
- Automatización
"""

def construir_system_prompt():
    db = SessionLocal()
    db.close()
    fecha_hoy = datetime.now().strftime("%d/%m/%Y")
    servicios_texto = SERVICIOS_TEXTO
    return f"""Eres el asistente virtual de OSORIO MANTENIMIENTO, un gestor de citas para realizar trabajos de mantenimiento.

Hoy es {fecha_hoy}

Tu trabajo es:
1. Atender al cliente y verificar si sus necesidades van de acuerdo a los servicios que ofrecemos
2. Siempre es posible atenderles en persona siempre y cuando la cita esté pagada
3. Agendar una cita para el cliente 

Tipo de servicios brindados:{servicios_texto}

Reglas importantes:
- Responde siempre en español, de forma amable y cálida
- También aclara que nuestro equipo habla inglés o francés
- No inventes servicios que no están en el catálogo.
- Advierte que la tarifa de visita dentro de la ciudad de Mérida es de $475 MXN.
- No usar emojis
- No uses formato Markdown, asteriscos, ni negritas. Solo texto plano.
- Sé breve: máximo 3-4 oraciones por respuesta
- Cuando el cliente confirme su intención de recibir la visita, preguntar los siguientes datos de contacto:
    - Nombre
    - Dirección de la visita

- Y proponer el 1° horario disponible del día siguiente
- Las visitas se agendan entre las 9am y 6pm de lunes a viernes y de 9pm a 2pm los sábados. Los domingos no laboramos
- Cuando recibas todos los datos de contacto, mandar link de pago para concretar la cita. Si no se paga, no se concreta la cita

- Cuando tengas nombre y dirección del cliente, responde EXACTAMENTE en este formato JSON y nada más:

CITA:{"nombre": "Juan García", "direccion": "Calle 60 123, Mérida"}

- No agregues texto antes ni después del formato CITA:
- Solo usa ese formato cuando tengas ambos datos confirmados
- No uses valores null o vacíos

"""

# Le dice a FastAPI qué forma tiene el JSON que va a recibir
class Mensaje(BaseModel):
    texto: str

# ENDPOINTS 
@app.get("/")
def inicio():
    return {"status": "OSARIO II activo"}

@app.post("/chat")
def chat(mensaje: Mensaje):
    historial.append({"role": "user", "content": mensaje.texto})

    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=construir_system_prompt(),
        messages=historial,
    )

    texto_respuesta = respuesta.content[0].text
    historial.append({"role": "assistant", "content": texto_respuesta})

    return {"respuesta": texto_respuesta}

@app.post("/whatsapp")
async def whatsapp(Body: str = Form(...), From: str = Form(...)):
    numero = From
    db = SessionLocal()

    mensajes_db = db.query(Historial).filter( # Recupera el historial de este usuario desde la base de datos
    Historial.numero == numero
    ).order_by(Historial.fecha).all()
    
    historial = [{"role": m.role, "content": m.contenido} for m in mensajes_db] # Convierte a formato que entiende Claude
    historial.append({"role": "user", "content": Body}) # Agrega el mensaje nuevo
    
    db.add(Historial(numero=numero, role="user", contenido=Body)) # Guarda el mensaje del usuario en la base de datos
    db.commit()
    
    respuesta = cliente.messages.create( # Llama a Claude
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=construir_system_prompt(),
        messages=historial[-10:],  # solo los últimos 10 mensajes
    )

    texto_respuesta = respuesta.content[0].text
    db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta)) # Guarda la respuesta en la base de datos
    db.commit()

    if texto_respuesta.startswith("CITA:"): # Detectar la intención de compra
        print(f"DEBUG - texto_respuesta: '{texto_respuesta}'")
        try:
            _, json_raw = texto_respuesta.split("CITA:")
            datos = json.loads(json_raw.strip())
            print(f"DEBUG - datos: '{datos}'")

            nombre_cliente = datos["nombre"].strip()
            direccion = datos["direccion"].strip()
            print(f"DEBUG - cliente: {nombre_cliente}, direccion: {direccion}")

            if not nombre_cliente or nombre_cliente.lower() == "none":
                texto_respuesta = "Entendido, si necesitas algo más con gusto te ayudo."
        
            else: # Crear cita
                cita = Visitas(
                    numero=numero,
                    nombre_cliente=nombre_cliente,
                    direccion=direccion,
                    descripcion = None,
                    fecha_visita = None,
                    hora_visita = None,
                    estado="pendiente"
                )
                db.add(cita)
                db.flush() 

                pago = [] 

                pago.append({
                    "title": "Visita de mantenimiento",
                    "quantity": 1,
                    "unit_price": 475,
                    "currency_id": "MXN"
                    })

                db.commit()
                print(f"DEBUG - cita creada con id: {cita.id}")

                link = crear_link_pago(pago, cita.id) # Generar link de pago
                print(f"DEBUG - link generado: {link}")

                texto_respuesta = f"Cita registrada {nombre_cliente}. El costo de la visita es $475 MXN. Aquí está tu link de pago para confirmar la cita: {link}"

        except Exception as e:
            print(f"DEBUG - error interno: {e}")
            texto_respuesta = "Hubo un problema al procesar tu pedido. Por favor intenta de nuevo."

    db.close()
    twiml = MessagingResponse()
    twiml.message(texto_respuesta)
    return Response(content=str(twiml), media_type="application/xml")

@app.post("/webhook/mercadopago")
async def webhook_mercadopago(request: Request):
    data = await request.json()
    
    # MercadoPago manda diferentes tipos de notificaciones, solo nos interesan las de pagos aprobados
    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        
        # Consultamos el pago para obtener los detalles
        sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))
        payment = sdk.payment().get(payment_id)
        payment_info = payment["response"]
        
        if payment_info["status"] == "approved":
            pedido_id = payment_info["external_reference"]
            
            db = SessionLocal() # Actualizamos el pedido en la base de datos
            visita = db.query(Visitas).filter_by(id=int(pedido_id)).first()
            if visita:
                visita.estado = "pagado"
                db.commit()
                
                twilio_client = TwilioClient( # Manda mensaje de confirmación por WhatsApp
                    os.environ.get("TWILIO_ACCOUNT_SID"),
                    os.environ.get("TWILIO_AUTH_TOKEN")
                )

                twilio_client.messages.create(
                    from_=os.environ.get("TWILIO_WA_NUMBER"),
                    to=visita.numero,
                    body=f"Tu pago fue confirmado. Su visita se agendó para el {visita.fecha_visita} a las {visita.hora_visita}. Gracias {visita.nombre_cliente}."
                )

            db.close()
    return {"status": "ok"}