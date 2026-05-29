from fastapi import FastAPI, Form, Response, Request
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client as TwilioClient
from database import SessionLocal, Historial, Visitas, Cotizacion, CitaServicio, crear_tablas
import mercadopago
import os
from pagos import crear_link_pago
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import json

load_dotenv()
app = FastAPI()
crear_tablas()  # crea las tablas al arrancar el servidor
cliente = Anthropic()
historial = []
MEXICO_TZ = ZoneInfo("America/Mexico_City")
ahora_mexico = datetime.now(MEXICO_TZ)

def construir_system_prompt():
    db = SessionLocal()
    # fecha_hoy = (ahora_mexico - timedelta(days=1)).strftime("%d/%m/%Y") 
    fecha_hoy = ahora_mexico.strftime("%d/%m/%Y") 

    # Obtener visitas y servicios del día siguiente
    mañana = (ahora_mexico + timedelta(days=1)).date()
    visitas_mañana = db.query(Visitas).filter(
        Visitas.fecha_visita == mañana,
        Visitas.estado != "cancelada"
    ).all()
    servicios_mañana = db.query(CitaServicio).filter(
        CitaServicio.fecha_servicio == mañana,
        CitaServicio.estado != "cancelada"
    ).all()
    db.close()

    # Construir texto de horarios ocupados del día siguiente:
    agenda_mañana = []
    for v in visitas_mañana:
        agenda_mañana.append({
            "tipo": "visita",
            "hora": v.hora_visita.strftime("%H:%M") if v.hora_visita else None,
            "id": v.id,
            "estado": v.estado,
        })
    for v in servicios_mañana:
        hora_inicio = v.hora_servicio
        duracion = v.tiempo_servicio or 2
        agenda_mañana.append({
            "tipo": "servicio",
            "hora": hora_inicio.strftime("%H:%M") if hora_inicio else None,
            "id": v.id,
            "estado": v.estado,
        })
        for i in range(1, duracion): # Agregar las horas bloqueadas por duración
            hora_bloqueada = (datetime.combine(mañana, hora_inicio) + timedelta(hours=i)).time()
            agenda_mañana.append({
                "tipo": "bloqueado",
                "hora": hora_bloqueada.strftime("%H:%M"),
                "id": v.id,
                "estado": "ocupado",
            })

    agenda_mañana = sorted(agenda_mañana, key=lambda x: x["hora"] or "99:99") # Ordenar por hora
    print(f"Buscando agenda para: {mañana}")
    print(f"Visitas: {len(visitas_mañana)} /// Servicios: {len(servicios_mañana)}")
    
    if mañana.weekday == 6: # Domingo
        horarios_disponibles = []
        disponibilidad_texto = "Mañana es domingo, no laboramos. Revisa la agenda del proximo lunes."
    # elif mañana.weekday() == 5: # Sábado
    #     horarios_disponibles = ["09:00", "11:00", "13:00"]
    else:
        horarios_disponibles = ["09:00", "11:00", "13:00", "16:00", "18:00"]
    
    if mañana.weekday() != 6: # Solo calcular disponibilidad si no es domingo
        horas_ocupadas = {item['hora'] for item in agenda_mañana}
        horarios_libres = [h for h in horarios_disponibles if h not in horas_ocupadas]

        if horarios_libres:
            disponibilidad_texto = f"Horarios disponibles mañana: {', '.join(horarios_libres)}"
        else:
            disponibilidad_texto = "La agenda de mañana está completamente llena. No hay horarios disponibles. Ofrece el siguiente día laboral"
    
    print(disponibilidad_texto)
    return f"""Eres el asistente virtual de OSORIO MANTENIMIENTO, un gestor de citas para realizar trabajos de mantenimiento.

Hoy es {fecha_hoy}
DISPONIBILIDAD DE MAÑANA ({mañana.strftime('%d/%m/%Y')}):
Los siguientes horarios NO están disponibles para agendar:
{disponibilidad_texto}

Tipo de servicios brindados principalmente: Plomería, Instalaciones eléctricas, Pintura, Carpintería, Herrería, Jardinería, Automatización

Tu trabajo es:
1. Siempre es posible atenderles en persona siempre y cuando la visita esté pagada, no importa que sea un servicio no enlistado
2. Agendar una cita para el cliente 

Reglas importantes:
- Responde siempre en español, de forma amable y cálida
- También aclara que nuestros técnicos hablan inglés y francés
- Advierte que la tarifa de visita dentro de la ciudad de Mérida es de $475 MXN y en caso de concretarse el servicio, se descuenta del total.
- Si el cliente pregunta por un servicio que no está enlistado, no advertirle que no se encuentra en la lista, simplemente decirle que 
  siempre y cuando se pague visita veremos como ayudarle.
- No uses formato Markdown, asteriscos, ni negritas, ni emojis. Solo texto plano.
- Sé breve: máximo 3-4 oraciones por respuesta
- Extraer la descripción del servicio que desee el cliente. Ejemplo:
    - necesito un sistema de riego
    - "descripción": "jardinería"
- Cuando el cliente confirme su intención de recibir la visita, preguntar los siguientes datos de contacto:
    - Nombre
    - Dirección de la visita
- Y proponer el 1° horario disponible del día siguiente.
- Sólo ofrece horarios que aparezcan en disponibilidad_texto. Si todos los horarios están ocupados decir que no hay diponibilidad ese día 
  y agenda para el día laboral más cercano
- La agenda del día es privada, no dar detalles. Sólo trabajar con el horario elegido.
- Si el cliente rechaza el horario propuesto o pide uno diferente, responde ÚNICAMENTE con la palabra: REAGENDAR
    - No agregues texto antes ni después

- Cuando tengas nombre, dirección, servicio, fecha y hora confirmados, 
  tu respuesta debe ser ÚNICAMENTE esto, sin ningún texto adicional antes ni después:

CITA:{{"nombre": "Juan García", "direccion": "Calle 60 123", "descripción": "jardinería", "fecha": "2026-05-20", "hora": "09:00"}}

- NUNCA agregues texto antes o después del formato CITA:
- NUNCA incluyas links ni explicaciones junto al formato CITA:
- Si el formato CITA: está en tu respuesta, no debe haber nada más
- No uses valores null o vacíos
"""

