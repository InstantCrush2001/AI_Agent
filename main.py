from fastapi import FastAPI, Response, Request
from pydantic import BaseModel
from anthropic import Anthropic
from dotenv import load_dotenv
from database import SessionLocal, Historial, Visitas, Cotizacion, CitaServicio, HorarioBloqueado, RateLimiter, SesionCita, crear_tablas
import mercadopago
import os
from pagos import crear_link_pago
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
import json
import httpx

load_dotenv()
app = FastAPI()
crear_tablas()  # crea las tablas al arrancar el servidor
cliente = Anthropic()
MEXICO_TZ = ZoneInfo("America/Mexico_City")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
MAX_MENSAJES = 30       # máximo de mensajes
VENTANA_MINUTOS = 60    # en una hora
numero_admin = os.environ.get("ADMIN_NUMERO", "").replace("whatsapp:+521", "")

dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

def construir_system_prompt(datos_capturados: str = ""):
    db = SessionLocal()
    ahora_mexico = datetime.now(MEXICO_TZ)# + timedelta(days=3)
    fecha_hoy = ahora_mexico.strftime("%d/%m/%Y") 
    agenda_hoy_texto = agenda_hoy(db=db, hoy= fecha_hoy)
    mañana = (ahora_mexico + timedelta(days=1)).date() # Obtener 1° horario disponible a partir del día siguiente
    horario_visita, fecha_visita = buscar_horario_disponible(db=db, fecha_inicio=mañana, isServ=False)
    
    if horario_visita:
        if fecha_visita == mañana:
            fecha_str = f"mañana {dias[fecha_visita.weekday()]} {fecha_visita.day} de {meses[fecha_visita.month - 1]}"
        else:
            fecha_str = f"el {dias[fecha_visita.weekday()]} {fecha_visita.day} de {meses[fecha_visita.month - 1]}"
        disponibilidad_visita = f"El próximo horario disponible para una visita de diagnóstico es {fecha_str} a las {horario_visita}."
    else:
        disponibilidad_visita = "No hay horarios disponibles para visitas en los próximos 15 días."
    db.close() 
    print(f" DEBUG - {disponibilidad_visita}")

    return f"""Eres el asistente virtual de OSORIO MANTENIMIENTO, un gestor de citas para realizar trabajos de mantenimiento.

Hoy es {fecha_hoy}
AGENDA DE HOY: {agenda_hoy_texto}
1° horario disponible para agendar visitas: {disponibilidad_visita}
    - Cuando el cliente quiera agendar una visita, ofrece los horarios indicados en la agenda de hoy.
    - No inventes horarios que no estén en la disponibilidad.

Tipo de servicios brindados principalmente: Plomería, Instalaciones eléctricas, Pintura, Carpintería, Herrería, Jardinería, Automatización

Reglas importantes:
- El nombre de la empresa "OSORIO MANTENIMIENTO" siempre desplegarlo en mayúsculas.
- Responde siempre en español, de forma amable y cálida.
- También aclara que nuestros técnicos hablan inglés y francés.
- Siempre es posible atenderles en persona siempre y cuando la visita esté pagada, no importa que sea un servicio no enlistado.
- Advierte que la tarifa de visita dentro de la ciudad de Mérida es de $475 MXN y en caso de concretarse el servicio, se descuenta del total.
- Si el cliente confirma una dirección fuera de Mérida, infórmale que contacte al {numero_admin} para agendar la cita.
- Si el cliente pregunta por un servicio que no está enlistado, no advertirle que no se encuentra en la lista, simplemente decirle que 
  siempre y cuando se pague visita veremos como ayudarle.
- No uses formato Markdown, asteriscos, ni negritas, ni emojis. Solo texto plano.
- Sé breve: máximo 3-4 oraciones por respuesta.
- Proponer los horarios disponible del día siguiente.
- Sólo ofrece horarios que aparezcan en disponibilidad_visita. Si todos los horarios están ocupados decir que no hay diponibilidad ese día 
  y agenda para el día laboral más cercano.
- De lunes a viernes trabajamos con los siguientes horarios: 9am - 11am - 1pm - 4pm
- Los sábados trabajamos con los siguientes horarios: 9am - 11am - 1pm
- Los domingos no laboramos
- La agenda del día es privada, no dar detalles.
- Si el cliente tiene alguna duda de los servicios o solicita un número telefónico al cual llamar, decirle que puede llamar al {numero_admin}.
- Si se detecta la intención de reagendar un servicio o visita, recordarle al cliente escribir REAGENDAR para proceder.

DATOS CAPTURADOS DEL CLIENTE:
{datos_capturados if datos_capturados else "Ninguno aún"}

- Extraer la descripción del servicio que desee el cliente. Ejemplo:
    - Cliente dice: necesito un sistema de riego
    - tu deber es insertar "jardinería" en el campo "descripcion" 
- Cuando el cliente confirme su intención de recibir la visita, preguntar los siguientes datos de contacto:
    - Nombre
    - Dirección de la visita
- Cuando el cliente proporcione nombre y dirección, responde ÚNICAMENTE:
    DATOS:{{"nombre": "Juan García", "direccion": "calle 60 123", "descripcion": "jardinería", "fecha": "2026-05-20", "hora": "09:00"}}
- No pidas datos que ya aparecen en DATOS CAPTURADOS
- Si el cliente proporciona explícitamente una ciudad diferente de Mérida, NO respondas con el formato "DATOS:", en cambio
  infórmale que contacte al {numero_admin} para agendar la cita

CUANDO TENGAS TODOS LOS DATOS (nombre, dirección, descripción, fecha, hora):
- Si el cliente confirma los datos con "sí", "continuar", "correcto" o similar, responde ÚNICAMENTE: CITA
- No vuelvas a generar DATOS: si ya están todos capturados
"""

