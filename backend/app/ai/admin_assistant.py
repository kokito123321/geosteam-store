import os
import json
import logging
import contextvars
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, func, or_
from google import genai
from google.genai import types

from backend.app.config import settings
from backend.app.database import async_session_maker
from backend.app.models import (
    Product, Order, StoreSettings, Customer, ChatMessage, ScheduledPost, AdminAssistantMessage
)
from backend.app.services.notifications import ws_manager

logger = logging.getLogger(__name__)

_current_actions: contextvars.ContextVar[List[Dict[str, Any]]] = contextvars.ContextVar("_current_actions", default=[])

def _record_action(tool_name: str, args: dict, result: Any):
    try:
        acts = _current_actions.get()
        acts.append({"tool": tool_name, "args": args, "result": result})
    except Exception:
        pass

ADMIN_COPILOT_SYSTEM_PROMPT = """შენ ხარ Geosteam-ის ადმინ პანელის სრულუფლებიანი, ჭკვიანი AI ასისტენტი (Admin Copilot / Operations & UI Controller).
შენი მისიაა დაეხმარო მაღაზიის მფლობელსა და ადმინისტრატორს ნებისმიერი საოპერაციო საქმის შესრულებაში, მონაცემების მართვასა და ადმინ პანელის მართვაში.

გაქვს წვდომა როგორც ბაზის მართვის, ისე ადმინ პანელის ინტერფეისის (UI) რეალურ დროში მართვის ხელსაწყოებზე:

🖥️ ინტერფეისის (UI) მართვის ხელსაწყოები:
1. navigate_to_tab: ეკრანზე კონკრეტულ განყოფილებაში გადასვლა/გახსნა. შესაძლო განყოფილებებია:
   - "overview" (მიმოხილვა / Dashboard)
   - "products" (პროდუქცია და მარაგები)
   - "orders" (შეკვეთები და ქვითრები)
   - "livechat" (Live Chat მომხმარებლებთან)
   - "channel_posts" (ჩანელის პოსტები & განრიგი)
   - "gemini_config" (AI & Gemini პარამეტრები)
   - "marketing" (მარკეტინგი & Broadcast შეტყობინებები)
   - "settings" (მაღაზიის პარამეტრები და რეკვიზიტები)
2. fill_form_field: ადმინ პანელის ნებისმიერი ველის შევსება ტექსტით/მონაცემით (მაგ: პოსტის მონახაზი, ფოტოს URL, შეტყობინების ტექსტი).
3. open_modal: მოდალური ფანჯრის გახსნა (მაგ: "productModal" ახალი პროდუქტის დასამატებლად).

📦 ბაზისა და მონაცემების მართვის ხელსაწყოები:
4. get_store_metrics: ანალიტიკა (შემოსავალი, შეკვეთების რაოდენობა, აქტიური პროდუქტები, გადაუმოწმებელი ქვითრები).
5. list_products: პროდუქტების ძებნა და მარაგების ნახვა.
6. update_product: პროდუქტის ფასის, მარაგის რაოდენობის ან სტატუსის განახლება.
7. add_new_product: ახალი ვეიპის სითხის ან პროდუქტის დამატება კატალოგში.
8. list_orders: ბოლო შეკვეთების ნახვა და ფილტრაცია სტატუსით (new, processing, delivered, cancelled).
9. update_order_status: შეკვეთის სტატუსის შეცვლა (მაგ: მომზადებაზე გადაყვანა, ჩაბარებულად მონიშვნა).
10. schedule_channel_post: ტელეგრამ ჩანელში (@Geosteamforeveryone) მარკეტინგული პოსტის შექმნა და დაგეგმვა/გამოქვეყნება.
11. update_store_settings: მაღაზიის ნებისმიერი პარამეტრის (საბანკო რეკვიზიტები, თვითგატანის მისამართი, მიწოდების მეთოდები, AI პრომპტი) შეცვლა.

წესები:
- უპასუხე ყოველთვის ქართულად, საქმიანი, თავაზიანი და ეფექტური ტონით.
- თუ ადმინისტრატორი გთხოვს: "გადადი შეკვეთებში", "გახსენი პროდუქტები", "ჩაწერე პოსტი" - გამოიყენე შესაბამისი navigate_to_tab / fill_form_field ფუნქცია!
- თუ გთხოვს პარამეტრების შეცვლას, გამოიყენე update_store_settings და navigate_to_tab("settings").
- ყოველთვის აუხსენი რა მოქმედება შეასრულე.
"""

