import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()  # carga las variables del archivo .env

# ── CATÁLOGO ──────────────────────────────────────────────────────────
# Por ahora es un diccionario en Python.
# Más adelante esto vendrá de Airtable o Supabase.
catalogo = [
    {"nombre": "Toa Metru Vakama",  "precio": 350, "stock":  1, "piezas": "70/72"},
    {"nombre": "Brutaka",           "precio": 890, "stock":  1, "piezas": "103/120"},
    {"nombre": "Piraka Reidak",     "precio": 520, "stock":  1, "piezas": "40/40"},
    {"nombre": "Matoran Piruk",     "precio": 180, "stock":  1, "piezas": "100/104"  },
]

# ── SYSTEM PROMPT ─────────────────────────────────────────────────────
# Aquí le dices a la IA quién es y qué puede hacer.
# El catálogo se inserta dinámicamente para que siempre esté actualizado.
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
- Sé breve: máximo 3-4 oraciones por respuesta"""

# ── CLIENTE DE ANTHROPIC ──────────────────────────────────────────────
cliente = Anthropic()  # lee ANTHROPIC_API_KEY del .env automáticamente

# ── HISTORIAL DE CONVERSACIÓN ─────────────────────────────────────────
# Claude no recuerda conversaciones anteriores por sí solo.
# Tú le mandas todo el historial en cada llamada.
historial = []

def chat(mensaje_usuario: str) -> str:
    # 1. Agrega el mensaje del usuario al historial
    historial.append({"role": "user", "content": mensaje_usuario})

    # 2. Llama a la API con todo el historial + system prompt
    respuesta = cliente.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=construir_system_prompt(),  # instrucciones + catálogo
        messages=historial,               # toda la conversación
    )

    # 3. Extrae el texto de la respuesta
    texto_respuesta = respuesta.content[0].text

    # 4. Guarda la respuesta en el historial para la siguiente vuelta
    historial.append({"role": "assistant", "content": texto_respuesta})

    return texto_respuesta

# ── LOOP PRINCIPAL ────────────────────────────────────────────────────
# Esto simula el chat en tu terminal. Más adelante este loop
# lo reemplazas por un endpoint de FastAPI que recibe mensajes de WhatsApp.
if __name__ == "__main__":
    print("🤖 Chatbot de Bionicle Saga MX — escribe 'salir' para terminar\n")
    while True:
        entrada = input("Tú: ").strip()
        if entrada.lower() == "salir":
            break
        if not entrada:
            continue
        respuesta = chat(entrada)
        print(f"\n Bionicle Saga MX: {respuesta}\n")