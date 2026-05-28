import os
from sqlalchemy import create_engine, Column, String, Float, Text, DateTime, Date, Time, Integer, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, date

DATABASE_URL = os.environ.get("DATABASE_URL")

# Motor de conexión a PostgreSQL
engine = create_engine(DATABASE_URL)

# Sesión para hacer consultas
SessionLocal = sessionmaker(bind=engine)

# Base para definir tablas
Base = declarative_base()


class Historial(Base):
    __tablename__ = "historiales"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))   # número de WhatsApp del usuario
    role = Column(String(20))     # "user" o "assistant"
    contenido = Column(Text)      # el texto del mensaje
    fecha = Column(DateTime(timezone=True), default=datetime.now())

class Visitas(Base):
    __tablename__ = "visitas"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))   # número de WhatsApp
    nombre_cliente = Column(String(100))
    direccion = Column(Text)
    descripcion = Column(String(100))
    fecha = Column(Date, default=date.today)
    fecha_visita = Column(Date, default=date.today)
    hora_visita = Column(Time)
    estado = Column(String(20), default="pendiente")


class Cotizacion(Base):
    __tablename__ = "cotizaciones"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))        # número de WhatsApp del cliente
    nombre_cliente = Column(String(100))
    descripcion = Column(Text)         # descripción del trabajo
    precio = Column(Integer)           # precio estimado
    estado = Column(String(20), default="enviada")  # enviada, aceptada, rechazada
    fecha = Column(DateTime(timezone=True), default=datetime.now())
    tiempo_servicio = Column(Integer, default=2)
    fecha_propuesta = Column(Date, default=date.today)
    hora_propuesta = Column(Time)
    visita_id = Column(Integer, ForeignKey("visitas.id"))

class CitaServicio(Base):
    __tablename__ = "citas_servicio"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))
    nombre_cliente = Column(String(100))
    direccion = Column(Text)
    descripcion = Column(Text)          # el trabajo a realizar
    precio = Column(Integer)            # precio de la cotización aceptada
    tiempo_servicio = Column(Integer, default=2)
    fecha_servicio = Column(Date, default=date.today)
    hora_servicio = Column(Time)
    estado = Column(String(20), default="pendiente")  # pendiente, confirmada, completada, cancelada
    cotizacion_id = Column(Integer, ForeignKey("cotizaciones.id"))  # referencia a la cotización
    fecha = Column(DateTime(timezone=True), default=datetime.now())

# Crea las tablas en PostgreSQL si no existen
def crear_tablas():
    Base.metadata.create_all(engine)