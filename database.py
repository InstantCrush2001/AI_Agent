import os
from sqlalchemy import create_engine, Column, String, Float, Text, DateTime, Time, Integer, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

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
    fecha = Column(DateTime, default=datetime.utcnow)

class Visitas(Base):
    __tablename__ = "visitas"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))   # número de WhatsApp
    nombre_cliente = Column(String(100))
    direccion = Column(Text)
    descripcion = Column(String(100))
    fecha = Column(DateTime, default=datetime.utcnow)
    fecha_visita = Column(DateTime, default=datetime.utcnow)
    hora_visita = Column(Time)
    estado = Column(String(20), default="pendiente")

    detalles = relationship("DetallePedido", back_populates="pedido")


# Crea las tablas en PostgreSQL si no existen
def crear_tablas():
    Base.metadata.create_all(engine)