def buscar_horario_disponible(db, fecha_inicio):
# Buscar si hay espacio disponible para cita de servicio
    print("DEBUG - entró a buscar_horario")
    horarios_disponibles = ["09:00", "11:00", "13:00"] #, "16:00", "18:00"]
    dia_sig = fecha_inicio
    primer_horario = None
    fecha_disponible = None

    for _ in range(15):  # busca hasta 15 días adelante
    # Saltar domingos
        if dia_sig.weekday() == 6:
            dia_sig += timedelta(days=1)
            continue

        citas_día = db.query(CitaServicio).filter( #Añade todas las citas de servicio del día actual a la variable
                CitaServicio.fecha_servicio == dia_sig,
                CitaServicio.estado != "cancelada" #Menos si está cancelada
        ).all()

        if len(citas_día) >= 1: # Si hay más de una cita en día actual, cambia de día y empieza de nuevo
            dia_sig += timedelta(days=1)
            continue

        # Calcular horarios bloqueados considerando duración
        horarios_bloq = set()
        for cita in citas_día: #Por cada cita:
            hora_inicio = cita.hora_servicio.hour # Toma el primer elemento de la hora_servicio / 9:00 --> Toma "9"
            duracion = cita.tiempo_servicio or 2 # Carga la duración del trabajo si hay, sino considera 2 horas
            for i in range(duracion): # por cada hora de la duración:
                hora_bloq = hora_inicio + i # le suma el valor actual la hora de inicio. Se debe sumar cada hora individual dentro del rango de servicio
                if hora_bloq < 18: # si hora_bloqueada no excede las 18:00, añadir al set
                    horarios_bloq.add(f"{hora_bloq:02d}:00") 

        primer_horario = next( #Devuelve el 1° valor que encuentre disponible
            (h for h in horarios_disponibles if h not in horarios_bloq), # Itera sobre los horarios disponibles que no estén en horarios bloqueados
            None # si no, devuelve None
        )
        if primer_horario:
            fecha_disponible = dia_sig
            break  # encontró fecha disponible, sale del loop

        dia_sig += timedelta(days=1) # Si no encontró espacio en día actual, pasa al día siguiente
    return primer_horario, fecha_disponible

