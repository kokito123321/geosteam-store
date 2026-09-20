from telegram import (
    ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
)
from typing import List, Optional
from backend.app.models import StoreSettings, Product

def get_main_keyboard(is_admin: bool = False, webapp_url: Optional[str] = None) -> ReplyKeyboardMarkup:
    """Returns the persistent main menu keyboard."""
    keyboard = [
        [KeyboardButton(text="📦 კატალოგი"), KeyboardButton(text="🛒 შეკვეთის გაფორმება")],
        [KeyboardButton(text="ℹ️ მაღაზია & ლოკაცია"), KeyboardButton(text="🇬🇪 ჩვენს შესახებ")],
        [KeyboardButton(text="🙋‍♂️ ოპერატორი")]
    ]
    if is_admin and webapp_url:
        keyboard.append([
            KeyboardButton(text="📱 მართვის პანელი (Mini App)", web_app=WebAppInfo(url=webapp_url))
        ])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_contact_request_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard requesting user's phone contact."""
    keyboard = [
        [KeyboardButton(text="📱 ტელეგრამის ნომრის გაზიარება", request_contact=True)],
        [KeyboardButton(text="✍️ სხვა ნომრის ჩაწერა"), KeyboardButton(text="❌ შეკვეთის გაუქმება")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_location_request_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard requesting delivery location."""
    keyboard = [
        [KeyboardButton(text="📍 GPS ლოკაციის გაზიარება", request_location=True)],
        [KeyboardButton(text="✍️ მისამართის ხელით ჩაწერა"), KeyboardButton(text="❌ შეკვეთის გაუქმება")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

def get_delivery_inline_keyboard(settings: StoreSettings) -> InlineKeyboardMarkup:
    """Inline options for delivery."""
    center_fee = getattr(settings, 'delivery_regions_center_fee', 9.0) or 9.0
    village_fee = getattr(settings, 'delivery_regions_village_fee', 12.0) or 12.0
    duration = getattr(settings, 'delivery_regions_duration_days', 3) or 3

    buttons = [
        [InlineKeyboardButton("🛵 თბილისი (Yandex საკურიერო)", callback_data="delivery_tbilisi_yandex")],
        [InlineKeyboardButton(f"🏙️ რეგიონები - ცენტრი ({center_fee:.0f}₾, {duration} დღე)", callback_data="delivery_region_center")],
        [InlineKeyboardButton(f"🏡 რეგიონები - სოფლები ({village_fee:.0f}₾, {duration} დღე)", callback_data="delivery_region_village")],
        [InlineKeyboardButton("🏬 თვითგატანა (მაღაზიიდან - უფასო)", callback_data="delivery_pickup")],
        [InlineKeyboardButton("❌ გაუქმება", callback_data="order_cancel")]
    ]
    return InlineKeyboardMarkup(buttons)

def get_payment_inline_keyboard(settings: StoreSettings) -> InlineKeyboardMarkup:
    """Inline options for payment."""
    buttons = []
    if settings.payment_bank_enabled:
        buttons.append([InlineKeyboardButton("💳 საბანკო გადარიცხვა", callback_data="payment_bank")])
    if settings.payment_cash_enabled:
        buttons.append([InlineKeyboardButton("💵 ნაღდი ანგარიშსწორება (ადგილზე)", callback_data="payment_cash")])
    buttons.append([InlineKeyboardButton("❌ გაუქმება", callback_data="order_cancel")])
    return InlineKeyboardMarkup(buttons)

def get_product_action_keyboard(product_id: int, channel_url: Optional[str] = None) -> InlineKeyboardMarkup:
    """Action buttons for a single product."""
    buttons = [
        [InlineKeyboardButton("🛒 შეკვეთა", callback_data=f"buy_prod_{product_id}")]
    ]
    if channel_url:
        buttons.append([InlineKeyboardButton("📢 პოსტი ჩანელში", url=channel_url)])
    return InlineKeyboardMarkup(buttons)

def get_catalog_selection_keyboard(products: List[Product]) -> InlineKeyboardMarkup:
    """Inline list of available products."""
    buttons = []
    for p in products:
        if p.is_active and p.stock_quantity > 0:
            btn_text = f"{p.name} - {p.price:.2f} GEL ({p.nicotine_mg})"
            buttons.append([InlineKeyboardButton(btn_text, callback_data=f"view_prod_{p.id}")])
    buttons.append([InlineKeyboardButton("🔙 მთავარი მენიუ", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(buttons)