def agenda_hoy(db, hoy):
    servicios_hoy = db.query(CitaServicio).filter( #Añade todas las citas de servicio del día actual a la variable
        CitaServicio.fecha_servicio == hoy,
        CitaServicio.estado != "cancelada" 
        ).all()
    visitas_hoy = db.query(Visitas).filter(
        Visitas.fecha_visita == hoy,
        Visitas.estado != "cancelada"
        ).all()
    bloqueados_hoy = db.query(HorarioBloqueado).filter(
        HorarioBloqueado.fecha == hoy
        ).all()
    
    agenda_hoy = []
    for v in visitas_hoy:
        if v.hora_visita:
            agenda_hoy.append(f"{v.hora_visita.strftime('%H:%M')} - visita ({v.nombre_cliente})")
    for s in servicios_hoy:
        if s.hora_servicio:
            agenda_hoy.append(f"{s.hora_servicio.strftime('%H:%M')} - servicio ({s.nombre_cliente})")
    for b in bloqueados_hoy:
        agenda_hoy.append(f"{b.hora} - bloqueado")

    agenda_hoy = sorted(agenda_hoy)

    if agenda_hoy:
        agenda_hoy_texto = "\n".join(agenda_hoy)
    else:
        agenda_hoy_texto = "Sin eventos hoy"
    
    return agenda_hoy_texto

