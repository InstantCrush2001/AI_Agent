import os
from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
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
    estado = Column(String(20), default="pendiente")
    fecha = Column(DateTime, default=datetime.utcnow)

class Pedido(Base):
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))   # número de WhatsApp
    producto = Column(String(100))
    precio = Column(Integer)
    nombre_cliente = Column(String(100))
    direccion = Column(Text)
    fecha = Column(DateTime, default=datetime.utcnow)

class Producto(Base):
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True)
    nombre = Column(String(100))
    set = Column(Integer)
    año = Column(Integer)
    tipo = Column(String(50))
    precio = Column(Integer)
    Pz_actuales = Column(Integer)
    Pz_totales = Column(Integer)

# Crea las tablas en PostgreSQL si no existen
def crear_tablas():
    Base.metadata.create_all(engine)