import json
import logging
import random
import uuid
from pathlib import Path
from datetime import datetime
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from sqlalchemy import select
from backend.app.database import async_session_maker
from backend.app.models import Customer, Product, Order, ChatMessage, StoreSettings, BlacklistUser
from backend.app.ai.gemini_client import gemini_service
from backend.app.ai.prompts import build_system_prompt, GEOSTEAM_ABOUT_US_TEXT
from backend.app.services.notifications import notify_new_order, notify_human_requested, ws_manager
from backend.app.bot.keyboards import (
    get_main_keyboard,
    get_contact_request_keyboard,
    get_location_request_keyboard,
    get_delivery_inline_keyboard,
    get_payment_inline_keyboard,
    get_catalog_selection_keyboard,
    get_product_action_keyboard
)
from backend.app.config import settings

logger = logging.getLogger(__name__)

async def get_or_create_customer(user, session) -> Customer:
    """Retrieves or creates a Customer record in database."""
    res = await session.execute(select(Customer).where(Customer.telegram_id == user.id))
    customer = res.scalars().first()
    if not customer:
        customer = Customer(
            telegram_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            language_code=user.language_code or "ka",
            order_state="IDLE",
            temp_cart="{}"
        )
        session.add(customer)
        await session.commit()
        await session.refresh(customer)
    else:
        # Update activity
        customer.username = user.username or customer.username
        customer.first_name = user.first_name or customer.first_name
        customer.last_active = datetime.utcnow()
        await session.commit()
    return customer

async def handle_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Captures new subscribers joining the channel or chat and registers them as customers."""
    result = update.chat_member
    if not result:
        return
    user = result.new_chat_member.user
    if user and not user.is_bot:
        try:
            async with async_session_maker() as session:
                await get_or_create_customer(user, session)
                logger.info(f"Registered channel subscriber {user.id} (@{user.username or 'no_user'}) into Customer database")
        except Exception as e:
            logger.error(f"Error recording chat member update: {e}")

def is_user_admin(user_id: int, store_settings: StoreSettings) -> bool:
    admin_str = (store_settings.admin_telegram_ids if store_settings else "") or settings.ADMIN_TELEGRAM_IDS
    if not admin_str:
        return False
    admin_ids = [aid.strip() for aid in admin_str.split(",") if aid.strip()]
    return str(user_id) in admin_ids

def get_lan_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /admin command for authorized administrators."""
    user = update.effective_user
    async with async_session_maker() as session:
        res = await session.execute(select(StoreSettings).limit(1))
        st_settings = res.scalars().first()

    if not is_user_admin(user.id, st_settings):
        await update.message.reply_text("⛔ თქვენ არ გაქვთ ადმინისტრატორის უფლებები.")
        return

    lan_ip = get_lan_ip()
    port = settings.PORT or 8000
    mobile_url = f"http://{lan_ip}:{port}/admin"

    msg = (
        f"👑 **Geosteam მართვის პანელი (Admin Panel)**\n\n"
        f"📱 **მობილური წვდომა (Wi-Fi ქსელში):**\n"
        f"👉 `{mobile_url}`\n\n"
        f"💻 **ლოკალური ბმული (PC):**\n"
        f"👉 `http://localhost:{port}/admin`\n\n"
        f"🔐 **შესასვლელი მონაცემები:**\n"
        f"• მომხმარებელი: `admin`\n"
        f"• პაროლი: `admin123`\n\n"
        f"💡 ტელეფონით გასახსნელად, დარწმუნდით რომ თქვენი ტელეფონი ჩართულია იმავე Wi-Fi-ზე და გახსენით ბმული ბრაუზერში."
    )
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Admin Panel-ის გახსნა (LAN)", url=f"http://{lan_ip}:{port}/admin")]
    ])
    await update.message.reply_text(msg, reply_markup=kb, parse_mode="Markdown")