def buscar_horario_disponible(db, fecha_inicio, isServ = True):
# Buscar si hay espacio disponible para cita de servicio
    dia_actual = fecha_inicio
    primer_horario = None
    fecha_disponible = None

    for _ in range(15):  # busca hasta 15 días adelante
    # Saltar domingos
        if dia_actual.weekday() == 6:
            dia_actual += timedelta(days=1)
            continue
        if dia_actual.weekday() == 5 or isServ == True:# Sábado o servicio
            horarios_disponibles = ["09:00", "11:00", "13:00"]
        else: # Lunes a viernes
            horarios_disponibles = ["09:00", "11:00", "13:00", "16:00"]

        servicios_dia = db.query(CitaServicio).filter( #Añade todas las citas de servicio del día actual a la variable
        CitaServicio.fecha_servicio == dia_actual,
        CitaServicio.estado != "cancelada" #Menos si está cancelada
        ).all()
        visitas_dia = db.query(Visitas).filter(
        Visitas.fecha_visita == dia_actual,
        Visitas.estado != "cancelada"
        ).all()
        bloqueados_dia = db.query(HorarioBloqueado).filter(
        HorarioBloqueado.fecha == dia_actual
        ).all()

        if isServ and len(servicios_dia) >= 1: # Si hay más de una cita en día actual, cambia de día y empieza de nuevo
                dia_actual += timedelta(days=1)
                continue

        # Calcular horarios bloqueados considerando duración
        horarios_bloq = set()

        # Bloquear por servicios existentes
        for cita in servicios_dia: #Por cada cita:
            hora_inicio = cita.hora_servicio.hour # Toma el primer elemento de la hora_servicio / 9:00 --> Toma "9"
            duracion = cita.tiempo_servicio or 2 # Carga la duración del trabajo si hay, sino considera 2 horas
            for i in range(duracion): # por cada hora de la duración:
                hora_bloq = hora_inicio + i # le suma el valor actual la hora de inicio. Se debe sumar cada hora individual dentro del rango de servicio
                if hora_bloq < 18: # si hora_bloqueada no excede las 18:00, añadir al set
                    horarios_bloq.add(f"{hora_bloq:02d}:00") 

        for visita in visitas_dia: # Bloquear por visitas existentes
            if visita.hora_visita:
                horarios_bloq.add(visita.hora_visita.strftime("%H:%M"))
        
        for b in bloqueados_dia: # Agregar horarios bloqueados manualmente
            horarios_bloq.add(b.hora)

        primer_horario = next( #Devuelve el 1° valor que encuentre disponible
            (h for h in horarios_disponibles if h not in horarios_bloq), # Itera sobre los horarios disponibles que no estén en horarios bloqueados
            None # si no, devuelve None
        )
        if primer_horario:
            fecha_disponible = dia_actual
            break  # encontró fecha disponible, sale del loop

        dia_actual += timedelta(days=1) # Si no encontró espacio en día actual, pasa al día siguiente
        print(f"Buscando agenda para: {dia_actual}")
        print(f"Visitas: {len(visitas_dia)} /// Servicios: {len(servicios_dia)}")
    return primer_horario, fecha_disponible

def verificar_limite(db, numero: str) -> bool: # "-> bool" indica que la función devuelve bool
    ahora_mexico = datetime.now(MEXICO_TZ)# + timedelta(days=3)
    registro = db.query(RateLimiter).filter_by(numero=numero).first()

    if not registro:
        db.add(RateLimiter(numero=numero, cantidad=1, ventana_inicio=ahora_mexico))
        db.commit()
        return True  # permitir

    # Verificar si la ventana expiró
    tiempo_transcurrido = (ahora_mexico - registro.ventana_inicio.replace(tzinfo=MEXICO_TZ)).total_seconds() / 60

    if tiempo_transcurrido > VENTANA_MINUTOS:
        # Reiniciar ventana
        registro.cantidad = 1
        registro.ventana_inicio = ahora_mexico
        db.commit()
        return True  # permitir

    if registro.cantidad >= MAX_MENSAJES:
        return False  # bloquear

    registro.cantidad += 1
    db.commit()
    return True  # permitir

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

async def procesar_mensaje(numero: str, Body: str, db) -> str:
    if not DEBUG:
        if not verificar_limite(db, numero):
            return "Has excedido el límite de mensajes. Por favor intenta de nuevo en una hora."
    ahora_mexico = datetime.now(MEXICO_TZ)# + timedelta(days=3)