# ------------------ Tool Implementations (Module-Level Functions) ------------------

async def navigate_to_tab(tab_name: str) -> Dict[str, Any]:
    """გადადის ადმინ პანელის მითითებულ ჩანართზე (overview, products, orders, livechat, channel_posts, gemini_config, marketing, settings)."""
    tab_clean = tab_name.strip().lower().replace(" ", "_")
    
    if "შეკვეთ" in tab_clean or "order" in tab_clean:
        tab_clean = "orders"
    elif "პროდუქტ" in tab_clean or "მარაგ" in tab_clean or "product" in tab_clean:
        tab_clean = "products"
    elif "ჩატ" in tab_clean or "live" in tab_clean or "მესიჯ" in tab_clean:
        tab_clean = "livechat"
    elif "პოსტ" in tab_clean or "ჩანელ" in tab_clean or "post" in tab_clean or "channel" in tab_clean:
        tab_clean = "channel_posts"
    elif "gemini" in tab_clean or "ai" in tab_clean:
        tab_clean = "gemini_config"
    elif "მარკეტინგ" in tab_clean or "ბროადკასტ" in tab_clean or "broadcast" in tab_clean:
        tab_clean = "marketing"
    elif "პარამეტრ" in tab_clean or "რეკვიზიტ" in tab_clean or "setting" in tab_clean:
        tab_clean = "settings"
    elif "მიმოხილვ" in tab_clean or "მთავარ" in tab_clean or "overview" in tab_clean:
        tab_clean = "overview"

    res_data = {"success": True, "action": "navigate_to_tab", "tab": tab_clean}
    _record_action("navigate_to_tab", {"tab_name": tab_name}, res_data)
    return res_data

async def fill_form_field(field_name: str, value: str) -> Dict[str, Any]:
    """ავსებს ადმინ პანელის ფორმის ველს მითითებული მნიშვნელობით."""
    res_data = {"success": True, "action": "fill_form_field", "field": field_name, "value": value}
    _record_action("fill_form_field", {"field_name": field_name, "value": value}, res_data)
    return res_data

async def open_modal(modal_name: str) -> Dict[str, Any]:
    """ხსნის მითითებულ მოდალურ ფანჯარას (მაგ: productModal, receiptModal)."""
    res_data = {"success": True, "action": "open_modal", "modal": modal_name}
    _record_action("open_modal", {"modal_name": modal_name}, res_data)
    return res_data

async def get_store_metrics() -> Dict[str, Any]:
    """აბრუნებს მაღაზიის მიმდინარე მეტრიკებს: შემოსავალი, შეკვეთები, პროდუქტები, ქვითრები."""
    async with async_session_maker() as session:
        res_rev = await session.execute(
            select(func.sum(Order.total_amount)).where(Order.order_status != "cancelled")
        )
        total_revenue = res_rev.scalar() or 0.0

        res_ord_cnt = await session.execute(select(func.count(Order.id)))
        total_orders = res_ord_cnt.scalar() or 0

        res_prod_cnt = await session.execute(select(func.count(Product.id)).where(Product.is_active == True))
        active_products = res_prod_cnt.scalar() or 0

        res_low = await session.execute(
            select(Product).where(Product.is_active == True, Product.stock_quantity < 5)
        )
        low_stock = [{"name": p.name, "stock": p.stock_quantity} for p in res_low.scalars().all()]

        res_pending = await session.execute(
            select(Order).where(
                Order.payment_method == "bank_transfer",
                Order.payment_status == "pending",
                Order.receipt_image_url != ""
            )
        )
        receipts_to_review = [
            {"order_number": o.order_number, "customer": o.customer_name, "amount": o.total_amount}
            for o in res_pending.scalars().all()
        ]

        res_data = {
            "total_revenue_gel": round(total_revenue, 2),
            "total_orders": total_orders,
            "active_products_count": active_products,
            "low_stock_products": low_stock,
            "pending_receipts_count": len(receipts_to_review),
            "receipts_to_review": receipts_to_review
        }
        _record_action("get_store_metrics", {}, res_data)
        return res_data

