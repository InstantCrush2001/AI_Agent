from fastapi import FastAPI, Form, Response
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

app = FastAPI()
cliente = Anthropic()

# ── CATÁLOGO ───────────────────────────────────────────────────────────
catalogo = [
    {"nombre": "Toa Metru Vakama",  "precio": 350, "stock": 1, "piezas": "70/72"},
    {"nombre": "Brutaka",           "precio": 890, "stock": 1, "piezas": "103/120"},
    {"nombre": "Piraka Reidak",     "precio": 520, "stock": 1, "piezas": "40/40"},
    {"nombre": "Matoran Piruk",     "precio": 180, "stock": 1, "piezas": "100/104"},
]

# ── HISTORIAL ──────────────────────────────────────────────────────────
historial = []

# ── SYSTEM PROMPT ──────────────────────────────────────────────────────
def construir_system_prompt():
    productos_texto = "\n".join(
        f"- {p['nombre']} | ${p['precio']} MXN | Stock: {p['stock']} | Piezas: {p['piezas']}"
        for p in catalogo
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
async def whatsapp(Body: str = Form(...)):
    # Body es el mensaje que mandó el usuario por WhatsApp
    historial.append({"role": "user", "content": Body})

    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=construir_system_prompt(),
        messages=historial,
    )

    texto_respuesta = respuesta.content[0].text
    historial.append({"role": "assistant", "content": texto_respuesta})

    # Twilio espera la respuesta en formato TwiML, no JSON
    twiml = MessagingResponse()
    twiml.message(texto_respuesta)
    return Response(content=str(twiml), media_type="application/xml")