#BLOQUE 1- INTERCEPTAR COMANDOS SIN CLAUDE
    # ACEPTO
    if Body.strip().upper() == "ACEPTO":
        cotizacion = db.query(Cotizacion).filter( # Devuelve la 1° cotización filtrada con los sig parámetros:
            Cotizacion.numero == numero,
            Cotizacion.estado == "enviada"
        ).order_by(Cotizacion.fecha.desc()).first()

        if cotizacion: 
            cotizacion.estado = "aceptada" # Cambia estado de cotización
            dos_dias = (ahora_mexico + timedelta(days=2)).date()
            primer_horario, fecha_disponible = buscar_horario_disponible(db=db, fecha_inicio=dos_dias) #Busca horario disponible dos días posteriores

            if primer_horario: # Si se acepta la cotización, se actualiza la DB y se envia mensaje para confirmar horario
                cotizacion.hora_propuesta = primer_horario
                cotizacion.fecha_propuesta = str(fecha_disponible)
                db.commit()
                texto_respuesta = f"Excelente {cotizacion.nombre_cliente}, su cotización ha sido aceptada. El primer horario disponible para realizar el trabajo es el {fecha_disponible.strftime('%d/%m/%Y')} a las {primer_horario}. Para confirmar responda CONFIRMO. Para sugerirle otro horario responda REAGENDAR"
            else: # Si no se acepta el horario, se cierra la conexión a DB y se envía mensaje de error.
                texto_respuesta = f"Excelente {cotizacion.nombre_cliente}, su cotización ha sido aceptada. Por el momento no tenemos horarios disponibles en los próximos 15 días. Le contactaremos para agendar."
        
            db.add(Historial(numero=numero, role="user", contenido=Body, fecha = ahora_mexico))
            db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta, fecha = ahora_mexico))
            db.commit()
            return texto_respuesta
    
    # CONFIRMO
    if Body.strip().upper() == "CONFIRMO":
        cotizacion = db.query(Cotizacion).filter( #Devuelve la 1° cotización filtrada con los sig parámetros:
            Cotizacion.numero == numero,
            Cotizacion.estado == "aceptada"
        ).order_by(Cotizacion.fecha.desc()).first()

        if cotizacion: # Si hay cotización, se cargan las siguientes variables con los datos de la cotización
            cotizacion.estado = "confirmada"
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
                    estado="pago pendiente",
                    cotizacion_id=cotizacion.id
                )
                db.add(cita)
                db.flush() # Añade los cambios de la cita de servicio a la base de datos sin hacer commit --> cambios temporales
                print(f"DEBUG - cita servicio creada id: {cita.id}")

                # Llamar a función generadora de link de pago y enviar mensaje con ese contenido
                link = crear_link_pago(cotizacion.descripcion, float(cotizacion.precio), f"s_{cita.id}") 
                texto_respuesta = f"Su cita ha sido agendada para el {fecha_disponible} a las {primer_horario}. Para confirmarla realice el pago de ${cotizacion.precio} MXN: {link}\n\nLe recomendamos realizar el pago lo antes posible ya que este link expira en 24 horas."

            else: # Si no se encuentran horarios se envía mensaje de error.
                texto_respuesta = f"Lo sentimos, no hay horarios disponibles. Si tiene alguna duda contáctenos al {numero_admin}"

            db.add(Historial(numero=numero, role="user", contenido=Body, fecha = ahora_mexico))
            db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta, fecha = ahora_mexico))
            db.commit() # Añade los cambios definitivos de la cita de servicio a la DB y al Historial
            return texto_respuesta
        else:
            servicio = db.query(CitaServicio).filter(
                CitaServicio.numero == numero,
                CitaServicio.estado.in_(["pago pendiente", "pagado"]),
                CitaServicio.fecha_servicio > ahora_mexico.date()
            ).order_by(CitaServicio.fecha.desc()).first()
            
            if servicio:
                fecha_serv = servicio.fecha_servicio 
                hora_serv = servicio.hora_servicio
                fecha_str = f"{dias[fecha_serv.weekday()]} {fecha_serv.day} de {meses[fecha_serv.month - 1]}"

                if servicio.estado == "pagado":
                    texto_respuesta = f"Su cita ha sido reagendada para el {fecha_serv} a las {hora_serv}. Hasta pronto!"
                else:
                    texto_respuesta = f"Su cita ha sido reagendada para el {fecha_serv} a las {hora_serv}. Para confirmarla realice el pago en el link anteriormente enviado"
            
            db.add(Historial(numero=numero, role="user", contenido=Body, fecha = ahora_mexico))
            db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta, fecha = ahora_mexico))
            db.commit() # Añade los cambios definitivos de la cita de servicio a la DB y al Historial
            return texto_respuesta
    
    # REAGENDAR
    if Body.strip().upper() == "REAGENDAR": # Detectar la intención de reagendar
        cotizacion = db.query(Cotizacion).filter( # Devuelve la 1° cotización filtrada con los sig parámetros:
            Cotizacion.numero == numero,
            Cotizacion.estado == "aceptada",
            Cotizacion.fecha_propuesta > ahora_mexico.date()
        ).order_by(Cotizacion.fecha.desc()).first()

        if cotizacion:
            fecha_actual = cotizacion.fecha_propuesta
            dia_siguiente = fecha_actual + timedelta(days=1)
            primer_horario, fecha_disponible = buscar_horario_disponible(db=db, fecha_inicio=dia_siguiente) 

            if primer_horario:
                cotizacion.hora_propuesta = primer_horario
                cotizacion.fecha_propuesta = fecha_disponible
                fecha_str = f"{dias[fecha_disponible.weekday()]} {fecha_disponible.day} de {meses[fecha_disponible.month - 1]}"
                texto_respuesta = f"Con gusto {cotizacion.nombre_cliente}. El siguiente horario disponible es el {fecha_str} a las {primer_horario}. Para confirmar responda CONFIRMO. Para sugerirle otro horario responda REAGENDAR"
                
            
            else:
                texto_respuesta = "Lo sentimos, no tenemos más horarios disponibles en los próximos 15 días. Le contactaremos para agendar."
        else:
            servicio = db.query(CitaServicio).filter(
                CitaServicio.numero == numero,
                CitaServicio.estado.in_(["pago pendiente", "pagado"]),
                CitaServicio.fecha_servicio > ahora_mexico.date()
            ).order_by(CitaServicio.fecha.desc()).first()

            if servicio:
                fecha_actual = servicio.fecha_servicio
                dia_siguiente = fecha_actual + timedelta(days=1)
                primer_horario, fecha_disponible = buscar_horario_disponible(db=db, fecha_inicio=dia_siguiente)

                if primer_horario:
                    servicio.fecha_servicio = fecha_disponible
                    servicio.hora_servicio = datetime.strptime(primer_horario, "%H:%M").time()
                    fecha_str = f"{dias[fecha_disponible.weekday()]} {fecha_disponible.day} de {meses[fecha_disponible.month - 1]}"
                    texto_respuesta = f"Con gusto {servicio.nombre_cliente}. El siguiente horario disponible para su servicio es el {fecha_str} a las {primer_horario}. Para confirmar responda CONFIRMO. Para sugerirle otro horario responda REAGENDAR."
                    
                    if servicio.estado == "pagado" and servicio.fecha_servicio == ahora_mexico.date():
                        mensaje_admin = f"AVISO: {servicio.nombre_cliente} reagendó su servicio pagado para el {fecha_disponible.strftime('%d/%m/%Y')} a las {primer_horario}."
                        await enviar_whatsapp(os.environ.get("ADMIN_NUMERO"), mensaje_admin)
                else:
                    texto_respuesta = "Lo sentimos, no tenemos más horarios disponibles en los próximos 15 días. Le contactaremos para agendar."
            else:
                visita = db.query(Visitas).filter(
                    Visitas.numero == numero,
                    Visitas.estado.in_(["pago pendiente", "pagado"]),
                    Visitas.fecha_visita >= ahora_mexico.date()
                ).order_by(Visitas.fecha.desc()).first()
            
                if visita:
                    fecha_actual = visita.fecha_visita
                    dia_siguiente = fecha_actual + timedelta(days=1)
                    primer_horario, fecha_disponible = buscar_horario_disponible(db=db, fecha_inicio=dia_siguiente, isServ=False)

                    if primer_horario:
                        visita.fecha_visita = fecha_disponible
                        visita.hora_visita = datetime.strptime(primer_horario, "%H:%M").time()
                        texto_respuesta = f"Con gusto {visita.nombre_cliente}. El siguiente horario disponible para su visita es el {fecha_disponible.strftime('%d/%m/%Y')} a las {primer_horario}. Para confirmar responda CONFIRMO. Para sugerirle otro horario responda REAGENDAR."
                    
                        if visita.estado == "pagado" and visita.fecha_visita == ahora_mexico.date():
                            mensaje_admin = f"URGENTE: {visita.nombre_cliente} reagendó su visita de HOY para el {fecha_disponible.strftime('%d/%m/%Y')} a las {primer_horario}."
                            await enviar_whatsapp(os.environ.get("ADMIN_NUMERO"), mensaje_admin)
                            print("pasó await WA")
                        else:
                            print("ignoro WA")
                    else:
                        texto_respuesta = "Lo sentimos, no tenemos más horarios disponibles en los próximos 15 días. Le contactaremos para agendar."
                else:
                    texto_respuesta = f"No encontramos cotización ni visita activa. Si tiene alguna pregunta contáctenos al {numero_admin}."

        db.add(Historial(numero=numero, role="user", contenido=Body, fecha = ahora_mexico))
        db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta, fecha = ahora_mexico))
        db.commit()
        return texto_respuesta
            
    # MOSTRAR AGENDA DEL DÍA PARA ADMIN
    if Body.strip().upper() == "AGENDA":
        if numero != os.environ.get("ADMIN_NUMERO"):
            print(f"ignoró a: {numero}")
            return None  # ignora si no es el admin, cae al Bloque 2
        
        hoy = ahora_mexico.date()
        
        visitas_hoy = db.query(Visitas).filter(
            Visitas.fecha_visita == hoy,
            Visitas.estado != "cancelada"
        ).all()
        
        servicios_hoy = db.query(CitaServicio).filter(
            CitaServicio.fecha_servicio == str(hoy),
            CitaServicio.estado != "cancelada"
        ).all()
        
        if not visitas_hoy and not servicios_hoy:
            texto_respuesta = f"No hay eventos agendados para hoy {hoy.strftime('%d/%m/%Y')}."
        else:
            lineas = [f"Agenda del {hoy.strftime('%d/%m/%Y')}:\n"]
            
            for v in visitas_hoy:
                hora = v.hora_visita.strftime('%H:%M') if v.hora_visita else "—"
                lineas.append(f"VISITA {hora} — {v.nombre_cliente} — {v.direccion} ({v.estado})")
            
            for s in servicios_hoy:
                hora = s.hora_servicio.strftime('%H:%M') if s.hora_servicio else "—"
                lineas.append(f"SERVICIO {hora} — {s.nombre_cliente} — {s.direccion} ({s.estado})")
            
            lineas.sort()  # ordena por hora
            texto_respuesta = "\n".join(lineas)
        
        db.add(Historial(numero=numero, role="user", contenido=Body, fecha = ahora_mexico))
        db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta, fecha = ahora_mexico))
        db.commit()
        return texto_respuesta

