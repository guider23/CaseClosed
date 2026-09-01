from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import config

Base = declarative_base()


class Customer(Base):
    __tablename__ = "customers"

    customer_id = Column(String, primary_key=True)
    account_age_days = Column(Integer, nullable=False)
    persona = Column(String, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    customer_id = Column(String, nullable=False)
    payment_id = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    item = Column(String, nullable=False)
    order_date = Column(DateTime, nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"

    order_id = Column(String, primary_key=True)
    courier = Column(String, nullable=False)
    tracking_id = Column(String, nullable=False)
    timeline = Column(JSON, nullable=False)
    delivered_at = Column(DateTime, nullable=True)
    pod_id = Column(String, nullable=True)
    receiver_name = Column(String, nullable=True)
    signature_flag = Column(Boolean, nullable=False)


class ChatLog(Base):
    __tablename__ = "chat_logs"

    order_id = Column(String, primary_key=True)
    messages = Column(JSON, nullable=False)


class Dispute(Base):
    __tablename__ = "disputes"

    dispute_id = Column(String, primary_key=True)
    payment_id = Column(String, nullable=False)
    order_id = Column(String, nullable=False)
    dispute_type = Column(String, nullable=False)
    reason_code = Column(String, nullable=False)
    raised_at = Column(DateTime, nullable=False)
    respond_by = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    label = Column(String, nullable=True)
    split = Column(String, nullable=True)

    # processing state
    status = Column(String, default="received")
    win_prob = Column(Float, nullable=True)
    draft = Column(Text, nullable=True)
    gate_reason = Column(String, nullable=True)
    evidence_bundle = Column(JSON, nullable=True)


engine = create_engine(config.database_url, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    Base.metadata.create_all(engine)
