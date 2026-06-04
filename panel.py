import streamlit as st
from dotenv import load_dotenv
import os
from collections import defaultdict

load_dotenv()
from database import SessionLocal, Visitas, CitaServicio, Cotizacion, Historial, HorarioBloqueado
from datetime import datetime, timedelta, timezone

MEXICO_TZ = timezone(timedelta(hours=-6))

st.set_page_config(page_title="Osorio Mantenimiento", layout="wide")
st.title("Panel de Administración — Osorio Mantenimiento")
db = SessionLocal()

# TABS 
tab1, tab2, tab3 = st.tabs([
    "Agenda Semanal",
    "Cotizaciones",
    "Historial de Conversaciones"
])
@st.dialog("Detalles del evento")
def mostrar_detalle(tipo, item, dia):
    if tipo == "visita":
        st.write(f"**ID:** {item.id}")
        st.write(f"**Cliente:** {item.nombre_cliente}")
        st.write(f"**Dirección:** {item.direccion}")
        st.write(f"**Hora:** {item.hora_visita.strftime('%H:%M') if item.hora_visita else '—'}")
        st.write(f"**Estado:** {item.estado}")
        st.write(f"**Descripción:** {item.descripcion}")
    elif tipo == "cita":
        hora_fin = (datetime.combine(dia, item.hora_servicio) + timedelta(hours=item.tiempo_servicio or 2)).strftime("%H:%M")
        st.write(f"**Cliente:** {item.nombre_cliente}")
        st.write(f"**Dirección:** {item.direccion}")
        st.write(f"**Horario:** {item.hora_servicio.strftime('%H:%M')} - {hora_fin}")
        st.write(f"**Descripción:** {item.descripcion}")
        st.write(f"**Precio:** ${item.precio} MXN")
        st.write(f"**Estado:** {item.estado}")

# TAB 1: AGENDA SEMANAL
with tab1:
    st.subheader("Agenda Semanal")

    if "semana_offset" not in st.session_state:
        st.session_state["semana_offset"] = 0

    nav1, nav2, nav3 = st.columns([1, 5, 1])
    with nav1:
        if st.button("◀ Anterior"):
            st.session_state["semana_offset"] -= 1
            st.rerun()
    with nav3:
        if st.button("Siguiente ▶"):
            st.session_state["semana_offset"] += 1
            st.rerun()

    hoy_real = datetime.now(MEXICO_TZ).date()
    hoy_ref = hoy_real + timedelta(weeks=st.session_state["semana_offset"])
    lunes = hoy_ref - timedelta(days=hoy_ref.weekday())
    dias = [lunes + timedelta(days=i) for i in range(7)]

    with nav2:
        st.markdown(f"**{dias[0].strftime('%d %b')} — {dias[6].strftime('%d %b %Y')}**")

    visitas = db.query(Visitas).order_by(Visitas.hora_visita).all()
    citas = db.query(CitaServicio).order_by(CitaServicio.hora_servicio).all()
    bloqueados = db.query(HorarioBloqueado).order_by(HorarioBloqueado.fecha,HorarioBloqueado.hora).all()

    visitas_por_dia = defaultdict(list)
    bloq_por_dia = defaultdict(list)
    citas_por_dia = defaultdict(list)

    for v in visitas:
        if v.fecha_visita:
            visitas_por_dia[v.fecha_visita].append(v)
    for b in bloqueados:
        if b.fecha:
            bloq_por_dia[b.fecha].append(b)
    for c in citas:
        if c.fecha_servicio:
            try:
                fecha_c = c.fecha_servicio
                citas_por_dia[fecha_c].append(c)
            except ValueError:
                pass

    ESTADO_ICON = {
        "pago pendiente": "🟡",
        "pagado": "🔵",
        "completada": "🟢",
        "cancelada": "🔴",
    }
    NOMBRES_DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    cols = st.columns(7)
    for i, (dia, col) in enumerate(zip(dias, cols)):
        with col:
            label = f"**{NOMBRES_DIAS[i]}**" + (" (HOY)" if dia == hoy_real else "")
            st.markdown(label)
            st.markdown(f"*{dia.strftime('%d/%m')}*")
            st.divider()

            itinerario = []
            for v in visitas_por_dia.get(dia, []):
                t = v.hora_visita or datetime.min.time()
                itinerario.append((t, "visita", v))
            for b in bloq_por_dia.get(dia, []):
                t = datetime.strptime(b.hora, "%H:%M").time()
                itinerario.append((t,"bloqueado",b))
            for c in citas_por_dia.get(dia, []):
                try:
                    t = c.hora_servicio if c.hora_servicio else datetime.min.time()
                except ValueError:
                    t = datetime.min.time()
                itinerario.append((t, "cita", c))
            itinerario.sort(key=lambda x: x[0])

            if not itinerario:
                st.caption("Sin eventos")

            for t, tipo, item in itinerario:
                hora_str = t.strftime("%H:%M") if t != datetime.min.time() else "—"
                with st.container(border=True):
                    if tipo == "visita":
                        st.markdown(f"**VISITA · {hora_str}**")
                        st.caption(item.nombre_cliente)
                        if st.button("Detalles", key=f"btn_visita_{item.id}"):
                            mostrar_detalle("visita", item, dia)
                        st.divider()
                        st.caption(f"{ESTADO_ICON.get(item.estado, '')} {item.estado}")
                        if item.estado == "pagado":
                            b1, b2 = st.columns(2)
                            with b1:
                                if st.button("✓", key=f"cv_{item.id}", help="Completar"):
                                    item.estado = "completada"
                                    db.commit()
                                    st.rerun()
                            with b2:
                                if st.button("✗", key=f"xv_{item.id}", help="Cancelar"):
                                    item.estado = "cancelada"
                                    db.commit()
                                    st.rerun()
                        if item.estado == " pago pendiente":
                            if st.button("Cancelar", key=f"xc_{item.id}"):
                                item.estado = "cancelada"
                                db.commit()
                                st.rerun()
                    elif tipo == "bloqueado":
                        st.markdown(f"**BLOQUEADO · {hora_str}**")
                        if st.button("Desbloquear", key=f"del_b_{item.id}"):
                            db.delete(item)
                            db.commit()
                            st.rerun()
                    else:
                        hora_fin = (datetime.combine(dia, t) + timedelta(hours=item.tiempo_servicio or 2)).strftime("%H:%M")
                        st.markdown(f"**SERVICIO · {hora_str}-{hora_fin}**")
                        st.caption(item.nombre_cliente)
                        if st.button(f"Detalles", key=f"btn_cita_{item.id}"):
                            mostrar_detalle("cita", item, dia)
                        st.divider()
                        st.caption(f"{ESTADO_ICON.get(item.estado, '')} {item.estado}")
                        if item.estado == "pagado":
                            b1, b2 = st.columns(2)
                            with b1:
                                if st.button("✓", key=f"cc_{item.id}", help="Completar"):
                                    item.estado = "completada"
                                    db.commit()
                                    st.rerun()
                            with b2:
                                if st.button("✗", key=f"xc_{item.id}", help="Cancelar"):
                                    item.estado = "cancelada"
                                    db.commit()
                                    st.rerun()
                        if item.estado == "pago pendiente":
                            if st.button("Cancelar", key=f"xv_{item.id}"):
                                item.estado = "cancelada"
                                db.commit()
                                st.rerun()
    st.divider()
    st.subheader("Bloquear horario")
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        fecha_bloqueo = st.date_input("Fecha", key="fecha_bloqueo")

    HORAS_OPCIONES = ["09:00", "11:00", "13:00", "16:00", "18:00"]

    ocupadas_bloqueo = set()
    for v in visitas:
        if v.fecha_visita == fecha_bloqueo and v.estado != "cancelada" and v.hora_visita:
            ocupadas_bloqueo.add(v.hora_visita.strftime("%H:%M"))
    for c in citas:
        if c.fecha_servicio == fecha_bloqueo and c.estado != "cancelada" and c.hora_servicio:
            hora_inicio = c.hora_servicio.hour
            duracion = c.tiempo_servicio or 2
            for i in range(duracion):
                hora_bloq = hora_inicio + i
                if hora_bloq < 18:
                    ocupadas_bloqueo.add(f"{hora_bloq:02d}:00")
    for b in bloqueados:
        if b.fecha == fecha_bloqueo:
            ocupadas_bloqueo.add(b.hora)

    horas_libres = [h for h in HORAS_OPCIONES if h not in ocupadas_bloqueo]

    with col2:
        if horas_libres:
            hora_bloqueo = st.selectbox("Horario", horas_libres, key="hora_bloqueo")
        else:
            st.warning("Todos los horarios de este día están ocupados.")
            hora_bloqueo = None
    with col3:
        st.write("")
        st.write("")
        if hora_bloqueo and st.button("Bloquear"):
            db.add(HorarioBloqueado(
                fecha=fecha_bloqueo,
                hora=hora_bloqueo
            ))
            db.commit()
            st.success(f"Horario {hora_bloqueo} del {fecha_bloqueo.strftime('%d/%m/%Y')} bloqueado")
            st.rerun()