#BLOQUE 2 - LLAMAR A CLAUDE
    mensajes_db = db.query(Historial).filter( # Recupera el historial de este usuario desde la base de datos
    Historial.numero == numero
    ).order_by(Historial.fecha).all()
    
    historial = [{"role": m.role, "content": m.contenido} for m in mensajes_db] # Convierte a formato que entiende Claude
    historial.append({"role": "user", "content": Body}) # Agrega el mensaje nuevo
    db.add(Historial(numero=numero, role="user", contenido=Body, fecha = ahora_mexico)) # Guarda el mensaje del usuario en la base de datos
    db.commit()
    sesion = db.query(SesionCita).filter_by(numero=numero).first()

    datos_capturados = ""
    if sesion:
        partes = []
        if sesion.nombre:
            partes.append(f"Nombre: {sesion.nombre}")
        if sesion.direccion:
            partes.append(f"Dirección: {sesion.direccion}")
        if sesion.descripcion:
            partes.append(f"Descripción: {sesion.descripcion}")
        datos_capturados = "\n".join(partes)

    respuesta = cliente.messages.create( # Llama a Claude
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=construir_system_prompt(datos_capturados),
        messages=historial[-10:],  # solo los últimos 10 mensajes
    )
    texto_respuesta = respuesta.content[0].text
    db.add(Historial(numero=numero, role="assistant", contenido=texto_respuesta, fecha = ahora_mexico)) # Guarda la respuesta en la base de datos
    db.commit()

