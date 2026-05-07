import os
from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer, ForeignKey
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

class Pedido(Base):
    __tablename__ = "pedidos"

    id = Column(Integer, primary_key=True)
    numero = Column(String(50))   # número de WhatsApp
    # producto = Column(String(100))
    # cantidad = Column(Integer)
    # precio = Column(Integer)
    nombre_cliente = Column(String(100))
    direccion = Column(Text)
    fecha = Column(DateTime, default=datetime.utcnow)
    estado = Column(String(20), default="pendiente")

    detalles = relationship("DetallePedido", back_populates="pedido")

class DetallePedido(Base):
    __tablename__ = "detalles_pedido"

    id = Column(Integer, primary_key=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id"))
    producto = Column(String(100))
    cantidad = Column(Integer)
    precio_unitario = Column(Integer)

    pedido = relationship("Pedido", back_populates="detalles")

class Producto(Base):
    __tablename__ = "productos"

    id = Column(Integer, primary_key=True)
    clave_prod = Column(String(50))
    nombre = Column(String(100))
    uso = Column(String(50))
    marca = Column(String(50))
    stock = Column(Integer)
    tipo = Column(String(50))
    precio = Column(Integer)
    proveedor = Column(String(50))

# Crea las tablas en PostgreSQL si no existen
def crear_tablas():
    Base.metadata.create_all(engine)