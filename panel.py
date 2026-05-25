import streamlit as st
from dotenv import load_dotenv
import os
from collections import defaultdict

load_dotenv()
from database import SessionLocal, Visitas, CitaServicio, Cotizacion, Historial
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

    visitas_por_dia = defaultdict(list)
    for v in visitas:
        if v.fecha_visita:
            visitas_por_dia[v.fecha_visita].append(v)

    citas_por_dia = defaultdict(list)
    for c in citas:
        if c.fecha_servicio:
            try:
                fecha_c = datetime.strptime(c.fecha_servicio, "%Y-%m-%d").date()
                citas_por_dia[fecha_c].append(c)
            except ValueError:
                pass

    ESTADO_ICON = {
        "pendiente": "🟡",
        "confirmada": "🔵",
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
            for c in citas_por_dia.get(dia, []):
                try:
                    t = datetime.strptime(c.hora_servicio, "%H:%M").time() if c.hora_servicio else datetime.min.time()
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
                        st.caption(f"{ESTADO_ICON.get(item.estado, '⚪')} {item.estado}")
                        if item.estado == "pendiente":
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
                    else:
                        st.markdown(f"**SERVICIO · {hora_str}**")
                        st.caption(item.nombre_cliente)
                        st.caption(f"{ESTADO_ICON.get(item.estado, '⚪')} {item.estado}")
                        if item.estado in ("pendiente", "confirmada"):
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