# TAB 2: COTIZACIONES 
with tab2:
    st.subheader("Cotizaciones")

    cotizaciones = db.query(Cotizacion).order_by(Cotizacion.fecha.desc()).all()

    for cot in cotizaciones:
        with st.expander(f"{cot.nombre_cliente} — ${cot.precio} MXN — {cot.estado.upper()}"):
            st.write(f"Descripción: {cot.descripcion}")
            st.write(f"Número: {cot.numero}")
            st.write(f"Estado: {cot.estado}")
            st.write(f"Fecha: {cot.fecha}")

    st.divider()
    st.subheader("Nueva Cotización")

    with st.form("nueva_cotizacion"):
        numero = st.text_input("Número WhatsApp", placeholder="whatsapp:+521234567890")
        nombre = st.text_input("Nombre del cliente")
        descripcion = st.text_area("Descripción del trabajo")
        precio = st.number_input("Precio MXN", min_value=0)
        visita_id = st.number_input("ID de visita", min_value=0)
        submitted = st.form_submit_button("Enviar cotización")

        if submitted:
            import requests
            response = requests.post(
                f"{os.environ.get('BASE_URL')}/cotizaciones",
                json={
                    "numero": numero,
                    "nombre_cliente": nombre,
                    "descripcion": descripcion,
                    "precio": int(precio),
                    "visita_id": int(visita_id)
                }
            )
            if response.status_code == 200:
                st.success("Cotización enviada correctamente")
                st.rerun()
            else:
                st.error(f"Error: {response.text}")

# TAB 3: HISTORIAL
with tab3:
    st.subheader("Historial de Conversaciones")

    numero_buscar = st.text_input("Número WhatsApp", placeholder="whatsapp:+521234567890")

    if numero_buscar:
        mensajes = db.query(Historial).filter(
            Historial.numero == numero_buscar
        ).order_by(Historial.fecha).all()

        if mensajes:
            for m in mensajes:
                if m.role == "user":
                    st.chat_message("user").write(m.contenido)
                else:
                    st.chat_message("assistant").write(m.contenido)
        else:
            st.info("No hay conversaciones para ese número")

db.close()
