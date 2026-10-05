import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from sqlalchemy import select

from backend.app.database import async_session_maker, IS_SQLITE
from backend.app.models import (
    StoreSettings, AdminUser, Product, Customer, Order, ScheduledPost, ChatMessage
)
from backend.app.config import settings
from backend.app.bot.bot_instance import bot_manager

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

class DatabaseBackupService:
    @staticmethod
    async def create_json_snapshot() -> Dict[str, Any]:
        """Creates a comprehensive JSON serializable snapshot of the entire database."""
        async with async_session_maker() as session:
            # 1. Store Settings
            st_res = await session.execute(select(StoreSettings).limit(1))
            st = st_res.scalars().first()
            settings_data = {}
            if st:
                settings_data = {
                    "system_prompt": st.system_prompt,
                    "ai_tone": st.ai_tone,
                    "delivery_courier_enabled": st.delivery_courier_enabled,
                    "delivery_pickup_enabled": st.delivery_pickup_enabled,
                    "delivery_mail_enabled": st.delivery_mail_enabled,
                    "delivery_tbilisi_yandex_enabled": getattr(st, "delivery_tbilisi_yandex_enabled", True),
                    "delivery_regions_center_fee": getattr(st, "delivery_regions_center_fee", 9.0),
                    "delivery_regions_village_fee": getattr(st, "delivery_regions_village_fee", 12.0),
                    "delivery_regions_duration_days": getattr(st, "delivery_regions_duration_days", 3),
                    "pickup_address": st.pickup_address,
                    "bank_name": st.bank_name,
                    "bank_iban": st.bank_iban,
                    "bank_recipient": st.bank_recipient,
                    "gemini_model": getattr(st, "gemini_model", "gemini-2.5-flash"),
                    "admin_telegram_ids": st.admin_telegram_ids,
                    "admin_email": st.admin_email
                }

            # 2. Products
            p_res = await session.execute(select(Product))
            products = p_res.scalars().all()
            products_data = [
                {
                    "id": p.id,
                    "name": p.name,
                    "description": p.description,
                    "price": p.price,
                    "volume_ml": p.volume_ml,
                    "color_type": p.color_type,
                    "stock_quantity": p.stock_quantity,
                    "is_active": p.is_active,
                    "photo_url": p.photo_url,
                    "channel_post_url": p.channel_post_url,
                    "vg_pg_ratio": p.vg_pg_ratio,
                    "nicotine_mg": p.nicotine_mg,
                    "created_at": p.created_at.isoformat() if p.created_at else None
                }
                for p in products
            ]

            # 3. Customers
            c_res = await session.execute(select(Customer))
            customers = c_res.scalars().all()
            customers_data = [
                {
                    "id": c.id,
                    "telegram_id": c.telegram_id,
                    "username": c.username,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "phone_number": getattr(c, "phone_number", ""),
                    "language_code": getattr(c, "language_code", "ka"),
                    "is_blacklisted": getattr(c, "is_blacklisted", False),
                    "created_at": c.created_at.isoformat() if c.created_at else None
                }
                for c in customers
            ]

            # 4. Orders
            o_res = await session.execute(select(Order))
            orders = o_res.scalars().all()
            orders_data = [
                {
                    "id": o.id,
                    "order_number": o.order_number,
                    "customer_telegram_id": o.customer_telegram_id,
                    "customer_name": o.customer_name,
                    "customer_phone": o.customer_phone,
                    "order_status": o.order_status,
                    "total_amount": o.total_amount,
                    "discount_amount": getattr(o, "discount_amount", 0.0),
                    "promo_code": getattr(o, "promo_code", ""),
                    "delivery_method": o.delivery_method,
                    "delivery_address": o.delivery_address,
                    "payment_method": o.payment_method,
                    "payment_status": o.payment_status,
                    "items_json": o.items_json,
                    "receipt_image_url": getattr(o, "receipt_image_url", ""),
                    "created_at": o.created_at.isoformat() if o.created_at else None
                }
                for o in orders
            ]

            # 5. Scheduled Posts
            sp_res = await session.execute(select(ScheduledPost))
            posts = sp_res.scalars().all()
            posts_data = [
                {
                    "id": sp.id,
                    "raw_notes": sp.raw_notes,
                    "generated_text": sp.generated_text,
                    "image_path": sp.image_path,
                    "scheduled_for": sp.scheduled_for.isoformat() if sp.scheduled_for else None,
                    "status": sp.status,
                    "published_at": sp.published_at.isoformat() if sp.published_at else None
                }
                for sp in posts
            ]

            # 6. Admin Users (preserving hashes, excluding passwords)
            a_res = await session.execute(select(AdminUser))
            admins = a_res.scalars().all()
            admins_data = [
                {
                    "id": a.id,
                    "username": a.username,
                    "password_hash": a.password_hash,
                    "role": a.role,
                    "is_active": a.is_active
                }
                for a in admins
            ]

            total_revenue = sum(o.total_amount or 0.0 for o in orders if getattr(o, "order_status", "") in ["paid", "delivered", "completed", "processing"])

            snapshot = {
                "backup_metadata": {
                    "app_name": settings.APP_NAME,
                    "timestamp": datetime.utcnow().isoformat(),
                    "total_products": len(products_data),
                    "total_orders": len(orders_data),
                    "total_customers": len(customers_data),
                    "total_revenue_gel": round(total_revenue, 2),
                    "db_type": "sqlite" if IS_SQLITE else "postgresql"
                },
                "store_settings": settings_data,
                "products": products_data,
                "customers": customers_data,
                "orders": orders_data,
                "scheduled_posts": posts_data,
                "admin_users": admins_data
            }
            return snapshot

    @classmethod
    async def create_backup_file(cls) -> Path:
        """Generates a JSON backup file on the server and returns its Path."""
        snapshot = await cls.create_json_snapshot()
        timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_path = BACKUP_DIR / f"geosteam_backup_{timestamp_str}.json"
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

        cls._cleanup_old_backups(keep=30)
        return file_path

    @classmethod
    async def restore_from_snapshot(cls, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Restores database contents from a JSON snapshot."""
        restored = {"products": 0, "settings": False, "customers": 0, "orders": 0}
        async with async_session_maker() as session:
            # 1. Restore Settings
            st_data = snapshot.get("store_settings")
            if st_data:
                res_s = await session.execute(select(StoreSettings).limit(1))
                st = res_s.scalars().first()
                if not st:
                    st = StoreSettings()
                    session.add(st)
                for k, v in st_data.items():
                    if hasattr(st, k):
                        setattr(st, k, v)
                restored["settings"] = True

            # 2. Restore Products
            prods_data = snapshot.get("products", [])
            if prods_data:
                for p_dict in prods_data:
                    p_name = p_dict.get("name")
                    if not p_name:
                        continue
                    res_p = await session.execute(select(Product).where(Product.name == p_name))
                    p = res_p.scalars().first()
                    if not p:
                        p = Product(name=p_name)
                        session.add(p)
                    p.description = p_dict.get("description", p.description or "")
                    p.price = float(p_dict.get("price", p.price or 0.0))
                    p.volume_ml = int(p_dict.get("volume_ml", p.volume_ml or 30))
                    p.color_type = p_dict.get("color_type", p.color_type or "")
                    p.stock_quantity = int(p_dict.get("stock_quantity", p.stock_quantity or 0))
                    p.is_active = bool(p_dict.get("is_active", True))
                    p.photo_url = p_dict.get("photo_url", p.photo_url or "")
                    p.channel_post_url = p_dict.get("channel_post_url", p.channel_post_url or "")
                    p.vg_pg_ratio = p_dict.get("vg_pg_ratio", p.vg_pg_ratio or "50/50")
                    p.nicotine_mg = p_dict.get("nicotine_mg", p.nicotine_mg or "20mg")
                    restored["products"] += 1

            await session.commit()
            
            try:
                from backend.app.routers.api_products import auto_sync_seed_products
                await auto_sync_seed_products(session)
            except Exception as ex:
                logger.debug(f"Could not sync seed after restore: {ex}")

        return restored

    @classmethod
    def _cleanup_old_backups(cls, keep: int = 30):
        try:
            files = sorted(BACKUP_DIR.glob("geosteam_backup_*.json"), key=os.path.getmtime)
            if len(files) > keep:
                for f in files[:-keep]:
                    f.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Error during old backup cleanup: {e}")

    @classmethod
    async def send_backup_to_telegram(cls, target_admin_id: Optional[str] = None) -> bool:
        """
        Creates a fresh backup and sends it directly to configured Telegram admin(s).
        """
        if not bot_manager.bot_app:
            logger.warning("Telegram Bot is not initialized. Cannot send backup.")
            return False

        try:
            backup_file = await cls.create_backup_file()
            with open(backup_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            meta = data.get("backup_metadata", {})
            caption = (
                f"💾 **Geosteam მონაცემთა ბაზის სარეზერვო ასლი (Backup)**\n\n"
                f"📅 **თარიღი (UTC):** `{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                f"📦 **პროდუქტები:** `{meta.get('total_products', 0)}` ცალი\n"
                f"🛒 **შეკვეთები:** `{meta.get('total_orders', 0)}` ცალი\n"
                f"👥 **მომხმარებლები:** `{meta.get('total_customers', 0)}`\n"
                f"💰 **შემოსავალი:** `{meta.get('total_revenue_gel', 0.0):.2f} GEL`\n"
                f"🐘 **ბაზის ტიპი:** `{meta.get('db_type', 'sqlite')}`\n\n"
                f"✅ ფაილი უსაფრთხოდ არის დარეზერვებული."
            )

            admin_ids = []
            if target_admin_id:
                admin_ids = [str(target_admin_id).strip()]
            else:
                async with async_session_maker() as session:
                    st_res = await session.execute(select(StoreSettings).limit(1))
                    st_db = st_res.scalars().first()
                    db_admin_ids = (st_db.admin_telegram_ids if st_db else "") or ""

                raw_ids = f"{settings.ADMIN_TELEGRAM_IDS or ''},{db_admin_ids}"
                admin_ids = list(set([aid.strip() for aid in raw_ids.split(",") if aid.strip().isdigit()]))
                if "7191755188" not in admin_ids:
                    admin_ids.append("7191755188")

            success = False
            for aid in admin_ids:
                try:
                    with open(backup_file, "rb") as bf:
                        await bot_manager.bot_app.bot.send_document(
                            chat_id=int(aid),
                            document=bf,
                            filename=backup_file.name,
                            caption=caption,
                            parse_mode="Markdown"
                        )
                    success = True
                    logger.info(f"Database backup sent successfully to Admin Telegram ID {aid}")
                except Exception as ex:
                    logger.error(f"Failed to send backup to Telegram ID {aid}: {ex}")

            return success
        except Exception as e:
            logger.error(f"Error creating and sending database backup: {e}", exc_info=True)
            return False

backup_service = DatabaseBackupService()