#BLOQUE 3 - PROCESAR RESPUESTA DE CLAUDE
    if "DATOS:" in texto_respuesta:
        visita_agendada = db.query(Visitas).filter(
                        Visitas.numero == numero,
                        Visitas.estado.in_(["pago pendiente", "pagado"]),
                        Visitas.fecha_visita >= ahora_mexico.date()
                    ).order_by(Visitas.fecha.desc()).first()
        if visita_agendada:
            texto_respuesta = f"Su última visita programada aun no sucede. Puede aprovechar ese día para consultar con los técnicos y anexar los servicios que requiera a su cotización.\n\nSi tiene alguna pregunta contáctenos al {numero_admin}."
        else:
            try:
                inicio = texto_respuesta.find("DATOS:")
                json_raw = texto_respuesta[inicio + 6:]
                inicio_json = json_raw.find("{")
                fin_json = json_raw.rfind("}") + 1
                datos = json.loads(json_raw[inicio_json:fin_json])

                sesion = db.query(SesionCita).filter_by(numero=numero).first()
                if not sesion:
                    sesion = SesionCita(numero=numero)
                    db.add(sesion)

                if "nombre" in datos:
                    sesion.nombre = datos["nombre"]
                if "direccion" in datos:
                    sesion.direccion = datos["direccion"]
                # Estos tres datos el bot los extrae según lo indicado en System Prompt
                if "descripcion" in datos:
                    sesion.descripcion = datos["descripcion"]
                if "fecha" in datos:
                    sesion.fecha = datos["fecha"]
                if "hora" in datos:
                    sesion.hora = datos["hora"]
                db.commit()

                if sesion.nombre and sesion.direccion:
                    texto_respuesta = f"Datos registrados.\nNombre: {sesion.nombre}\nDireccion: {sesion.direccion}\nTipo de servicio: {sesion.descripcion}\nFecha propuesta: {sesion.fecha}\nHora propuesta: {sesion.hora}\n\nContinuamos?"
                    datos_capturados += "\n\nTODOS LOS DATOS ESTÁN COMPLETOS. Si el cliente confirma, responde ÚNICAMENTE: CITA"
                else:
                    faltantes = []
                    if not sesion.nombre:
                        faltantes.append("nombre")
                    if not sesion.direccion:
                        faltantes.append("dirección")
                    
                    texto_respuesta = f"Aún necesito los siguientes datos: {', '.join(faltantes)}. ¿Me los podría proporcionar?"
            except Exception as e:
                print(f"DEBUG DATO - error: {e}")

    if "CITA" in texto_respuesta: # Detectar la intención de cita
        try:
            sesion = db.query(SesionCita).filter_by(numero=numero).first()
            # No pasa a la pinche cita si DATOS no están completos. Asi que SIEMPRE estarán completos en este bloque
            cita = Visitas(
                numero=numero,
                nombre_cliente=sesion.nombre,
                direccion=sesion.direccion,
                descripcion = sesion.descripcion,
                fecha_visita = sesion.fecha,
                hora_visita = sesion.hora,
                estado="pago pendiente"
            )
            db.add(cita)
            db.flush() 
            db.commit()
            db.delete(sesion)
            db.commit()
            
            precio_visita = 11.0 if DEBUG else float(os.environ.get("PRECIO_VISITA"))
            link = crear_link_pago("Visita de mantenimiento", precio_visita, f"v_{cita.id}", fecha_cita = cita.fecha_visita, hora_cita= cita.hora_visita)
            texto_respuesta = f"Cita registrada {sesion.nombre}. El costo de la visita es $475 MXN. Aquí está tu link de pago para confirmar la cita: {link}\n\nLe recomendamos realizar el pago lo antes posible ya que este link expira dos horas antes de su visita.\n\nPara sugerirle otro horario responda REAGENDAR."
        
        except Exception as e:
            print(f"DEBUG - error interno: {e}")
            texto_respuesta = "Hubo un problema al procesar tu cita. Por favor intenta de nuevo."
    
    ultimo_historial = db.query(Historial).filter(
        Historial.numero == numero,
        Historial.role == "assistant"
    ).order_by(Historial.fecha.desc()).first()

    if ultimo_historial:
        ultimo_historial.contenido = texto_respuesta
        ultimo_historial.fecha = ahora_mexico
        db.commit()

    return texto_respuesta