# Le dice a FastAPI qué forma tiene el JSON que va a recibir
class Mensaje(BaseModel):
    texto: str
class CotizacionInput(BaseModel):
    numero: str          #FORMATO --> whatsapp:+521234567890
    nombre_cliente: str
    descripcion: str
    precio: int
    tiempo_servicio: int
    visita_id: int

# ENDPOINT PARA CHAT EN WA
@app.post("/whatsapp")
async def whatsapp(Body: str = Form(...), From: str = Form(...)):
    numero = From
    db = SessionLocal()

#BLOQUE 1- INTERCEPTAR ACEPTO Y CONFIRMO SIN CLAUDE

    # ACEPTO
    if Body.strip().upper() == "ACEPTO":
        cotizacion = db.query(Cotizacion).filter( # Devuelve la 1° cotización filtrada con los sig parámetros:
            Cotizacion.numero == numero,
            Cotizacion.estado == "enviada"
        ).order_by(Cotizacion.fecha.desc()).first()

        if cotizacion: 
            cotizacion.estado = "aceptada" # Cambia estado de cotización
            dos_dias = (datetime.now(MEXICO_TZ) + timedelta(days=2)).date()
            primer_horario, fecha_disponible = buscar_horario_disponible(db=db, fecha_inicio=dos_dias) #Busca horario disponible dos días posteriores

            if primer_horario: # Si se acepta la cotización, se actualiza la DB y se envia mensaje para confirmar horario
                cotizacion.hora_propuesta = primer_horario
                cotizacion.fecha_propuesta = str(fecha_disponible)
                db.commit()
                texto_respuesta = f"Excelente {cotizacion.nombre_cliente}, su cotización ha sido aceptada. El primer horario disponible para realizar el trabajo es el {fecha_disponible.strftime('%d/%m/%Y')} a las {primer_horario}. Para confirmar responda CONFIRMO."
            else: # Si no se acepta el horario, se cierra la conexión a DB y se envía mensaje de error.
                texto_respuesta = f"Excelente {cotizacion.nombre_cliente}, su cotización ha sido aceptada. Por el momento no tenemos horarios disponibles en los próximos 15 días. Le contactaremos para agendar."

            db.add(Historial(numero=numero, role="user", contenido=Body))
            db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta))
            db.commit()
            db.close()

            twiml = MessagingResponse()
            twiml.message(texto_respuesta)
            return Response(content=str(twiml), media_type="application/xml")

        else: # Si no se encuentra Cotización, se cierra la conexión a DB y se envía mensaje de error.
            db.close()
            twiml = MessagingResponse()
            twiml.message("No encontramos una cotización pendiente. Si tiene alguna pregunta contáctenos al 9992717117")
            return Response(content=str(twiml), media_type="application/xml")
        
    # CONFIRMO
    if Body.strip().upper() == "CONFIRMO":
        cotizacion = db.query(Cotizacion).filter( #Devuelve la 1° cotización filtrada con los sig parámetros:
            Cotizacion.numero == numero,
            Cotizacion.estado == "aceptada"
        ).order_by(Cotizacion.fecha.desc()).first()

        if cotizacion: # Si hay cotización, se cargan las siguientes variables con los datos de la cotización
            primer_horario = cotizacion.hora_propuesta
            fecha_disponible = cotizacion.fecha_propuesta

            if primer_horario: # Si hay horario establecido, se extrae la dirección del ID de la visita correspondiente y el tiempo de servicio
                visita = db.query(Visitas).filter_by(id=cotizacion.visita_id).first() 
                direccion = visita.direccion if visita else ""
                tiempo_servicio = cotizacion.tiempo_servicio if cotizacion.tiempo_servicio else 2
                
                cita = CitaServicio( # Generar cita de servicio
                    numero=numero,
                    nombre_cliente=cotizacion.nombre_cliente,
                    direccion=direccion,
                    descripcion=cotizacion.descripcion,
                    precio=cotizacion.precio,
                    tiempo_servicio = tiempo_servicio,
                    fecha_servicio=str(fecha_disponible),
                    hora_servicio=primer_horario,
                    estado="pendiente",
                    cotizacion_id=cotizacion.id
                )
                db.add(cita)
                db.flush() # Añade los cambios de la cita de servicio a la base de datos sin hacer commit --> cambios temporales

                pago = [{ # Configuración del pago 
                    "title": cotizacion.descripcion,
                    "quantity": 1,
                    "unit_price": float(cotizacion.precio),
                    "currency_id": "MXN"
                }]
                print(f"DEBUG - cita servicio creada id: {cita.id}")

                # Llamar a función generadora de link de pago y enviar mensaje con ese contenido
                link = crear_link_pago(pago, f"s_{cita.id}") 
                texto_respuesta = f"Su cita ha sido agendada para mañana {fecha_disponible} a las {primer_horario}. Para confirmarla realice el pago de ${cotizacion.precio} MXN: {link}"

                db.add(Historial(numero=numero, role="user", contenido=Body))
                db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta))
                db.commit() # Añade los cambios definitivos de la cita de servicio a la DB y al Historial
                db.close() # Cierra la conexión con DB

                twiml = MessagingResponse()
                twiml.message(texto_respuesta)
                return Response(content=str(twiml), media_type="application/xml")

            else: # Si no se encuentran horarios, se cierra la conexión a DB y se envía mensaje de error.
                db.close()
                twiml = MessagingResponse()
                twiml.message("Lo sentimos, no hay horarios disponibles. Si tiene alguna pregunta contáctenos al 9992717117")
                return Response(content=str(twiml), media_type="application/xml")

        else: # Si no se encuentra Cotización, se cierra la conexión a DB y se envía mensaje de error.
            db.close()
            twiml = MessagingResponse()
            twiml.message("No encontramos una cotización aceptada pendiente de confirmar.")
            return Response(content=str(twiml), media_type="application/xml")
        
    if Body.strip().upper() == "REAGENDAR": # Detectar la intención de reagendar
        cotizacion = db.query(Cotizacion).filter( # Devuelve la 1° cotización filtrada con los sig parámetros:
            Cotizacion.numero == numero,
            Cotizacion.estado == "aceptada"
        ).order_by(Cotizacion.fecha.desc()).first()

        if cotizacion:
            fecha_actual = date.fromisoformat(cotizacion.fecha_propuesta)
            dia_siguiente = fecha_actual + timedelta(days=1)
            primer_horario, fecha_disponible = buscar_horario_disponible(db=db, fecha_inicio=dia_siguiente) 

            if primer_horario:
                cotizacion.hora_propuesta = primer_horario
                cotizacion.fecha_propuesta = str(fecha_disponible)
                texto_respuesta = f"Con gusto {cotizacion.nombre_cliente}. El siguiente horario disponible es el {fecha_disponible.strftime('%d/%m/%Y')} a las {primer_horario}. Para confirmar responda CONFIRMO."
            else:
                texto_respuesta = "Lo sentimos, no tenemos más horarios disponibles en los próximos 15 días. Le contactaremos para agendar."
        else:
            db.close()
            twiml = MessagingResponse()
            twiml.message("No encontramos una cotización activa. Si tiene alguna pregunta contáctenos al 9992717117")
            return Response(content=str(twiml), media_type="application/xml")
    
        db.add(Historial(numero=numero, role="user", contenido=Body))
        db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta))
        db.commit()
        db.close()

        twiml = MessagingResponse()
        twiml.message(texto_respuesta)
        return Response(content=str(twiml), media_type="application/xml")  
            
