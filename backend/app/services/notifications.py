import json
import logging
from typing import List, Dict, Any, Optional
from email.message import EmailMessage
import aiosmtplib
from fastapi import WebSocket
from backend.app.config import settings
from backend.app.models import Order, StoreSettings

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {e}")
                self.disconnect(connection)

ws_manager = ConnectionManager()

async def send_email_alert(
    subject: str,
    body: str,
    store_settings: Optional[StoreSettings] = None,
    html_body: Optional[str] = None
) -> bool:
    """Sends email alert via SMTP with auto port fallback (465 SSL / 587 TLS)."""
    if not store_settings:
        from backend.app.database import async_session_maker
        from sqlalchemy import select
        async with async_session_maker() as session:
            res = await session.execute(select(StoreSettings).limit(1))
            store_settings = res.scalars().first()

    host = (store_settings.smtp_host if store_settings else "") or settings.SMTP_HOST
    config_port = int((store_settings.smtp_port if store_settings else None) or settings.SMTP_PORT or 465)
    user = (store_settings.smtp_user if store_settings else "") or settings.SMTP_USER
    password = (store_settings.smtp_password if store_settings else "") or settings.SMTP_PASSWORD
    from_email = (store_settings.smtp_from_email if store_settings else "") or settings.SMTP_FROM_EMAIL or user
    to_email = (store_settings.admin_email if store_settings else "") or settings.ADMIN_EMAIL

    if not host or not to_email:
        logger.info(f"SMTP not fully configured (Host: '{host}', To: '{to_email}'). Skipping email alert.")
        return False

    msg = EmailMessage()
    msg["From"] = from_email or user or "noreply@geosteam.ge"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if html_body:
        msg.add_alternative(html_body, subtype="html")

    # Cloud hosting providers (e.g. Render, AWS, GCP) often block plaintext port 587.
    # Port 465 (SMTPS direct SSL) is direct and standard.
    # We attempt both 465 SSL and 587 TLS for maximum reliability.
    port_attempts = [(465, True, False), (587, False, True)]
    if config_port == 587:
        port_attempts = [(465, True, False), (587, False, True)]

    last_err = None
    for port, is_ssl, is_tls in port_attempts:
        try:
            logger.info(f"Attempting SMTP send to {to_email} via {host}:{port} (SSL={is_ssl}, TLS={is_tls})...")
            await aiosmtplib.send(
                msg,
                hostname=host,
                port=port,
                username=user if user else None,
                password=password if password else None,
                start_tls=is_tls,
                use_tls=is_ssl,
                timeout=12
            )
            logger.info(f"✅ Email alert sent successfully to {to_email} via {host}:{port}")
            return True
        except Exception as e:
            last_err = e
            logger.warning(f"SMTP attempt via {host}:{port} failed: {e}")

    logger.error(f"❌ Failed to send email alert to {to_email} via all SMTP ports: {last_err}")
    return False