@app.post("/webhook/mercadopago")
async def webhook_mercadopago(request: Request):
    data = await request.json()

    if DEBUG: 
        orden_id = data.get("orden_id") #DEBUG sin pago
    else:
        # MercadoPago manda diferentes tipos de notificaciones, solo nos interesan las de pagos aprobados
        if data.get("type") != "payment":
            return {"status": "ok"}  # ignorar notificaciones que no son de pago
        
        # Consultamos el pago para obtener los detalles
        payment_id = data["data"]["id"]  
        sdk = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))
        payment = sdk.payment().get(payment_id)
        payment_info = payment["response"]
            
        if payment_info["status"] != "approved":
            return {"status": "ok"}  # ignorar pagos no aprobados
        
        orden_id = payment_info["external_reference"]
    
    db = SessionLocal()
    mensaje = None
    numero = None
    registro = None

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
    
    if registro and mensaje and numero:
        await enviar_whatsapp(numero, mensaje)

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
    mensaje = f"Hola {data.nombre_cliente}, le compartimos la cotización para el trabajo solicitado:\n\n{data.descripcion}\n\nPrecio estimado: ${data.precio} MXN\n\nPara aceptar y agendar su visita responda ACEPTO. Para cualquier duda estamos a sus órdenes al 9992717117."
    await enviar_whatsapp(data.numero, mensaje)

    db.close()
    return {"status": "cotizacion enviada", "id": cotizacion_id}

