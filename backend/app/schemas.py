from typing import Optional, List, Any
from pydantic import BaseModel
from datetime import datetime

class ProductBase(BaseModel):
    name: str
    description: Optional[str] = ""
    price: float
    volume_ml: Optional[int] = 30
    color_type: Optional[str] = ""
    stock_quantity: Optional[int] = 10
    is_active: Optional[bool] = True
    photo_url: Optional[str] = ""
    channel_post_url: Optional[str] = ""
    vg_pg_ratio: Optional[str] = "50/50"
    nicotine_mg: Optional[str] = "20mg"

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    volume_ml: Optional[int] = None
    color_type: Optional[str] = None
    stock_quantity: Optional[int] = None
    is_active: Optional[bool] = None
    photo_url: Optional[str] = None
    channel_post_url: Optional[str] = None
    vg_pg_ratio: Optional[str] = None
    nicotine_mg: Optional[str] = None

class ProductResponse(ProductBase):
    id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class OrderBase(BaseModel):
    customer_telegram_id: int
    customer_name: Optional[str] = ""
    customer_phone: Optional[str] = ""
    items_json: str
    total_amount: float
    discount_amount: Optional[float] = 0.0
    promo_code: Optional[str] = ""
    delivery_method: str = "courier"
    delivery_address: Optional[str] = ""
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    payment_method: str = "cash"
    payment_status: Optional[str] = "pending"
    order_status: Optional[str] = "new"
    receipt_image_url: Optional[str] = ""
    receipt_file_id: Optional[str] = ""
    notes: Optional[str] = ""

class OrderCreate(OrderBase):
    pass

class OrderUpdate(BaseModel):
    payment_status: Optional[str] = None
    order_status: Optional[str] = None
    notes: Optional[str] = None

class OrderResponse(OrderBase):
    id: int
    order_number: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class StoreSettingsSchema(BaseModel):
    system_prompt: Optional[str] = ""
    ai_tone: Optional[str] = "official_humorous"
    fallback_message: Optional[str] = ""
    delivery_courier_enabled: Optional[bool] = True
    delivery_tbilisi_yandex_enabled: Optional[bool] = True
    delivery_pickup_enabled: Optional[bool] = True
    delivery_mail_enabled: Optional[bool] = True
    delivery_regions_center_fee: Optional[float] = 9.0
    delivery_regions_village_fee: Optional[float] = 12.0
    delivery_regions_duration_days: Optional[int] = 3
    pickup_address: Optional[str] = ""
    pickup_lat: Optional[float] = 41.6938
    pickup_lng: Optional[float] = 44.8015
    bank_name: Optional[str] = "TBC Bank"
    bank_iban: Optional[str] = ""
    bank_recipient: Optional[str] = "Geosteam"
    gemini_model: Optional[str] = "gemini-2.5-flash"
    payment_cash_enabled: Optional[bool] = True
    payment_bank_enabled: Optional[bool] = True
    admin_telegram_ids: Optional[str] = ""
    admin_email: Optional[str] = ""
    smtp_host: Optional[str] = ""
    smtp_port: Optional[int] = 587
    smtp_user: Optional[str] = ""
    smtp_password: Optional[str] = ""
    smtp_from_email: Optional[str] = ""
    security_shield_enabled: Optional[bool] = True
    security_audit_logs: Optional[str] = "[]"

    class Config:
        from_attributes = True

class BulkDeleteProductsRequest(BaseModel):
    product_ids: List[int]

class GenerateChannelPostRequest(BaseModel):
    notes: Optional[str] = None
    raw_notes: Optional[str] = None
    image_url: Optional[str] = None
    photo_url: Optional[str] = None

class PublishChannelPostRequest(BaseModel):
    text: str
    photo_url: Optional[str] = None
    scheduled_for: Optional[str] = None # ISO format or None

class ScheduledPostResponse(BaseModel):
    id: int
    raw_notes: Optional[str] = ""
    generated_text: str
    image_path: Optional[str] = ""
    scheduled_for: Optional[datetime] = None
    status: str
    error_message: Optional[str] = ""
    created_at: Optional[datetime] = None
    published_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class PromoCodeCreate(BaseModel):
    code: str
    discount_percent: Optional[float] = 0.0
    discount_amount: Optional[float] = 0.0
    min_order_amount: Optional[float] = 0.0
    is_active: Optional[bool] = True
    usage_limit: Optional[int] = 100

class PromoCodeResponse(PromoCodeCreate):
    id: int
    times_used: int

    class Config:
        from_attributes = True

class BroadcastRequest(BaseModel):
    message: str
    photo_url: Optional[str] = None
    target: Optional[str] = "all" # "all", "bot_users", "channel"

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str