async def list_products(query: str = "") -> List[Dict[str, Any]]:
    """პროდუქტების კატალოგის და მარაგების ნახვა/ძიება."""
    async with async_session_maker() as session:
        stmt = select(Product)
        if query and query.strip():
            stmt = stmt.where(Product.name.ilike(f"%{query.strip()}%"))
        res = await session.execute(stmt)
        products = res.scalars().all()
        res_list = [
            {
                "id": p.id,
                "name": p.name,
                "price": p.price,
                "stock": p.stock_quantity,
                "volume_ml": p.volume_ml,
                "nicotine": p.nicotine_mg,
                "vg_pg": p.vg_pg_ratio,
                "is_active": p.is_active
            }
            for p in products
        ]
        _record_action("list_products", {"query": query}, res_list)
        return res_list

async def update_product(
    product_id: Optional[int] = None,
    product_name: Optional[str] = None,
    price: Optional[float] = None,
    stock: Optional[int] = None,
    is_active: Optional[bool] = None
) -> Dict[str, Any]:
    """პროდუქტის ფასის, მარაგის რაოდენობის ან სტატუსის განახლება."""
    async with async_session_maker() as session:
        prod = None
        if product_id:
            res = await session.execute(select(Product).where(Product.id == product_id))
            prod = res.scalars().first()
        elif product_name:
            res = await session.execute(select(Product).where(Product.name.ilike(f"%{product_name.strip()}%")))
            prod = res.scalars().first()

        if not prod:
            err_dict = {"success": False, "error": f"პროდუქტი ვერ მოიძებნა (ID: {product_id}, Name: {product_name})"}
            _record_action("update_product", {"product_id": product_id, "product_name": product_name}, err_dict)
            return err_dict

        changes = []
        if price is not None:
            old_p = prod.price
            prod.price = float(price)
            changes.append(f"ფასი: {old_p} -> {prod.price} GEL")
        if stock is not None:
            old_s = prod.stock_quantity
            prod.stock_quantity = int(stock)
            changes.append(f"მარაგი: {old_s} -> {prod.stock_quantity} ცალი")
        if is_active is not None:
            prod.is_active = bool(is_active)
            changes.append(f"სტატუსი: {'აქტიური' if prod.is_active else 'გამორთული'}")

        await session.commit()
        await session.refresh(prod)

        await ws_manager.broadcast({
            "type": "product_updated",
            "product_id": prod.id,
            "name": prod.name,
            "price": prod.price,
            "stock": prod.stock_quantity
        })

        res_dict = {
            "success": True,
            "product_id": prod.id,
            "product_name": prod.name,
            "changes": changes,
            "current_price": prod.price,
            "current_stock": prod.stock_quantity
        }
        _record_action("update_product", {"product_id": product_id, "product_name": product_name}, res_dict)
        return res_dict

async def add_new_product(
    name: str,
    price: float,
    stock: int = 10,
    volume_ml: int = 30,
    nicotine_mg: str = "20mg",
    vg_pg_ratio: str = "50/50",
    description: str = "",
    photo_url: str = ""
) -> Dict[str, Any]:
    """ახალი პროდუქტის დამატება კატალოგში."""
    async with async_session_maker() as session:
        new_prod = Product(
            name=name.strip(),
            price=float(price),
            stock_quantity=int(stock),
            volume_ml=int(volume_ml),
            nicotine_mg=nicotine_mg.strip() if nicotine_mg else "20mg",
            vg_pg_ratio=vg_pg_ratio.strip() if vg_pg_ratio else "50/50",
            description=description.strip() if description else "პრემიუმ ხარისხის სითხე.",
            photo_url=photo_url.strip() if photo_url else "",
            is_active=True
        )
        session.add(new_prod)
        await session.commit()
        await session.refresh(new_prod)

        await ws_manager.broadcast({
            "type": "product_created",
            "product_id": new_prod.id,
            "name": new_prod.name,
            "price": new_prod.price,
            "stock": new_prod.stock_quantity
        })

        res_dict = {
            "success": True,
            "product_id": new_prod.id,
            "name": new_prod.name,
            "price": new_prod.price,
            "stock": new_prod.stock_quantity
        }
        _record_action("add_new_product", {"name": name, "price": price}, res_dict)
        return res_dict

