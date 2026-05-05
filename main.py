from fastapi import FastAPI, Form, Response
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from database import SessionLocal, Historial, Producto, crear_tablas

load_dotenv()

app = FastAPI()
crear_tablas()  # crea las tablas al arrancar el servidor
cliente = Anthropic()


# ── HISTORIAL ──────────────────────────────────────────────────────────
historial = []

# ── SYSTEM PROMPT ──────────────────────────────────────────────────────
def construir_system_prompt():
    db = SessionLocal()
    productos = db.query(Producto).all()
    db.close()
    
    productos_texto = "\n".join(
        f"- {p.nombre} | ${p.precio} MXN | Stock: {p.stock} | Año: {p.año} | Piezas: {p.Pz_actuales}/{p.Pz_totales}"
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
- Sé breve: máximo 3-4 oraciones por respuesta"""

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

    # Recupera el historial de este usuario desde la base de datos
    mensajes_db = db.query(Historial).filter(
        Historial.numero == numero
    ).order_by(Historial.fecha).all()

    # Convierte a formato que entiende Claude
    historial = [{"role": m.role, "content": m.contenido} for m in mensajes_db]

    # Agrega el mensaje nuevo
    historial.append({"role": "user", "content": Body})

    # Guarda el mensaje del usuario en la base de datos
    db.add(Historial(numero=numero, role="user", contenido=Body))
    db.commit()

    # Llama a Claude
    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=construir_system_prompt(),
        messages=historial[-10:],  # solo los últimos 10 mensajes
    )

    texto_respuesta = respuesta.content[0].text

    # Guarda la respuesta en la base de datos
    db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta))
    db.commit()
    db.close()

    twiml = MessagingResponse()
    twiml.message(texto_respuesta)
    return Response(content=str(twiml), media_type="application/xml")