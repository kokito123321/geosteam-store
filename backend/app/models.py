from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text, DateTime, ForeignKey
)
from backend.app.database import Base

class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    price = Column(Float, nullable=False, default=0.0) # in GEL
    volume_ml = Column(Integer, default=30) # e.g. 30, 60, 100, 120 ml
    color_type = Column(String(100), default="") # e.g. "Salt Nicotine", "Freebase", color
    stock_quantity = Column(Integer, default=10)
    is_active = Column(Boolean, default=True) # in stock and visible
    photo_url = Column(String(1024), default="")
    channel_post_url = Column(String(1024), default="") # Link to Telegram post in channel
    vg_pg_ratio = Column(String(50), default="50/50") # e.g. "70/30", "50/50"
    nicotine_mg = Column(String(50), default="20mg") # e.g. "0mg", "3mg", "6mg", "20mg", "50mg"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String(255), default="")
    first_name = Column(String(255), default="")
    last_name = Column(String(255), default="")
    phone_number = Column(String(100), default="")
    language_code = Column(String(10), default="ka") # ka, en, ru
    bot_paused = Column(Boolean, default=False) # Human handoff state
    is_blacklisted = Column(Boolean, default=False) # Blacklist state for fraudulent activity
    order_state = Column(String(100), default="IDLE") # FSM state for ordering
    temp_cart = Column(Text, default="{}") # JSON cart
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String(50), unique=True, index=True, nullable=False)
    customer_telegram_id = Column(Integer, nullable=False, index=True)
    customer_name = Column(String(255), default="")
    customer_phone = Column(String(100), default="")
    items_json = Column(Text, default="[]") # JSON list of items
    total_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    promo_code = Column(String(50), default="")
    delivery_method = Column(String(50), default="courier") # courier, pickup, mail
    delivery_address = Column(Text, default="")
    location_lat = Column(Float, nullable=True)
    location_lng = Column(Float, nullable=True)
    payment_method = Column(String(50), default="cash") # cash, bank_transfer
    payment_status = Column(String(50), default="pending") # pending, paid
    order_status = Column(String(50), default="new") # new, processing, delivered, cancelled
    receipt_image_url = Column(String(1024), default="")
    receipt_file_id = Column(String(255), default="")
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    customer_telegram_id = Column(Integer, index=True, nullable=False)
    sender = Column(String(20), nullable=False) # "user", "ai", "admin"
    message_text = Column(Text, nullable=False)
    media_url = Column(String(1024), default="", nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class StoreSettings(Base):
    __tablename__ = "store_settings"

    id = Column(Integer, primary_key=True)
    system_prompt = Column(Text, default="")
    ai_tone = Column(String(100), default="official_humorous")
    fallback_message = Column(Text, default="სამწუხაროდ ამ ეტაპზე ეს პროდუქტი ამოწურულია. გნებავთ მსგავსი არომატი შემოგთავაზოთ თუ ოპერატორს დაგაკავშიროთ?")
    delivery_courier_enabled = Column(Boolean, default=True)
    delivery_tbilisi_yandex_enabled = Column(Boolean, default=True)
    delivery_pickup_enabled = Column(Boolean, default=True)
    delivery_mail_enabled = Column(Boolean, default=True)
    delivery_regions_center_fee = Column(Float, default=9.0)
    delivery_regions_village_fee = Column(Float, default=12.0)
    delivery_regions_duration_days = Column(Integer, default=3)
    pickup_address = Column(Text, default="")
    pickup_lat = Column(Float, default=41.6938)
    pickup_lng = Column(Float, default=44.8015)
    bank_name = Column(String(100), default="TBC Bank")
    bank_iban = Column(String(100), default="GE00TB0000000000000000")
    bank_recipient = Column(String(255), default="Geosteam")
    gemini_model = Column(String(100), default="gemini-2.5-flash")
    payment_cash_enabled = Column(Boolean, default=True)
    payment_bank_enabled = Column(Boolean, default=True)
    admin_telegram_ids = Column(String(255), default="")
    admin_email = Column(String(255), default="")
    smtp_host = Column(String(255), default="")
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String(255), default="")
    smtp_password = Column(String(255), default="")
    smtp_from_email = Column(String(255), default="")
    security_shield_enabled = Column(Boolean, default=True)
    security_audit_logs = Column(Text, default="[]") # JSON list of security logs

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    discount_percent = Column(Float, default=0.0) # e.g. 10.0 for 10%
    discount_amount = Column(Float, default=0.0) # fixed GEL
    min_order_amount = Column(Float, default=0.0)
    is_active = Column(Boolean, default=True)
    usage_limit = Column(Integer, default=100)
    times_used = Column(Integer, default=0)

class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), default="superadmin") # superadmin, manager, courier
    is_active = Column(Boolean, default=True)

class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id = Column(Integer, primary_key=True, index=True)
    raw_notes = Column(Text, default="")
    generated_text = Column(Text, nullable=False)
    image_path = Column(String(1024), default="")
    scheduled_for = Column(DateTime, nullable=True) # None = immediate
    status = Column(String(50), default="draft") # draft, scheduled, published, failed
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)

class AdminAssistantMessage(Base):
    __tablename__ = "admin_assistant_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender = Column(String(20), nullable=False) # "admin", "assistant"
    message_text = Column(Text, nullable=False)
    actions_performed = Column(Text, default="[]") # JSON list of actions performed
    timestamp = Column(DateTime, default=datetime.utcnow)

class BlacklistUser(Base):
    __tablename__ = "blacklist_users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True, nullable=False)
    username = Column(String(255), default="")
    full_name = Column(String(255), default="")
    reason = Column(String(500), default="არასწორი / ყალბი ქვითარი")
    receipt_url = Column(String(1024), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