async def list_orders(status: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    """შეკვეთების სიის ნახვა."""
    async with async_session_maker() as session:
        stmt = select(Order).order_by(Order.id.desc()).limit(limit)
        if status and status.strip():
            stmt = select(Order).where(Order.order_status == status.strip()).order_by(Order.id.desc()).limit(limit)
        res = await session.execute(stmt)
        orders = res.scalars().all()

        res_list = []
        for o in orders:
            items = []
            try:
                items = json.loads(o.items_json)
            except Exception:
                pass
            res_list.append({
                "id": o.id,
                "order_number": o.order_number,
                "customer_name": o.customer_name,
                "phone": o.customer_phone,
                "total_amount": o.total_amount,
                "order_status": o.order_status,
                "payment_method": o.payment_method,
                "payment_status": o.payment_status,
                "has_receipt": bool(o.receipt_image_url),
                "items": items
            })
        _record_action("list_orders", {"status": status, "limit": limit}, res_list)
        return res_list

async def update_order_status(order_id: int, new_status: str) -> Dict[str, Any]:
    """შეკვეთის სტატუსის განახლება (new, processing, delivered, cancelled)."""
    async with async_session_maker() as session:
        res = await session.execute(select(Order).where(Order.id == order_id))
        order = res.scalars().first()
        if not order:
            err_dict = {"success": False, "error": f"შეკვეთა ID {order_id} ვერ მოიძებნა"}
            _record_action("update_order_status", {"order_id": order_id, "new_status": new_status}, err_dict)
            return err_dict

        old_status = order.order_status
        order.order_status = new_status.strip().lower()
        if new_status == "delivered" and order.payment_status != "paid":
            order.payment_status = "paid"

        await session.commit()

        await ws_manager.broadcast({
            "type": "order_status_updated",
            "order_id": order.id,
            "order_number": order.order_number,
            "status": order.order_status,
            "payment_status": order.payment_status
        })

        res_dict = {
            "success": True,
            "order_id": order.id,
            "order_number": order.order_number,
            "old_status": old_status,
            "new_status": order.order_status
        }
        _record_action("update_order_status", {"order_id": order_id, "new_status": new_status}, res_dict)
        return res_dict

async def schedule_channel_post(
    notes: str,
    photo_url: str = "",
    post_now: bool = False,
    schedule_minutes: int = 0,
    schedule_time_georgia: str = ""
) -> Dict[str, Any]:
    """
    ტელეგრამ არხში (@Geosteamforeveryone) მარკეტინგული პოსტის გენერირება და დაგეგმვა/გამოქვეყნება საქართველოს ზუსტი დროით (UTC+4).
    - notes: პროდუქტის მოკლე ინფორმაცია ან ტექსტი
    - photo_url: ფოტოს URL (არასავალდებულო)
    - post_now: თუ true-ა, დაუყოვნებლივ გამოქვეყნდება
    - schedule_minutes: რამდენ წუთში გამოქვეყნდეს (მაგ: 30, 60)
    - schedule_time_georgia: საქართველოს დრო (მაგ: "18:00", "2026-09-17 18:30", "ხვალ 15:00")
    """
    from backend.app.ai.gemini_client import gemini_service
    from datetime import timedelta

    post_text = await gemini_service.generate_channel_post(notes, photo_url if photo_url else None)
    if not post_text:
        post_text = notes

    now_utc = datetime.utcnow()
    now_georgia = now_utc + timedelta(hours=4)
    sched_dt_utc = None
    georgia_display = ""
    status = "draft"

    if post_now:
        sched_dt_utc = now_utc
        status = "scheduled"
        georgia_display = "დაუყოვნებლივ (ეხლავე)"
    elif schedule_minutes > 0:
        sched_dt_utc = now_utc + timedelta(minutes=schedule_minutes)
        status = "scheduled"
        target_geo = now_georgia + timedelta(minutes=schedule_minutes)
        georgia_display = target_geo.strftime("%Y-%m-%d %H:%M") + " (საქართველოს დრო)"
    elif schedule_time_georgia:
        st_clean = schedule_time_georgia.strip()
        try:
            if len(st_clean) == 5 and ":" in st_clean:
                h, m = map(int, st_clean.split(":"))
                target_geo = now_georgia.replace(hour=h, minute=m, second=0, microsecond=0)
                if target_geo <= now_georgia:
                    target_geo += timedelta(days=1)
                sched_dt_utc = target_geo - timedelta(hours=4)
                status = "scheduled"
                georgia_display = target_geo.strftime("%Y-%m-%d %H:%M") + " (საქართველოს დრო)"
            else:
                clean_dt_str = st_clean.replace("Z", "").split(".")[0].replace(" ", "T")
                target_geo = datetime.fromisoformat(clean_dt_str)
                sched_dt_utc = target_geo - timedelta(hours=4)
                status = "scheduled"
                georgia_display = target_geo.strftime("%Y-%m-%d %H:%M") + " (საქართველოს დრო)"
        except Exception:
            sched_dt_utc = now_utc + timedelta(hours=1)
            status = "scheduled"
            georgia_display = (now_georgia + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M") + " (საქართველოს დრო)"
    else:
        status = "draft"
        georgia_display = "შენახულია მონახაზად (Draft)"

    async with async_session_maker() as session:
        new_post = ScheduledPost(
            raw_notes=notes,
            generated_text=post_text,
            image_path=photo_url.strip() if photo_url else "",
            scheduled_for=sched_dt_utc,
            status=status
        )
        session.add(new_post)
        await session.commit()
        await session.refresh(new_post)

        await ws_manager.broadcast({
            "type": "channel_post_created",
            "post_id": new_post.id
        })

        res_dict = {
            "success": True,
            "post_id": new_post.id,
            "generated_text": post_text,
            "image_url": photo_url,
            "status": new_post.status,
            "scheduled_time_georgia": georgia_display
        }
        _record_action("schedule_channel_post", {
            "notes": notes,
            "scheduled_time": georgia_display
        }, res_dict)
        return res_dict

async def update_store_settings(
    pickup_address: Optional[str] = None,
    delivery_courier_enabled: Optional[bool] = None,
    delivery_pickup_enabled: Optional[bool] = None,
    delivery_mail_enabled: Optional[bool] = None,
    payment_cash_enabled: Optional[bool] = None,
    payment_bank_enabled: Optional[bool] = None,
    bank_name: Optional[str] = None,
    bank_iban: Optional[str] = None,
    bank_recipient: Optional[str] = None,
    system_prompt: Optional[str] = None,
    fallback_message: Optional[str] = None,
    admin_telegram_ids: Optional[str] = None
) -> Dict[str, Any]:
    """მაღაზიის ნებისმიერი პარამეტრისა და საბანკო რეკვიზიტების განახლება."""
    async with async_session_maker() as session:
        res = await session.execute(select(StoreSettings).limit(1))
        st = res.scalars().first()
        if not st:
            st = StoreSettings()
            session.add(st)

        changes = []
        if pickup_address is not None:
            st.pickup_address = pickup_address.strip()
            changes.append(f"მისამართი: {st.pickup_address}")
        if delivery_courier_enabled is not None:
            st.delivery_courier_enabled = bool(delivery_courier_enabled)
            changes.append(f"კურიერი: {st.delivery_courier_enabled}")
        if delivery_pickup_enabled is not None:
            st.delivery_pickup_enabled = bool(delivery_pickup_enabled)
            changes.append(f"თვითგატანა: {st.delivery_pickup_enabled}")
        if delivery_mail_enabled is not None:
            st.delivery_mail_enabled = bool(delivery_mail_enabled)
            changes.append(f"ფოსტა: {st.delivery_mail_enabled}")
        if payment_cash_enabled is not None:
            st.payment_cash_enabled = bool(payment_cash_enabled)
            changes.append(f"ნაღდი გადახდა: {st.payment_cash_enabled}")
        if payment_bank_enabled is not None:
            st.payment_bank_enabled = bool(payment_bank_enabled)
            changes.append(f"საბანკო გადახდა: {st.payment_bank_enabled}")
        if bank_name is not None:
            st.bank_name = bank_name.strip()
            changes.append(f"ბანკი: {st.bank_name}")
        if bank_iban is not None:
            st.bank_iban = bank_iban.strip()
            changes.append(f"IBAN: {st.bank_iban}")
        if bank_recipient is not None:
            st.bank_recipient = bank_recipient.strip()
            changes.append(f"მიმღები: {st.bank_recipient}")
        if system_prompt is not None:
            st.system_prompt = system_prompt.strip()
            changes.append("AI პრომპტი განახლდა")
        if fallback_message is not None:
            st.fallback_message = fallback_message.strip()
            changes.append("Fallback მესიჯი განახლდა")
        if admin_telegram_ids is not None:
            st.admin_telegram_ids = admin_telegram_ids.strip()
            changes.append(f"ადმინ ID: {st.admin_telegram_ids}")

        await session.commit()

        await ws_manager.broadcast({
            "type": "settings_updated",
            "changes": changes
        })

        res_dict = {"success": True, "action": "update_store_settings", "changes": changes}
        _record_action("update_store_settings", {}, res_dict)
        return res_dict

# ------------------ Admin Assistant Agent Service ------------------

class AdminAssistantService:
    def __init__(self):
        self.model_name = "gemini-3.8-flash"
        self._client: Optional[genai.Client] = None

    @property
    def client(self) -> Optional[genai.Client]:
        if not self._client:
            try:
                if settings.USE_VERTEX_AI or settings.GCP_PROJECT_ID:
                    if settings.GOOGLE_APPLICATION_CREDENTIALS:
                        cred_path = Path(settings.GOOGLE_APPLICATION_CREDENTIALS)
                        if cred_path.exists():
                            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(cred_path.resolve())

                    self._client = genai.Client(
                        vertexai=True,
                        project=settings.GCP_PROJECT_ID or None,
                        location=settings.GCP_LOCATION or "global"
                    )
                elif settings.GEMINI_API_KEY:
                    self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.error(f"Error initializing Admin Assistant Gemini Client: {e}")
                self._client = None
        return self._client

    # ------------------ Main Agent Chat Loop ------------------

    async def process_admin_message(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Processes admin prompt with Gemini 3.8 Flash, calls tools as needed,
        and returns response text + list of executed actions.
        """
        if not self.client:
            return {
                "reply": "⚠️ ასისტენტი მიუწვდომელია (Gemini კლიენტი არ არის ინიციალიზებული).",
                "actions": []
            }

        tools_list = [
            navigate_to_tab,
            fill_form_field,
            open_modal,
            get_store_metrics,
            list_products,
            update_product,
            add_new_product,
            list_orders,
            update_order_status,
            schedule_channel_post,
            update_store_settings
        ]

        contents = []
        if conversation_history:
            for msg in conversation_history[-8:]:
                role = "user" if msg.get("sender") == "admin" else "model"
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part.from_text(text=msg.get("text", ""))]
                    )
                )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)]
            )
        )

        config = types.GenerateContentConfig(
            system_instruction=ADMIN_COPILOT_SYSTEM_PROMPT,
            temperature=0.3,
            max_output_tokens=1500,
            tools=tools_list,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            )
        )

        _current_actions.set([])
        executed_actions = []

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )

            current_turn_contents = list(contents)
            
            while response.function_calls:
                current_turn_contents.append(response.candidates[0].content)

                function_responses = []
                for fc in response.function_calls:
                    fname = fc.name
                    fargs = fc.args or {}
                    logger.info(f"Admin Copilot calling tool: {fname} with args: {fargs}")

                    tool_result = None
                    try:
                        if fname == "navigate_to_tab":
                            tool_result = await navigate_to_tab(**fargs)
                        elif fname == "fill_form_field":
                            tool_result = await fill_form_field(**fargs)
                        elif fname == "open_modal":
                            tool_result = await open_modal(**fargs)
                        elif fname == "get_store_metrics":
                            tool_result = await get_store_metrics()
                        elif fname == "list_products":
                            tool_result = await list_products(**fargs)
                        elif fname == "update_product":
                            tool_result = await update_product(**fargs)
                        elif fname == "add_new_product":
                            tool_result = await add_new_product(**fargs)
                        elif fname == "list_orders":
                            tool_result = await list_orders(**fargs)
                        elif fname == "update_order_status":
                            tool_result = await update_order_status(**fargs)
                        elif fname == "schedule_channel_post":
                            tool_result = await schedule_channel_post(**fargs)
                        elif fname == "update_store_settings":
                            tool_result = await update_store_settings(**fargs)
                        else:
                            tool_result = {"error": f"უცნობი ფუნქცია: {fname}"}
                    except Exception as err:
                        logger.error(f"Error executing tool {fname}: {err}", exc_info=True)
                        tool_result = {"error": str(err)}

                    executed_actions.append({"tool": fname, "args": fargs, "result": tool_result})

                    function_responses.append(
                        types.Part.from_function_response(
                            name=fname,
                            response={"result": tool_result}
                        )
                    )

                current_turn_contents.append(
                    types.Content(
                        role="user",
                        parts=function_responses
                    )
                )

                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=current_turn_contents,
                    config=config
                )

            final_text = response.text or "მოქმედება წარმატებით შესრულდა."
            all_actions = executed_actions if executed_actions else _current_actions.get()
            return {
                "reply": final_text.strip(),
                "actions": all_actions
            }

        except Exception as e:
            logger.error(f"Admin Assistant processing failed: {e}", exc_info=True)
            all_actions = executed_actions if executed_actions else _current_actions.get()
            return {
                "reply": f"სამწუხაროდ, ოპერაციის შესრულებისას დაფიქსირდა შეცდომა: {str(e)[:150]}",
                "actions": all_actions
            }

admin_assistant_service = AdminAssistantService()