async def notify_new_order(order: Order, store_settings: Optional[StoreSettings] = None, bot_app=None):
    """
    Dispatches order notification across 3 channels:
    1. Telegram to Admins
    2. Admin Dashboard Live WebSocket (Audio/Badge)
    3. Email to Admin (HTML & Text)
    """
    if not store_settings:
        from backend.app.database import async_session_maker
        from sqlalchemy import select
        async with async_session_maker() as session:
            res = await session.execute(select(StoreSettings).limit(1))
            store_settings = res.scalars().first()

    # 1. Parse Items
    try:
        items = json.loads(order.items_json) if order.items_json else []
    except Exception:
        items = []

    items_text = ""
    items_html_rows = ""
    for it in items:
        nic = f" ({it.get('nicotine_mg')})" if it.get('nicotine_mg') else ""
        subtotal = float(it.get('price', 0)) * int(it.get('quantity', 1))
        items_text += f"• {it.get('name')}{nic} x{it.get('quantity', 1)} = {subtotal:.2f} GEL\n"
        items_html_rows += f"""
        <tr>
            <td style="padding: 8px; border-bottom: 1px solid #e2e8f0;">{it.get('name')}{nic}</td>
            <td style="padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: center;">{it.get('quantity', 1)}</td>
            <td style="padding: 8px; border-bottom: 1px solid #e2e8f0; text-align: right;">{subtotal:.2f} GEL</td>
        </tr>
        """

    delivery_title = {
        "courier": "🛵 კურიერით მიტანა",
        "pickup": "🏬 თვითგატანა (მაღაზიიდან)",
        "mail": "📦 ფოსტით გაგზავნა"
    }.get(order.delivery_method, order.delivery_method)

    payment_title = {
        "cash": "💵 ნაღდი ანგარიშსწორება",
        "bank_transfer": "💳 საბანკო გადარიცხვა"
    }.get(order.payment_method, order.payment_method)

    location_link = ""
    if order.location_lat and order.location_lng:
        location_link = f"\n📍 [რუკაზე ნახვა](https://www.google.com/maps?q={order.location_lat},{order.location_lng})"

    # Compose Telegram message
    tg_message = (
        f"🚨 **ახალი შეკვეთა #{order.order_number}!**\n\n"
        f"👤 **მომხმარებელი:** {order.customer_name or 'უცნობი'}\n"
        f"📞 **ტელეფონი:** `{order.customer_phone or 'არ არის მითითებული'}`\n"
        f"🆔 **Telegram ID:** `{order.customer_telegram_id}`\n\n"
        f"🛒 **პროდუქცია:**\n{items_text or 'პროდუქცია არ ჩანს'}\n"
        f"💰 **სულ გადასახდელი:** **{order.total_amount:.2f} GEL**\n\n"
        f"🚚 **მიწოდება:** {delivery_title}\n"
        f"🏠 **მისამართი:** {order.delivery_address or 'არ არის მითითებული'}{location_link}\n"
        f"💳 **გადახდა:** {payment_title} ({order.payment_status})\n"
        f"{f'💬 მომხმარებლის მოწერილი: {order.notes}' if order.notes else ''}"
    )

    # 1. Dispatch Telegram Alert to Admins
    admin_ids_str = (store_settings.admin_telegram_ids if store_settings else "") or settings.ADMIN_TELEGRAM_IDS
    if bot_app and admin_ids_str:
        admin_ids = [aid.strip() for aid in admin_ids_str.split(",") if aid.strip()]
        for admin_id in admin_ids:
            try:
                await bot_app.bot.send_message(
                    chat_id=int(admin_id),
                    text=tg_message,
                    parse_mode="Markdown",
                    disable_web_page_preview=False
                )
            except Exception as e:
                logger.error(f"Failed to send Telegram alert to admin {admin_id}: {e}")

    # 2. Dispatch WebSocket to Dashboard
    await ws_manager.broadcast({
        "type": "new_order",
        "order": {
            "id": order.id,
            "order_number": order.order_number,
            "customer_name": order.customer_name,
            "customer_phone": order.customer_phone,
            "total_amount": order.total_amount,
            "delivery_method": order.delivery_method,
            "payment_method": order.payment_method,
            "payment_status": order.payment_status,
            "notes": order.notes or "",
            "created_at": order.created_at.isoformat() if order.created_at else ""
        }
    })

    # 3. Dispatch Email Alert (Text & HTML)
    email_text = (
        f"შემოვიდა ახალი შეკვეთა #{order.order_number}\n\n"
        f"მომხმარებელი: {order.customer_name}\n"
        f"ტელეფონი: {order.customer_phone}\n"
        f"თანხა: {order.total_amount:.2f} GEL\n"
        f"მიწოდება: {delivery_title}\n"
        f"მისამართი: {order.delivery_address}\n"
        f"გადახდა: {payment_title}\n"
        f"მომხმარებლის მოწერილი: {order.notes or 'შენიშვნის გარეშე'}\n\n"
        f"შეკვეთის დეტალები:\n{items_text}"
    )

    html_email = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; background-color: #f8fafc; padding: 20px; color: #1e293b;">
        <div style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 24px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); border: 1px solid #e2e8f0;">
            <div style="text-align: center; border-bottom: 2px solid #6366f1; padding-bottom: 16px; margin-bottom: 20px;">
                <h2 style="color: #6366f1; margin: 0;">🚨 ახალი შეკვეთა #{order.order_number}</h2>
                <p style="color: #64748b; margin: 4px 0 0 0; font-size: 14px;">Geosteam Online Store</p>
            </div>
            
            <table style="width: 100%; margin-bottom: 20px; font-size: 14px;">
                <tr>
                    <td style="padding: 4px 0; color: #64748b; width: 140px;">👤 <strong>მომხმარებელი:</strong></td>
                    <td style="padding: 4px 0; font-weight: 600;">{order.customer_name or 'უცნობი'}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #64748b;">📞 <strong>ტელეფონი:</strong></td>
                    <td style="padding: 4px 0;">{order.customer_phone or 'არ არის მითითებული'}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #64748b;">🚚 <strong>მიწოდება:</strong></td>
                    <td style="padding: 4px 0;">{delivery_title}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #64748b;">🏠 <strong>მისამართი:</strong></td>
                    <td style="padding: 4px 0;">{order.delivery_address or 'არ არის მითითებული'}</td>
                </tr>
                <tr>
                    <td style="padding: 4px 0; color: #64748b;">💳 <strong>გადახდა:</strong></td>
                    <td style="padding: 4px 0;">{payment_title} ({order.payment_status})</td>
                </tr>
                {f'''
                <tr>
                    <td style="padding: 4px 0; color: #6366f1;">💬 <strong>მოწერილი:</strong></td>
                    <td style="padding: 4px 0; background: #f1f5f9; padding: 6px; border-radius: 4px;">{order.notes}</td>
                </tr>
                ''' if order.notes else ''}
            </table>

            <h3 style="font-size: 15px; color: #334155; margin-bottom: 10px; border-bottom: 1px solid #cbd5e1; padding-bottom: 6px;">🛒 შეკვეთილი პროდუქცია</h3>
            <table style="width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 20px;">
                <thead>
                    <tr style="background: #f8fafc; color: #475569;">
                        <th style="padding: 8px; text-align: left; border-bottom: 2px solid #e2e8f0;">პროდუქტი</th>
                        <th style="padding: 8px; text-align: center; border-bottom: 2px solid #e2e8f0;">რაოდ.</th>
                        <th style="padding: 8px; text-align: right; border-bottom: 2px solid #e2e8f0;">ჯამი</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html_rows}
                </tbody>
            </table>

            <div style="text-align: right; font-size: 18px; font-weight: bold; color: #6366f1; padding: 12px 0; border-top: 2px solid #e2e8f0;">
                სულ გადასახდელი: {order.total_amount:.2f} GEL
            </div>
        </div>
    </body>
    </html>
    """

    await send_email_alert(
        subject=f"🚨 ახალი შეკვეთა #{order.order_number} - {order.total_amount:.2f} GEL",
        body=email_text,
        store_settings=store_settings,
        html_body=html_email
    )

async def notify_human_requested(customer_name: str, customer_id: int, store_settings: StoreSettings, bot_app=None):
    """Notifies admin that customer wants to talk to a human."""
    text = (
        f"🙋‍♂️ **მომხმარებელი ითხოვს ოპერატორს!**\n\n"
        f"👤 სახელი: {customer_name}\n"
        f"🆔 Telegram ID: `{customer_id}`\n\n"
        f"გადადით ადმინ-პანელის Live Chat-ში მომხმარებელთან სასაუბროდ."
    )
    admin_ids_str = store_settings.admin_telegram_ids or settings.ADMIN_TELEGRAM_IDS
    if bot_app and admin_ids_str:
        for aid in [a.strip() for a in admin_ids_str.split(",") if a.strip()]:
            try:
                await bot_app.bot.send_message(chat_id=int(aid), text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Failed to send human handoff alert to {aid}: {e}")

    await ws_manager.broadcast({
        "type": "human_handoff_requested",
        "customer_id": customer_id,
        "customer_name": customer_name
    })