@app.get("/whatsapp/meta") # HTTP GET para verificación
async def verificar_meta(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    if mode == "subscribe" and token == os.environ.get("META_VERIFY_TOKEN"):
        return Response(content=challenge, media_type="text/plain")
    
    return Response(status_code=403)

@app.post("/whatsapp/meta") # HTTP POST para mensajes
async def whatsapp_meta(request: Request):
    data = await request.json() # Lee el cuerpo de la petición de Meta y lo convierte a diccionario Python

    if data.get("object") != "whatsapp_business_account": # Si los datos son diferentes a WA los ignora
        return {"status": "ok"}

    try:# Navega la estructura anidada del JSON de Meta para llegar a los datos del mensaje
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" not in value: # Si no hay mensajes nuevos, los ignora
            return {"status": "ok"}

        mensaje = value["messages"][0] # Navega la estructura anidada del JSON de Meta para llegar a los datos del mensaje.
        if mensaje.get("type") != "text":
            return {"status": "ok"}

        numero = f"whatsapp:+{mensaje['from']}" #Extrae los tres datos necesarios: # cliente, texto de mensaje y number ID
        Body = mensaje["text"]["body"]
        phone_number_id = value["metadata"]["phone_number_id"]

        db = SessionLocal() # Llama a procesar_mensaje
        texto_respuesta = await procesar_mensaje(numero, Body, db)
        db.close()

        async with httpx.AsyncClient() as client: #Llamar a API de META
            await client.post(
                f"https://graph.facebook.com/v18.0/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {os.environ.get('META_ACCESS_TOKEN')}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": mensaje["from"],
                    "type": "text",
                    "text": {"body": texto_respuesta}
                }
            )
    except Exception as e:
        print(f"DEBUG META - error: {e}")

    return {"status": "ok"}

async def enviar_whatsapp_meta(numero: str, mensaje: str):
    numero_limpio = numero.replace("whatsapp:+", "")
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://graph.facebook.com/v18.0/{os.environ.get('META_PHONE_NUMBER_ID')}/messages",
            headers={"Authorization": f"Bearer {os.environ.get('META_ACCESS_TOKEN')}"},
            json={
                "messaging_product": "whatsapp",
                "to": numero_limpio,
                "type": "text",
                "text": {"body": mensaje}
            }
        )
async def enviar_whatsapp(numero: str, mensaje: str):
    if os.environ.get("CANAL_WA") == "meta":
        await enviar_whatsapp_meta(numero, mensaje)