import json
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import select, text
from passlib.context import CryptContext

from backend.app.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    from backend.app.models import StoreSettings, AdminUser, Product

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Safe column migrations for existing SQLite tables
        try:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN receipt_image_url VARCHAR(1024) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE orders ADD COLUMN receipt_file_id VARCHAR(255) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN gemini_model VARCHAR(100) DEFAULT 'gemini-3.8-flash'"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN delivery_tbilisi_yandex_enabled BOOLEAN DEFAULT 1"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN delivery_regions_center_fee FLOAT DEFAULT 9.0"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN delivery_regions_village_fee FLOAT DEFAULT 12.0"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN delivery_regions_duration_days INTEGER DEFAULT 3"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN security_shield_enabled BOOLEAN DEFAULT 1"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE store_settings ADD COLUMN security_audit_logs TEXT DEFAULT '[]'"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE chat_messages ADD COLUMN media_url VARCHAR(1024) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE customers ADD COLUMN is_blacklisted BOOLEAN DEFAULT 0"))
        except Exception:
            pass
        
    pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
    
    # Initialize default settings & admin user if not exists
    async with async_session_maker() as session:
        # Check settings
        res = await session.execute(select(StoreSettings).limit(1))
        current_settings = res.scalars().first()
        if not current_settings:
            new_settings = StoreSettings(
                system_prompt="შენ ხარ GeoSteam-ის მეგობრული, უშუალო და ენერგიული კონსულტანტი ვეიპ სითხეების (E-Liquids) მაღაზიაში. შენი მიზანია დაეხმარო მომხმარებელს სწორი არომატისა და ნიკოტინის დონის შერჩევაში, პასუხი გასცე კითხვებს და დაეხმარო შეკვეთის გაფორმებაში.",
                ai_tone="official_humorous",
                delivery_courier_enabled=True,
                delivery_pickup_enabled=True,
                delivery_mail_enabled=True,
                payment_cash_enabled=True,
                payment_bank_enabled=True,
                pickup_address="https://maps.app.goo.gl/5Ehyo2jkQv91ChnG8",
                pickup_lat=41.6938,
                pickup_lng=44.8015,
                bank_name="BOG",
                bank_iban="GE58BG0000000100906441",
                bank_recipient="ლ.ჩ",
                gemini_model="gemini-3.6-flash",
                admin_telegram_ids="7191755188",
                admin_email="lchibarashvili@gmail.com",
                smtp_host="smtp.gmail.com",
                smtp_port=587,
                smtp_user="lchibarashvili@gmail.com",
                smtp_password="ppsx pujc bvgl ubyb",
                delivery_tbilisi_yandex_enabled=True,
                delivery_regions_center_fee=9.0,
                delivery_regions_village_fee=12.0,
                delivery_regions_duration_days=3
            )
            session.add(new_settings)
        else:
            # If dummy or default values present, update with real store settings
            if not current_settings.pickup_address or "რუსთაველი" in (current_settings.pickup_address or ""):
                current_settings.pickup_address = "https://maps.app.goo.gl/5Ehyo2jkQv91ChnG8"
            if not current_settings.bank_iban or "GE00TB0000000000000000" in (current_settings.bank_iban or ""):
                current_settings.bank_iban = "GE58BG0000000100906441"
                current_settings.bank_name = "BOG"
                current_settings.bank_recipient = "ლ.ჩ"
            if "შპს" in (current_settings.bank_recipient or ""):
                current_settings.bank_recipient = "Geosteam"
            if current_settings.system_prompt and "შპს" in current_settings.system_prompt:
                current_settings.system_prompt = current_settings.system_prompt.replace("არასდროს ახსენო 'შპს'.", "").replace("შპს", "")
            if not getattr(current_settings, "gemini_model", None) or "2.5" in (current_settings.gemini_model or "") or "2.0" in (current_settings.gemini_model or "") or "1.5" in (current_settings.gemini_model or ""):
                current_settings.gemini_model = "gemini-3.6-flash"
            session.add(current_settings)
            
        # Check products count - seed all products if empty
        prod_res = await session.execute(select(Product).limit(1))
        has_prod = prod_res.scalars().first()
        if not has_prod:
            seed_file = Path(__file__).parent / "seed_products.json"
            if seed_file.exists():
                try:
                    with open(seed_file, "r", encoding="utf-8") as f:
                        seed_data = json.load(f)
                    for item in seed_data:
                        p = Product(
                            name=item.get("name"),
                            description=item.get("description"),
                            price=float(item.get("price", 0.0)),
                            volume_ml=item.get("volume_ml"),
                            color_type=item.get("color_type"),
                            stock_quantity=int(item.get("stock_quantity", 0)),
                            is_active=bool(item.get("is_active", True)),
                            photo_url=item.get("photo_url"),
                            channel_post_url=item.get("channel_post_url"),
                            vg_pg_ratio=item.get("vg_pg_ratio"),
                            nicotine_mg=item.get("nicotine_mg")
                        )
                        session.add(p)
                except Exception as e:
                    logger.error(f"Error seeding products: {e}")

        # Check admin
        admin_res = await session.execute(select(AdminUser).limit(1))
        admin = admin_res.scalars().first()
        if not admin:
            default_admin = AdminUser(
                username="admin",
                password_hash=pwd_context.hash("admin123"),
                role="superadmin",
                is_active=True
            )
            session.add(default_admin)
            
        await session.commit()