async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles /start command."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    async with async_session_maker() as session:
        customer = await get_or_create_customer(user, session)
        customer.order_state = "IDLE"
        customer.temp_cart = "{}"
        customer.bot_paused = False
        await session.commit()

        res = await session.execute(select(StoreSettings).limit(1))
        st_settings = res.scalars().first()

    welcome_text = (
        f"გაუმარჯოს, {user.first_name}! 💨\n\n"
        f"GeoSteam-ში ხარ! 🇬🇪💨\n"
        f"ჩვენთან დაგხვდება უმაღლესი ხარისხის პრემიუმ ვეიპ სითხეები და მოწყობილობები.\n\n"
        f"მომწერე რა გაინტერესებს — სითხეები, არომატები, ნიკოტინის დონე თუ მიწოდება, და სიამოვნებით დაგეხმარები!"
    )
    await update.message.reply_text(welcome_text, reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")

async def handle_show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays catalog of available products."""
    async with async_session_maker() as session:
        res = await session.execute(
            select(Product).where(Product.is_active == True).order_by(Product.name)
        )
        products = res.scalars().all()

    if not products:
        await update.message.reply_text(
            "ამჟამად კატალოგში პროდუქცია არ არის. გთხოვთ შეამოწმოთ მოგვიანებით.",
            parse_mode="Markdown"
        )
        return

    reply_text = "💨 **ჩვენი ხელმისაწვდომი ვეიპ სითხეები:**\n\n"
    for p in products:
        stock_badge = f"✅ მარაგშია ({p.stock_quantity})" if p.stock_quantity > 0 else "❌ ამოწურულია"
        reply_text += (
            f"🔹 **{p.name}**\n"
            f"   💰 ფასი: **{p.price:.2f} GEL** | მოცულობა: {p.volume_ml}ml\n"
            f"   🧪 ნიკოტინი: {p.nicotine_mg} | VG/PG: {p.vg_pg_ratio}\n"
            f"   📊 {stock_badge}\n"
        )
        if p.channel_post_url:
            reply_text += f"   📢 [პოსტი ჩანელში]({p.channel_post_url})\n"
        reply_text += "\n"

    reply_text += "აირჩიეთ პროდუქტი დეტალების სანახავად და შესაკვეთად 👇"
    kb = get_catalog_selection_keyboard(products)
    await update.message.reply_text(reply_text, reply_markup=kb, parse_mode="Markdown")

async def handle_store_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays store location and information."""
    async with async_session_maker() as session:
        res = await session.execute(select(StoreSettings).limit(1))
        st_settings = res.scalars().first()

    info_text = (
        f"ℹ️ **მაღაზიის ინფორმაცია:**\n\n"
        f"📍 **თვითგატანის მისამართი:** {st_settings.pickup_address}\n\n"
        f"🚚 **მიწოდების სერვისი:**\n"
        f"{'• კურიერით მიტანა თბილისში' if st_settings.delivery_courier_enabled else ''}\n"
        f"{'• თვითგატანა ჩვენი ლოკაციიდან' if st_settings.delivery_pickup_enabled else ''}\n"
        f"{'• ფოსტით რეგიონებში' if st_settings.delivery_mail_enabled else ''}\n\n"
        f"💳 **გადახდის მეთოდები:**\n"
        f"{'• ნაღდი ანგარიშსწორება ადგილზე' if st_settings.payment_cash_enabled else ''}\n"
        f"{f'• საბანკო გადარიცხვა ({st_settings.bank_name})' if st_settings.payment_bank_enabled else ''}\n\n"
        f"დამატებითი კითხვებისთვის შეგიძლიათ მომწეროთ ნებისმიერ დროს!"
    )
    await update.message.reply_text(info_text, parse_mode="Markdown")
    if st_settings.pickup_lat and st_settings.pickup_lng:
        try:
            await update.message.reply_location(
                latitude=st_settings.pickup_lat,
                longitude=st_settings.pickup_lng
            )
        except Exception as e:
            logger.debug(f"Could not send location map: {e}")

async def handle_request_operator(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles operator request (Human handoff)."""
    user = update.effective_user
    async with async_session_maker() as session:
        res = await session.execute(select(Customer).where(Customer.telegram_id == user.id))
        customer = res.scalars().first()
        if customer:
            customer.bot_paused = True
            await session.commit()

        res_s = await session.execute(select(StoreSettings).limit(1))
        st_settings = res_s.scalars().first()

    await notify_human_requested(
        customer_name=f"{user.first_name} (@{user.username})" if user.username else user.first_name,
        customer_id=user.id,
        store_settings=st_settings,
        bot_app=context.application
    )

    await update.message.reply_text(
        "👨‍💼 **თქვენი მოთხოვნა გადაეცა ჩვენს ოპერატორს.**\n\n"
        "ბოტის ავტომატური პასუხები დროებით შეჩერებულია ამ ჩატში. "
        "გთხოვთ დაწეროთ თქვენი შეკითხვა და ოპერატორი უმოკლეს დროში გიპასუხებთ პირადში!",
        parse_mode="Markdown"
    )

async def start_order_workflow(update: Update, context: ContextTypes.DEFAULT_TYPE, product_id: int = None):
    """Starts the interactive ordering flow."""
    user = update.effective_user
    async with async_session_maker() as session:
        customer = await get_or_create_customer(user, session)
        
        if customer.is_blacklisted:
            msg = "🚫 თქვენი ანგარიში შეზღუდულია ადმინისტრაციის მიერ. გთხოვთ დაუკავშირდეთ ოპერატორს."
            if update.callback_query:
                await update.callback_query.answer(msg, show_alert=True)
            else:
                await update.message.reply_text(msg)
            return
        
        if product_id:
            res_p = await session.execute(select(Product).where(Product.id == product_id))
            prod = res_p.scalars().first()
            if not prod or prod.stock_quantity <= 0:
                msg = "სამწუხაროდ ეს პროდუქტი ამჟამად მარაგში აღარ არის."
                if update.callback_query:
                    await update.callback_query.answer(msg, show_alert=True)
                else:
                    await update.message.reply_text(msg)
                return
            
            cart = {
                "product_id": prod.id,
                "name": prod.name,
                "price": prod.price,
                "nicotine_mg": prod.nicotine_mg,
                "vg_pg_ratio": prod.vg_pg_ratio,
                "quantity": 1
            }
            customer.temp_cart = json.dumps(cart)
            customer.order_state = "AWAITING_DELIVERY_CHOICE"
            await session.commit()

            res_s = await session.execute(select(StoreSettings).limit(1))
            st_settings = res_s.scalars().first()

            text = (
                f"🛒 **შეკვეთა:** {prod.name}\n"
                f"💰 ფასი: {prod.price:.2f} GEL | ნიკოტინი: {prod.nicotine_mg}\n\n"
                f"გთხოვთ აირჩიოთ მიწოდების სასურველი მეთოდი 👇"
            )
            kb = get_delivery_inline_keyboard(st_settings)
            if update.callback_query:
                await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
            else:
                await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
        else:
            # Show list of products to choose
            res = await session.execute(select(Product).where(Product.is_active == True, Product.stock_quantity > 0))
            prods = res.scalars().all()
            if not prods:
                msg = "ამ ეტაპზე მარაგში პროდუქცია არ არის."
                if update.callback_query:
                    await update.callback_query.answer(msg, show_alert=True)
                else:
                    await update.message.reply_text(msg)
                return

            text = "🛒 გთხოვთ აირჩიოთ პროდუქტი, რომლის შეკვეთაც გსურთ:"
            kb = get_catalog_selection_keyboard(prods)
            if update.callback_query:
                await update.callback_query.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
            else:
                await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline button clicks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user

    async with async_session_maker() as session:
        customer = await get_or_create_customer(user, session)
        res_s = await session.execute(select(StoreSettings).limit(1))
        st_settings = res_s.scalars().first()

        if data.startswith("view_prod_"):
            prod_id = int(data.split("_")[2])
            res_p = await session.execute(select(Product).where(Product.id == prod_id))
            prod = res_p.scalars().first()
            if prod:
                detail_text = (
                    f"💨 **{prod.name}**\n\n"
                    f"📝 {prod.description or 'მაღალი ხარისხის პრემიუმ სითხე.'}\n\n"
                    f"💰 ფასი: **{prod.price:.2f} GEL**\n"
                    f"💧 მოცულობა: **{prod.volume_ml} ml**\n"
                    f"🧪 ნიკოტინი: **{prod.nicotine_mg}**\n"
                    f"💨 VG/PG: **{prod.vg_pg_ratio}**\n"
                    f"📦 მარაგი: {'✅ მარაგშია' if prod.stock_quantity > 0 else '❌ ამოწურულია'}\n"
                )
                kb = get_product_action_keyboard(prod.id, prod.channel_post_url)
                if prod.photo_url:
                    try:
                        await query.message.reply_photo(photo=prod.photo_url, caption=detail_text, reply_markup=kb, parse_mode="Markdown")
                        return
                    except Exception as e:
                        logger.debug(f"Could not send photo: {e}")
                await query.message.reply_text(detail_text, reply_markup=kb, parse_mode="Markdown")

        elif data.startswith("buy_prod_"):
            prod_id = int(data.split("_")[2])
            await start_order_workflow(update, context, product_id=prod_id)

        elif data.startswith("delivery_"):
            method = data.replace("delivery_", "")
            cart = json.loads(customer.temp_cart or "{}")
            cart["delivery_method"] = method
            customer.temp_cart = json.dumps(cart)

            if method == "pickup":
                # Skip asking for customer location, go straight to phone
                customer.order_state = "AWAITING_PHONE"
                await session.commit()
                text = (
                    f"🏬 თქვენ აირჩიეთ **თვითგატანა**.\n"
                    f"📍 მაღაზიის მისამართი: **{st_settings.pickup_address}**\n\n"
                    f"გთხოვთ გაგვიზიაროთ თქვენი საკონტაქტო ნომერი ღილაკზე დაჭერით 👇"
                )
                await query.message.reply_text(text, reply_markup=get_contact_request_keyboard(), parse_mode="Markdown")
            else:
                customer.order_state = "AWAITING_LOCATION"
                await session.commit()
                text = (
                    "📍 გთხოვთ გამოგვიგზავნოთ თქვენი **მიწოდების ლოკაცია**.\n"
                    "შეგიძლიათ გამოიყენოთ ღილაკი '📍 GPS ლოკაციის გაზიარება' ან ჩაწეროთ მისამართი ტექსტურად 👇"
                )
                await query.message.reply_text(text, reply_markup=get_location_request_keyboard(), parse_mode="Markdown")

        elif data.startswith("payment_"):
            method = data.replace("payment_", "")
            cart = json.loads(customer.temp_cart or "{}")
            cart["payment_method"] = method
            customer.temp_cart = json.dumps(cart)
            await session.commit()

            # Finalize order creation
            await finalize_order(query.message, customer, cart, st_settings, context)

        elif data == "order_cancel":
            customer.order_state = "IDLE"
            customer.temp_cart = "{}"
            await session.commit()
            await query.message.reply_text("❌ შეკვეთის პროცესი გაუქმდა.")

        elif data == "back_to_menu":
            await query.message.reply_text("რით შემიძლია დაგეხმაროთ? მომწერეთ ნებისმიერი შეკითხვა 💨")

async def finalize_order(message_target, customer: Customer, cart: dict, st_settings: StoreSettings, context: ContextTypes.DEFAULT_TYPE):
    """Saves the completed order to DB and triggers alerts."""
    dm = cart.get("delivery_method", "tbilisi_yandex")
    center_fee = getattr(st_settings, 'delivery_regions_center_fee', 9.0) or 9.0
    village_fee = getattr(st_settings, 'delivery_regions_village_fee', 12.0) or 12.0

    delivery_fee = 0.0
    if dm in ("region_village", "delivery_region_village"):
        delivery_fee = village_fee
        formatted_dm = f"რეგიონი (სოფელი - {village_fee:.0f}₾)"
    elif dm in ("region_center", "delivery_region_center"):
        delivery_fee = center_fee
        formatted_dm = f"რეგიონი (ცენტრი - {center_fee:.0f}₾)"
    elif dm in ("pickup", "delivery_pickup"):
        delivery_fee = 0.0
        formatted_dm = "თვითგატანა (მაღაზიიდან)"
    else:
        delivery_fee = 0.0
        formatted_dm = "თბილისი (Yandex საკურიერო)"

    items_list = cart.get("items", [])
    subtotal = float(cart.get("subtotal", 0.0))
    total = subtotal + delivery_fee
    order_number = f"ORD-{random.randint(10000, 99999)}"

    # Create Order object
    new_order = Order(
        order_number=order_number,
        customer_telegram_id=customer.telegram_id,
        customer_name=f"{customer.first_name} {customer.last_name or ''}".strip(),
        customer_phone=cart.get("phone", ""),
        items_json=json.dumps(items_list),
        total_amount=total,
        delivery_method=formatted_dm,
        delivery_address=cart.get("delivery_address", "თბილისი"),
        payment_method=cart.get("payment_method", "cash"),
        payment_status="pending",
        order_status="new",
        notes=cart.get("notes", "")
    )

    async with async_session_maker() as session:
        session.add(new_order)
        # Deduct stock
        for it in items_list:
            res_p = await session.execute(select(Product).where(Product.id == it["product_id"]))
            p = res_p.scalars().first()
            if p:
                p.stock_quantity = max(0, p.stock_quantity - it.get("quantity", 1))

        # Reset customer ordering state
        res_c = await session.execute(select(Customer).where(Customer.telegram_id == customer.telegram_id))
        c_db = res_c.scalars().first()
        if c_db:
            if cart.get("payment_method") == "bank_transfer":
                c_db.order_state = f"AWAITING_RECEIPT_{new_order.id}"
            else:
                c_db.order_state = "IDLE"
            c_db.temp_cart = "{}"

        await session.commit()
        await session.refresh(new_order)

    # Dispatch alerts
    try:
        from backend.app.bot.bot_instance import bot_manager
        await notify_new_order(new_order, st_settings, bot_manager.bot_app)
    except Exception as e:
        logger.error(f"Error in notify_new_order: {e}", exc_info=True)

    # Broadcast event to Web Dashboard
    await ws_manager.broadcast({
        "type": "new_order",
        "order": {
            "id": new_order.id,
            "order_number": new_order.order_number,
            "customer_name": new_order.customer_name,
            "total_amount": new_order.total_amount,
            "status": new_order.order_status,
            "created_at": new_order.created_at.isoformat()
        }
    })

    # Confirmation text for customer
    payment_info = ""
    if new_order.payment_method == "bank_transfer":
        payment_info = (
            f"💳 **საბანკო რეკვიზიტები გადარიცხვისთვის:**\n"
            f"🏦 ბანკი: {st_settings.bank_name}\n"
            f"🔢 ანგარიში (IBAN): `{st_settings.bank_iban}`\n"
            f"👤 მიმღები: {st_settings.bank_recipient or 'Geosteam'}\n\n"
            f"📸 **გთხოვთ გადმოგვიგზავნოთ გადახდის ქვითარი (სქრინშოტი/ფოტო) აქ პირად ჩატში!**"
        )
    else:
        payment_info = "💵 გადახდა განხორციელდება ნაღდი ანგარიშსწორებით შეკვეთის მიღებისას."

    confirm_text = (
        f"🎉 **მადლობა! თქვენი შეკვეთა მიღებულია!**\n\n"
        f"📦 შეკვეთის ნომერი: **#{new_order.order_number}**\n"
        f"💰 ჯამური თანხა: **{total:.2f} GEL**\n"
        f"📞 საკონტაქტო: {new_order.customer_phone}\n"
        f"🚚 მიწოდება: {new_order.delivery_method}\n"
        f"{payment_info}\n"
        f"ჩვენი მენეჯერი მალე დაგიკავშირდებათ დეტალების დასაზუსტებლად! ❤️"
    )

    await message_target.reply_text(
        confirm_text,
        parse_mode="Markdown"
    )

async def handle_text_or_multimedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler for text, location, contact, and AI conversations."""
    message = update.message
    if not message:
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    text = message.text or ""

    async with async_session_maker() as session:
        customer = await get_or_create_customer(user, session)
        res_s = await session.execute(select(StoreSettings).limit(1))
        st_settings = res_s.scalars().first()

        # Check if customer is blacklisted
        if customer.is_blacklisted:
            if text == "🙋‍♂️ ოპერატორი":
                await handle_request_operator(update, context)
                return
            await message.reply_text(
                "🚫 **თქვენი ანგარიში შეზღუდულია ადმინისტრაციის მიერ.**\n\n"
                "დაფიქსირებულია შეუსაბამო ან საეჭვო ქვითარი. "
                "გასარკვევად დაუკავშირდით ოპერატორს ღილაკით: 🙋‍♂️ ოპერატორი.",
                parse_mode="Markdown"
            )
            return

        # Handle persistent menu button texts
        if text == "📦 კატალოგი":
            customer.bot_paused = False
            await session.commit()
            await handle_show_catalog(update, context)
            return
        elif text == "🛒 შეკვეთის გაფორმება":
            customer.bot_paused = False
            await session.commit()
            await start_order_workflow(update, context)
            return
        elif text == "ℹ️ მაღაზია & ლოკაცია":
            customer.bot_paused = False
            await session.commit()
            await handle_store_info(update, context)
            return
        elif text == "🇬🇪 ჩვენს შესახებ" or "ჩვენს შესახებ" in text.lower() or "ვინ ხართ" in text.lower():
            customer.bot_paused = False
            await session.commit()
            await message.reply_text(GEOSTEAM_ABOUT_US_TEXT, parse_mode="Markdown")
            return
        elif text == "🙋‍♂️ ოპერატორი":
            await handle_request_operator(update, context)
            return
        elif text == "❌ შეკვეთის გაუქმება":
            customer.order_state = "IDLE"
            customer.temp_cart = "{}"
            await session.commit()
            await message.reply_text("შეკვეთა გაუქმებულია.")
            return

        # Handle FSM state for ordering
        state = customer.order_state
        if state == "AWAITING_LOCATION":
            cart = json.loads(customer.temp_cart or "{}")
            if message.location:
                cart["location_lat"] = message.location.latitude
                cart["location_lng"] = message.location.longitude
                cart["delivery_address"] = f"GPS: {message.location.latitude:.4f}, {message.location.longitude:.4f}"
            else:
                cart["delivery_address"] = text

            customer.temp_cart = json.dumps(cart)
            customer.order_state = "AWAITING_PHONE"
            await session.commit()

            prompt_msg = (
                "📱 გთხოვთ გაგვიზიაროთ თქვენი **ტელეფონის ნომერი** კურიერის დასაკავშირებლად.\n\n"
                "თუ გსურთ ტელეგრამის ნომრის გაზიარება, დააჭირეთ '📱 ტელეგრამის ნომრის გაზიარება' ღილაკს. "
                "თუ გსურთ სხვა ნომერზე დაგვიკავშირდეთ, უბრალოდ მოგვწერეთ ნომერი ტექსტურად 👇"
            )
            await message.reply_text(prompt_msg, reply_markup=get_contact_request_keyboard(), parse_mode="Markdown")
            return

        elif state == "AWAITING_PHONE":
            cart = json.loads(customer.temp_cart or "{}")
            phone_num = ""
            if message.contact:
                phone_num = message.contact.phone_number
            elif text and not text.startswith("✍️"):
                phone_num = text

            if phone_num:
                customer.phone_number = phone_num
                cart["phone"] = phone_num
                customer.temp_cart = json.dumps(cart)
                customer.order_state = "AWAITING_PAYMENT_CHOICE"
                await session.commit()

                pay_text = (
                    f"📞 ნომერი ჩაწერილია: `{phone_num}`\n\n"
                    f"გთხოვთ აირჩიოთ **გადახდის მეთოდი** 👇"
                )
                await message.reply_text(pay_text, reply_markup=get_payment_inline_keyboard(st_settings), parse_mode="Markdown")
                return
            else:
                await message.reply_text("გთხოვთ მოგვწეროთ თქვენი მობილურის ნომერი (მაგ: 599123456):")
                return

        # Check if user sent a photo / receipt
        uploaded_media_url = ""
        if message.photo:
            photo = message.photo[-1]
            try:
                receipts_dir = Path("frontend/static/uploads/receipts")
                receipts_dir.mkdir(parents=True, exist_ok=True)
                fn = f"photo_{user.id}_{uuid.uuid4().hex[:8]}.jpg"
                fp = receipts_dir / fn
                file_obj = await context.bot.get_file(photo.file_id)
                await file_obj.download_to_drive(custom_path=str(fp))
                uploaded_media_url = f"/static/uploads/receipts/{fn}"
            except Exception as ex:
                logger.error(f"Error downloading photo: {ex}")

            target_order = None
            if customer.order_state and customer.order_state.startswith("AWAITING_RECEIPT_"):
                try:
                    order_id = int(customer.order_state.split("_")[-1])
                    res_ord = await session.execute(select(Order).where(Order.id == order_id))
                    target_order = res_ord.scalars().first()
                except Exception:
                    pass

            if not target_order:
                # Check recent pending bank transfer order for this customer
                res_ord = await session.execute(
                    select(Order)
                    .where(Order.customer_telegram_id == user.id)
                    .order_by(Order.id.desc())
                    .limit(1)
                )
                target_order = res_ord.scalars().first()

            if target_order and uploaded_media_url:
                try:
                    target_order.receipt_image_url = uploaded_media_url
                    target_order.receipt_file_id = photo.file_id
                    customer.order_state = "IDLE"

                    chat_msg = ChatMessage(
                        customer_telegram_id=user.id,
                        sender="user",
                        message_text=text or f"🧾 გადარიცხვის ქვითარი შეკვეთაზე #{target_order.order_number}",
                        media_url=uploaded_media_url
                    )
                    session.add(chat_msg)
                    await session.commit()

                    # Execute Gemini Multimodal Vision Verification
                    expected_iban = st_settings.bank_iban if st_settings else ""
                    expected_amount = float(target_order.total_amount)
                    expected_recip = st_settings.bank_recipient if st_settings else "Geosteam"

                    with open(fp, "rb") as rf_bytes:
                        raw_bytes = rf_bytes.read()

                    vision_res = await gemini_service.verify_receipt_image(
                        image_bytes=raw_bytes,
                        mime_type="image/jpeg",
                        expected_iban=expected_iban,
                        expected_amount=expected_amount,
                        expected_recipient=expected_recip
                    )

                    logger.info(f"Vision receipt verification for #{target_order.order_number}: {vision_res}")
                    is_verified = vision_res.get("is_match", True)
                    customer_display = f"{user.first_name} (@{user.username})" if user.username else user.first_name

                    if is_verified:
                        target_order.payment_status = "verified"
                        await session.commit()

                        await message.reply_text(
                            f"✅ **ქვითარი წარმატებით დამოწმდა AI-ის მიერ!**\n\n"
                            f"🔖 შეკვეთის ნომერი: `{target_order.order_number}`\n"
                            f"💰 დადასტურებული თანხა: **{vision_res.get('extracted_amount', expected_amount):.2f} GEL**\n"
                            f"🏦 მიმღები ანგარიში: `{vision_res.get('extracted_iban', expected_iban)}`\n\n"
                            f"შეკვეთა გადავიდა მზადების ეტაპზე. მადლობა Geosteam-ის არჩევისთვის! ❤️",
                            parse_mode="Markdown"
                        )

                        await ws_manager.broadcast({
                            "type": "receipt_verified",
                            "order_id": target_order.id,
                            "order_number": target_order.order_number,
                            "receipt_url": target_order.receipt_image_url,
                            "extracted_amount": vision_res.get("extracted_amount", expected_amount),
                            "extracted_iban": vision_res.get("extracted_iban", expected_iban)
                        })
                    else:
                        # Fraud / Mismatch detected -> Auto-Add to Blacklist
                        mismatch_reason = vision_res.get("reason", "არასწორი ანგარიში ან თანხის შეუსაბამობა")
                        target_order.payment_status = "fraud_suspected"
                        customer.is_blacklisted = True

                        res_bl = await session.execute(select(BlacklistUser).where(BlacklistUser.telegram_id == user.id))
                        existing_bl = res_bl.scalars().first()
                        if not existing_bl:
                            bl_entry = BlacklistUser(
                                telegram_id=user.id,
                                username=user.username or "",
                                full_name=customer_display,
                                reason=f"ქვითრის შეუსაბამობა #{target_order.order_number}: {mismatch_reason}",
                                receipt_url=uploaded_media_url
                            )
                            session.add(bl_entry)

                        await session.commit()

                        # Broadcast fraud alert to Admin Panel
                        await ws_manager.broadcast({
                            "type": "receipt_fraud_alert",
                            "customer_id": user.id,
                            "customer_name": customer_display,
                            "order_number": target_order.order_number,
                            "extracted_amount": vision_res.get("extracted_amount", 0.0),
                            "expected_amount": expected_amount,
                            "extracted_iban": vision_res.get("extracted_iban", ""),
                            "expected_iban": expected_iban,
                            "reason": mismatch_reason,
                            "receipt_url": uploaded_media_url
                        })

                        # Notify Admins via Telegram
                        admin_alert_text = (
                            f"🚨 **ყურადღება: ყალბი / შეუსაბამო ქვითარი!**\n\n"
                            f"👤 მომხმარებელი: {customer_display} (ID: `{user.id}`)\n"
                            f"🔖 შეკვეთა: `#{target_order.order_number}`\n"
                            f"💰 მოსალოდნელი: **{expected_amount:.2f} GEL** | IBAN: `{expected_iban}`\n"
                            f"❌ ქვითარზე: **{vision_res.get('extracted_amount', 0.0):.2f} GEL** | IBAN: `{vision_res.get('extracted_iban', 'N/A')}`\n"
                            f"📝 AI დასკვნა: {mismatch_reason}\n\n"
                            f"🚫 **მომხმარებელი ავტომატურად დაემატა Black List-ში!**"
                        )
                        if st_settings and st_settings.admin_telegram_ids:
                            admin_ids = [aid.strip() for aid in st_settings.admin_telegram_ids.split(",") if aid.strip().isdigit()]
                            for aid in admin_ids:
                                try:
                                    await context.bot.send_message(chat_id=int(aid), text=admin_alert_text, parse_mode="Markdown")
                                except Exception:
                                    pass

                        await message.reply_text(
                            f"⚠️ **ქვითრის გადამოწმების შეცდომა!**\n\n"
                            f"AI სისტემამ ქვითარში დააფიქსირა შეუსაბამობა:\n"
                            f"• {mismatch_reason}\n\n"
                            f"თუ შეცდომით გამოგზავნეთ არასწორი ქვითარი ან გსურთ გარკვევა, გთხოვთ დაუკავშირდეთ ოპერატორს ღილაკით: 🙋‍♂️ ოპერატორი.",
                            parse_mode="Markdown"
                        )

                    await ws_manager.broadcast({
                        "type": "receipt_uploaded",
                        "order_id": target_order.id,
                        "order_number": target_order.order_number,
                        "receipt_url": target_order.receipt_image_url
                    })

                    await ws_manager.broadcast({
                        "type": "new_chat_message",
                        "message": {
                            "customer_id": user.id,
                            "customer_name": f"{user.first_name} (@{user.username})" if user.username else user.first_name,
                            "sender": "user",
                            "text": chat_msg.message_text,
                            "media_url": uploaded_media_url,
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    })

                    # Notify Admin with Photo
                    if st_settings and st_settings.admin_telegram_ids:
                        admin_ids = [aid.strip() for aid in st_settings.admin_telegram_ids.split(",") if aid.strip().isdigit()]
                        for aid in admin_ids:
                            try:
                                with open(fp, "rb") as rf:
                                    await context.bot.send_photo(
                                        chat_id=int(aid),
                                        photo=rf,
                                        caption=(
                                            f"🧾 **ახალი ქვითარი შეკვეთაზე #{target_order.order_number}!**\n"
                                            f"👤 მომხმარებელი: {target_order.customer_name} ({target_order.customer_phone})\n"
                                            f"💰 თანხა: {target_order.total_amount:.2f} GEL\n"
                                            f"🚚 მიწოდება: {target_order.delivery_method}"
                                        ),
                                        parse_mode="Markdown"
                                    )
                            except Exception as e:
                                logger.error(f"Failed to forward receipt photo to admin {aid}: {e}")
                    return
                except Exception as ex:
                    logger.error(f"Error saving receipt photo: {ex}", exc_info=True)
                    await message.reply_text("ქვითრის დამუშავებისას დაფიქსირდა შეცდომა, გთხოვთ სცადოთ თავიდან.")
                    return

        # Record incoming message in chat history
        chat_msg = ChatMessage(
            customer_telegram_id=user.id,
            sender="user",
            message_text=text or ("[ფოტო]" if uploaded_media_url else "[მედია / ფაილი]"),
            media_url=uploaded_media_url or ""
        )
        session.add(chat_msg)
        await session.commit()

        # Broadcast live message to Admin Dashboard
        await ws_manager.broadcast({
            "type": "new_chat_message",
            "message": {
                "customer_id": user.id,
                "customer_name": f"{user.first_name} (@{user.username})" if user.username else user.first_name,
                "sender": "user",
                "text": chat_msg.message_text,
                "media_url": uploaded_media_url or "",
                "timestamp": datetime.utcnow().isoformat()
            }
        })

        # Check Human Handoff (if bot is paused for this customer)
        if customer.bot_paused:
            logger.info(f"Bot is paused for customer {user.id}. Message logged for admin operator.")
            if text.strip().lower() in ["/unpause", "/bot", "/start", "ბოტი", "დაბრუნება", "bot"]:
                customer.bot_paused = False
                await session.commit()
                await message.reply_text("🤖 **ბოტი კვლავ აქტიურია!** რით დაგეხმარო? 💨", parse_mode="Markdown")
                return
            return

        # If bot is active: Generate response using Gemini 3.8 Flash!
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        # Fetch recent products and prompt
        res_prod = await session.execute(select(Product))
        products = res_prod.scalars().all()

        system_prompt = build_system_prompt(st_settings, products)

        # Fetch recent 6 messages for context
        res_hist = await session.execute(
            select(ChatMessage)
            .where(ChatMessage.customer_telegram_id == user.id)
            .order_by(ChatMessage.id.desc())
            .limit(6)
        )
        history_msgs = list(reversed(res_hist.scalars().all()))
        history_formatted = [
            {"sender": m.sender, "text": m.message_text}
            for m in history_msgs
        ]

        cust_name = f"{user.first_name} {user.last_name or ''}".strip() or f"@{user.username}"
        # Call Gemini with customer context
        ai_reply = await gemini_service.get_response(
            user_message=text,
            system_instruction=system_prompt,
            history=history_formatted,
            customer_context={
                "telegram_id": user.id,
                "name": cust_name,
                "phone": customer.phone_number or ""
            }
        )

        # Save AI reply
        ai_chat_msg = ChatMessage(
            customer_telegram_id=user.id,
            sender="ai",
            message_text=ai_reply
        )
        session.add(ai_chat_msg)
        await session.commit()

        # Broadcast AI reply to dashboard
        await ws_manager.broadcast({
            "type": "new_chat_message",
            "message": {
                "customer_id": user.id,
                "customer_name": "AI Assistant",
                "sender": "ai",
                "text": ai_reply,
                "timestamp": datetime.utcnow().isoformat()
            }
        })

        # Send response to customer safely
        try:
            if len(ai_reply) > 4000:
                chunks = [ai_reply[i:i+4000] for i in range(0, len(ai_reply), 4000)]
                for chunk in chunks:
                    await message.reply_text(chunk, parse_mode="Markdown")
            else:
                await message.reply_text(ai_reply, parse_mode="Markdown")
        except Exception as send_err:
            logger.warning(f"Failed to send Markdown message, retrying plain text: {send_err}")
            if len(ai_reply) > 4000:
                chunks = [ai_reply[i:i+4000] for i in range(0, len(ai_reply), 4000)]
                for chunk in chunks:
                    await message.reply_text(chunk)
            else:
                await message.reply_text(ai_reply)
