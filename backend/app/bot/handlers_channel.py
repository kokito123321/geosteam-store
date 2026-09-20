import logging
from telegram import Update
from telegram.ext import ContextTypes
from sqlalchemy import select
from backend.app.database import async_session_maker
from backend.app.models import Product, StoreSettings
from backend.app.ai.post_parser import parse_channel_post_content
from backend.app.services.notifications import ws_manager
from backend.app.config import settings

logger = logging.getLogger(__name__)

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Automatically triggered whenever a new post is published in the connected Telegram Channel.
    Parses product specs with Gemini and creates a product record in the database.
    """
    post = update.channel_post
    if not post:
        return

    post_text = post.text or post.caption or ""
    if not post_text.strip():
        logger.info("Channel post has no text/caption, skipping product auto-parser.")
        return

    # Extract photo if available
    photo_url = ""
    if post.photo:
        # Get highest resolution photo file_id
        photo_url = post.photo[-1].file_id

    # Construct post URL if channel has a username
    chat = post.chat
    channel_post_url = ""
    if chat.username:
        channel_post_url = f"https://t.me/{chat.username}/{post.message_id}"

    logger.info(f"Processing channel post {post.message_id} from {chat.title or chat.id}...")

    # Parse with Gemini
    parsed_data = await parse_channel_post_content(post_text)
    if not parsed_data or not parsed_data.get("name"):
        logger.info("Channel post does not appear to be a product or parsing returned no name.")
        return

    # Save to Database
    async with async_session_maker() as session:
        new_product = Product(
            name=parsed_data.get("name", "Vape Liquid"),
            description=parsed_data.get("description", post_text),
            price=float(parsed_data.get("price", 0.0)),
            volume_ml=int(parsed_data.get("volume_ml", 30)),
            color_type=parsed_data.get("color_type", "Salt Nicotine"),
            stock_quantity=int(parsed_data.get("stock_quantity", 10)),
            is_active=True,
            photo_url=photo_url,
            channel_post_url=channel_post_url,
            vg_pg_ratio=parsed_data.get("vg_pg_ratio", "50/50"),
            nicotine_mg=parsed_data.get("nicotine_mg", "20mg")
        )
        session.add(new_product)

        # Fetch admin IDs from settings
        res = await session.execute(select(StoreSettings).limit(1))
        store_settings = res.scalars().first()
        await session.commit()
        await session.refresh(new_product)

        # Notify Admin on Telegram
        admin_ids_str = (store_settings.admin_telegram_ids if store_settings else "") or settings.ADMIN_TELEGRAM_IDS
        if admin_ids_str:
            admin_ids = [aid.strip() for aid in admin_ids_str.split(",") if aid.strip()]
            alert_msg = (
                f"🎉 **ჩანელიდან ავტომატურად დაემატა ახალი პროდუქტი!**\n\n"
                f"🏷 **დასახელება:** {new_product.name}\n"
                f"💰 **ფასი:** {new_product.price:.2f} GEL\n"
                f"💧 **მოცულობა:** {new_product.volume_ml} ml\n"
                f"💨 **VG/PG:** {new_product.vg_pg_ratio}\n"
                f"🧪 **ნიკოტინი:** {new_product.nicotine_mg}\n"
                f"📦 **მარაგი:** {new_product.stock_quantity} ცალი\n"
                f"{f'🔗 [პოსტის ნახვა]({new_product.channel_post_url})' if new_product.channel_post_url else ''}\n\n"
                f"მონაცემების რედაქტირება ნებისმიერ დროს შეგიძლიათ ადმინ-პანელიდან."
            )
            for aid in admin_ids:
                try:
                    await context.bot.send_message(
                        chat_id=int(aid),
                        text=alert_msg,
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Failed to send channel auto-import alert to {aid}: {e}")

        # Broadcast WebSocket event to live dashboard
        await ws_manager.broadcast({
            "type": "product_added_from_channel",
            "product": {
                "id": new_product.id,
                "name": new_product.name,
                "price": new_product.price,
                "stock_quantity": new_product.stock_quantity
            }
        })