#BLOQUE 2 - LLAMAR A CLAUDE
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

#BLOQUE 3 - PROCESAR RESPUESTA DE CLAUDE
    if "CITA:" in texto_respuesta: # Detectar la intención de cita
        print(f"DEBUG 1 - texto_respuesta: '{texto_respuesta}'")
        try:
            _, json_raw = texto_respuesta.split("CITA:")
            datos = json.loads(json_raw.strip())
            print(f"DEBUG 2 - datos: '{datos}'")

            nombre_cliente = datos["nombre"].strip()
            direccion = datos["direccion"].strip()
            descripcion = datos["descripción"].strip()
            fecha_cita = datos["fecha"].strip()
            hora_cita = datos["hora"].strip()
            print(f"DEBUG 3 - cliente: {nombre_cliente}, direccion: {direccion}, desc: {descripcion}, a las {hora_cita} del {fecha_cita}")

            if not nombre_cliente or nombre_cliente.lower() == "none":
                texto_respuesta = "Entendido, si necesitas algo más con gusto te ayudo."
        
            else: # Crear cita
                cita = Visitas(
                    numero=numero,
                    nombre_cliente=nombre_cliente,
                    direccion=direccion,
                    descripcion = descripcion,
                    fecha_visita = fecha_cita,
                    hora_visita = hora_cita,
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
                print(f"DEBUG 4 - cita creada con id: {cita.id}")

                link = crear_link_pago(pago, f"v_{cita.id}") # Generar link de pago
                print(f"DEBUG 5 - link generado: {link}")

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
    orden_id = data.get("orden_id") #DEBUG sin pago

    """# MercadoPago manda diferentes tipos de notificaciones, solo nos interesan las de pagos aprobados
    if data.get("type") == "payment":
        payment_id = data["data"]["id"]
        
        # Consultamos el pago para obtener los detalles
        sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))
        payment = sdk.payment().get(payment_id)
        payment_info = payment["response"]
        
        if payment_info["status"] == "approved":
            pedido_id = payment_info["external_reference"]"""
            
    db = SessionLocal() # Actualizamos el pedido en la base de datos

    if str(orden_id).startswith("v_"):
        id_fil = int(str(orden_id).replace("v_",""))
        registro = db.query(Visitas).filter_by(id=id_fil).first()
        if registro:
            registro.estado = "pagado"
            db.commit()
            mensaje = f"Pago recibido. Su visita para diagnóstico ha sido confirmada para el {registro.fecha_visita} a las {registro.hora_visita}. Gracias {registro.nombre_cliente}."
            numero = registro.numero
    
    elif str(orden_id).startswith("s_"):
        id_fil = int(str(orden_id).replace("s_",""))
        registro = db.query(CitaServicio).filter_by(id=id_fil).first()
        if registro:
            registro.estado = "pagado"
            db.commit()
            mensaje = f"Pago recibido. Su cita de servicio ha sido confirmada para el {registro.fecha_servicio} a las {registro.hora_servicio}. Gracias {registro.nombre_cliente}."
            numero = registro.numero
    
    else:
        db.close()
        return {"status": "ok"}

    if registro:          
        twilio_client = TwilioClient( # Manda mensaje de confirmación por WhatsApp
                    os.environ.get("TWILIO_ACCOUNT_SID"),
                    os.environ.get("TWILIO_AUTH_TOKEN")
                )
        twilio_client.messages.create(
                    from_=os.environ.get("TWILIO_WA_NUMBER"),
                    to=numero,
                    body=mensaje
                )

    db.close()
    return {"status": "ok"}

@app.post("/cotizaciones")
async def crear_cotizacion(data: CotizacionInput):
    db = SessionLocal()

    cotizacion = Cotizacion(
        numero=data.numero,
        nombre_cliente=data.nombre_cliente,
        descripcion=data.descripcion,
        precio=data.precio,
        tiempo_servicio = data.tiempo_servicio,
        visita_id = data.visita_id
    )
    db.add(cotizacion)
    db.commit()
    cotizacion_id = cotizacion.id 

    twilio_client = TwilioClient(
        os.environ.get("TWILIO_ACCOUNT_SID"),
        os.environ.get("TWILIO_AUTH_TOKEN")
    )

    twilio_client.messages.create(
        from_=os.environ.get("TWILIO_WA_NUMBER"),
        to=data.numero,
        body=f"Hola {data.nombre_cliente}, le compartimos la cotización para el trabajo solicitado:\n\n{data.descripcion}\n\nPrecio estimado: ${data.precio} MXN\n\nPara aceptar y agendar su visita responda ACEPTO. Para cualquier duda estamos a sus órdenes."
    )

    db.close()
    return {"status": "cotizacion enviada", "id": cotizacion_id}