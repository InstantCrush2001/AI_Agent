from fastapi import FastAPI, Form, Response, Request
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from database import SessionLocal, Historial, Producto, Pedido, crear_tablas
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
        f"- {p.nombre} | ${p.precio} MXN | Año: {p.año} | Piezas: {p.Pz_actuales}/{p.Pz_totales}"
        for p in productos
    )
    return f"""Eres el asistente virtual de Bionicle Saga MX, una tienda que conecta
a compradores con vendedores de Bionicle.

Tu trabajo es:
1. Ayudar a los clientes a encontrar productos del catálogo
2. Responder preguntas sobre precio, estética, año de lanzamiento y nombre de su colección
3. Indicar precios y disponibilidad
4. Guiar al cliente hacia hacer un pedido

CATÁLOGO ACTUAL:
{productos_texto}

Reglas importantes:
- Responde siempre en español, de forma amable y cálida
- Si un producto no tiene stock, dilo claramente y ofrece alternativas
- Si el cliente quiere comprar, pide su nombre y dirección de envío
- No inventes productos que no están en el catálogo
- No usar emojis
- No uses formato Markdown, asteriscos, ni negritas. Solo texto plano.
- Sé breve: máximo 3-4 oraciones por respuesta

- Cuando el cliente confirme que quiere comprar un producto específico 
y te haya dado su nombre y dirección, responde EXACTAMENTE en este formato 
y nada más:

COMPRA:nombre_del_producto|nombre_cliente|dirección_completa

Ejemplo:
COMPRA:Brutaka|Juan García|Calle Reforma 123, CDMX

- No agregues texto adicional cuando uses ese formato
- Solo usa ese formato cuando tengas los tres datos confirmados

"""

# ── MODELO DE DATOS ────────────────────────────────────────────────────
# Le dice a FastAPI qué forma tiene el JSON que va a recibir
class Mensaje(BaseModel):
    texto: str

# ── ENDPOINTS ──────────────────────────────────────────────────────────
@app.get("/")
def inicio():
    return {"status": "Bionicle Saga MX funcionando"}

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
            nombre_producto, nombre_cliente, direccion = datos.split("|")
            print(f"DEBUG - producto: '{nombre_producto}', cliente: '{nombre_cliente}', direccion: '{direccion}'")

            # Verificar producto en base de datos
            print(f"DEBUG - buscando producto: '{nombre_producto.strip()}'")
            producto = db.query(Producto).filter(
                Producto.nombre.ilike(f"%{nombre_producto.strip()}%")
            ).first()
            print(f"DEBUG - producto encontrado: {producto}")

            if producto: #and producto.stock > 0: # Crear pedido en PostgreSQL
                print(f"DEBUG - stock ok, creando pedido...")
                try:
                    pedido = Pedido(
                        numero=numero,
                        producto=producto.nombre,
                        precio=producto.precio,
                        nombre_cliente=nombre_cliente.strip(),
                        direccion=direccion.strip(),
                        estado="pendiente"
                    )
                    db.add(pedido)
                    db.commit()
                    print(f"DEBUG - pedido creado id: {pedido.id}")

                    link = crear_link_pago(producto.nombre, producto.precio, pedido.id) # Generar link de pago
                    print(f"DEBUG - link generado: {link}")

                    texto_respuesta = f"Perfecto {nombre_cliente.strip()}, aquí está tu link de pago por ${producto.precio} MXN: {link}"

                except Exception as e:
                    print(f"DEBUG - error interno: {e}")
                    texto_respuesta = "Hubo un problema al procesar tu pedido. Por favor intenta de nuevo."
        except Exception as e:
                    print(f"DEBUG - error interno: {e}")
                    # texto_respuesta = "Hubo un problema al procesar tu pedido. Por favor intenta de nuevo."

    db.close()
    twiml = MessagingResponse()
    twiml.message(texto_respuesta)
    return Response(content=str(twiml), media_type="application/xml")

@app.post("/webhook/mercadopago")
async def webhook_mercadopago(request: Request):
    data = await request.json()
    
    # MercadoPago manda diferentes tipos de notificaciones
    # solo nos interesan las de pagos aprobados
    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        
        # Consultamos el pago para obtener los detalles
        sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))
        payment = sdk.payment().get(payment_id)
        payment_info = payment["response"]
        
        if payment_info["status"] == "approved":
            pedido_id = payment_info["external_reference"]
            
            # Actualizamos el pedido en la base de datos
            db = SessionLocal()
            pedido = db.query(Pedido).filter_by(id=int(pedido_id)).first()
            if pedido:
                pedido.estado = "pagado"
                db.commit()
            db.close()
    
    return {"status": "ok"}