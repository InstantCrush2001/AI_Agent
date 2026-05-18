from fastapi import FastAPI, Form, Response, Request
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from database import SessionLocal, Historial, Producto, Pedido, DetallePedido, crear_tablas
import mercadopago
import os
from pagos import crear_link_pago

load_dotenv()

app = FastAPI()
crear_tablas()  # crea las tablas al arrancar el servidor
cliente = Anthropic()
historial = []

def construir_system_prompt():
    db = SessionLocal()
    productos = db.query(Producto).all()
    db.close()
    
    productos_texto = "\n".join(
        f"- {p.nombre} | clave del producto: {p.clave_prod}| ${p.precio} MXN, marca {p.marca}"
        for p in productos
    )
    return f"""Eres el asistente virtual de MEDICAL SUPPLIES MID, una tienda en línea
de suministros médicos.

Tu trabajo es:
1. Ayudar a los clientes a encontrar productos del catálogo
2. Responder preguntas sobre precio, cantidad y especificaciones
3. Indicar precios y disponibilidad
4. Guiar al cliente hacia hacer un pedido

CATÁLOGO ACTUAL:
{productos_texto}

Reglas importantes:
- Responde siempre en español, de forma amable y cálida
- Si un producto no tiene stock suficiente, dilo claramente y ofrece alternativas
- Siempre que menciones un producto, no menciones su clave_prod a menos que elc cliente la pida
- Si el cliente quiere comprar, pide su nombre y dirección de envío
- No inventes productos que no están en el catálogo
- Advierte que nuestro servicio es exclusivamente en la ciudad de Mérida y alrededores.
- No usar emojis
- No uses formato Markdown, asteriscos, ni negritas. Solo texto plano.
- Sé breve: máximo 3-4 oraciones por respuesta

- Cuando el cliente confirme que quiere comprar un producto específico 
y te haya dado su nombre y dirección, responde EXACTAMENTE en este formato 
y nada más:

COMPRA:nombre_cliente|dirección_completa|clave_prod1:cantidad1,clave_prod2:cantidad2,clave_prodN:cantidadN

Ejemplo:
COMPRA:Juan García|Calle Montejo, Mérida|HB112:5,PAR022:3,...

- Solo usa ese formato cuando tengas nombre, dirección y al menos un producto confirmado
- No uses valores None o vacíos

"""

# Le dice a FastAPI qué forma tiene el JSON que va a recibir
class Mensaje(BaseModel):
    texto: str

# ENDPOINTS 
@app.get("/")
def inicio():
    return {"status": "Medical Supplies MID funcionando"}

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

    if texto_respuesta.startswith("COMPRA:"): # Detectar la intención de compra
        print(f"DEBUG - texto_respuesta: '{texto_respuesta}'")
        try:
            _, datos = texto_respuesta.split("COMPRA:")
            print(f"DEBUG - datos: '{datos}'")
            partes = datos.split("|")
            nombre_cliente = partes[0].strip()
            direccion = partes[1].strip()
            claves_raw = partes[2].strip()
            print(f"DEBUG - cliente: '{nombre_cliente}', direccion: '{direccion}' productos: {claves_raw}")

            # Crear el pedido principal
            pedido = Pedido(
                numero=numero,
                nombre_cliente=nombre_cliente,
                direccion=direccion,
                estado="pendiente"
            )
            db.add(pedido)
            db.flush() 

            total = 0
            detalles_texto = []
            items_mp = []  # para MercadoPago

            # Procesar cada producto
            for item in claves_raw.split(","):
                claveProd, cantidad_str = item.strip().split(":")
                cantidad = int(cantidad_str.strip())

                producto = db.query(Producto).filter(
                    Producto.clave_prod == claveProd.strip().upper()
                ).first()

                if producto and producto.stock >= cantidad: 
                    print(f"DEBUG - stock ok, añadiendo {cantidad} {producto.nombre} a pedido...")
                    detalle = DetallePedido(
                            pedido_id=pedido.id,
                            producto=producto.nombre,
                            cantidad=cantidad,
                            precio_unitario=producto.precio
                        )
                    db.add(detalle)
                
                    precio = float(producto.precio)
                    subtotal = precio * cantidad
                    total += subtotal
                    detalles_texto.append(f"{cantidad}x {producto.nombre} ${subtotal:.2f} MXN")

                    items_mp.append({
                        "title": producto.nombre,
                        "quantity": cantidad,
                        "unit_price": precio,
                        "currency_id": "MXN"
                    })

                else:
                    print(f"DEBUG - no hay suficiente stock de {producto.nombre}...")
                    texto_respuesta = f"No contamos con la cantidad de {producto.nombre} suficiente."

            db.commit()
            print(f"DEBUG - pedido creado id: {pedido.id}")

            link = crear_link_pago(items_mp, pedido.id) # Generar link de pago
            print(f"DEBUG - link generado: {link}")

            resumen = "\n".join(detalles_texto)
            texto_respuesta = f"Pedido confirmado {nombre_cliente}:\n{resumen}\nTotal: ${total:.2f} MXN\nLink de pago: {link}"

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
            pedido = db.query(Pedido).filter_by(id=int(pedido_id)).first()
            if pedido:
                pedido.estado = "pagado"

                detalles = db.query(DetallePedido).filter(DetallePedido.pedido_id == pedido.id).all()
                for detalle in detalles:
                    prod = db.query(Producto).filter(Producto.nombre == detalle.producto).first()
                    if prod:
                        prod.stock -= detalle.cantidad

                db.commit()
                
                twilio_client = TwilioClient( # Manda mensaje de confirmación por WhatsApp
                    os.environ.get("TWILIO_ACCOUNT_SID"),
                    os.environ.get("TWILIO_AUTH_TOKEN")
                )
                # Construir resumen de productos
                detalles = db.query(DetallePedido).filter_by(pedido_id=pedido.id).all()
                resumen = ", ".join([f"{d.cantidad}x {d.producto}" for d in detalles])
                
                twilio_client.messages.create(
                    from_=os.environ.get("TWILIO_WA_NUMBER"),
                    to=pedido.numero,
                    body=f"Tu pago fue confirmado. Pedido: {resumen}. Su pedido llegará hoy antes de las 8 pm. Gracias {pedido.nombre_cliente}."
                )

            db.close()
    return {"status": "ok"}