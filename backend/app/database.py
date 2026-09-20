from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from backend.app.config import settings

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
    from backend.app.models import StoreSettings, AdminUser
    from passlib.context import CryptContext
    from sqlalchemy import select

    from sqlalchemy import text

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
                system_prompt="შენ ხარ პროფესიონალი და მეგობრული AI გაყიდვების ასისტენტი Geosteam-ის ვეიპის სითხეების (E-Liquids) მაღაზიაში. მაღაზიის სახელია მხოლოდ Geosteam (ჯეოსტიმი). შენი მიზანია დაეხმარო მომხმარებელს სწორი არომატისა და ნიკოტინის დონის შერჩევაში, პასუხი გასცე კითხვებს და დაეხმარო შეკვეთის გაფორმებაში. იყავი საქმიანი, თავაზიანი და მსუბუქი იუმორით. თუ პროდუქტი არ არის მარაგში, შესთავაზე მსგავსი გემოები ან ოპერატორთან გადამისამართება.",
                ai_tone="official_humorous",
                delivery_courier_enabled=True,
                delivery_pickup_enabled=True,
                delivery_mail_enabled=False,
                payment_cash_enabled=True,
                payment_bank_enabled=True,
                pickup_address=settings.STORE_LOCATION_ADDRESS,
                pickup_lat=settings.STORE_LOCATION_LAT,
                pickup_lng=settings.STORE_LOCATION_LNG,
                bank_name=settings.STORE_BANK_NAME,
                bank_iban=settings.STORE_IBAN,
                bank_recipient="Geosteam",
                gemini_model="gemini-2.5-flash",
                admin_telegram_ids=settings.ADMIN_TELEGRAM_IDS,
                admin_email=settings.ADMIN_EMAIL
            )
            session.add(new_settings)
        else:
            # Clean up any legacy LLC/შპს from existing settings
            if "შპს" in (current_settings.bank_recipient or ""):
                current_settings.bank_recipient = "Geosteam"
            if current_settings.system_prompt and "შპს" in current_settings.system_prompt:
                current_settings.system_prompt = current_settings.system_prompt.replace("არასდროს ახსენო 'შპს'.", "").replace("შპს", "")
            if not getattr(current_settings, "gemini_model", None):
                current_settings.gemini_model = "gemini-2.5-flash"
            session.add(current_settings)
            
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
