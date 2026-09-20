import asyncio
import sys

# Ensure UTF-8 output on Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.database import async_session_maker, init_db
from backend.app.models import Product
from sqlalchemy import select

SAMPLE_PRODUCTS = [
    {
        "name": "Elfliq Watermelon Ice",
        "description": "წვნიანი საზამთროს გამაგრილებელი არომატი მსუბუქი ყინულის ეფექტით. იდეალურია ზაფხულის ცხელი დღეებისთვის.",
        "price": 25.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 15,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/101"
    },
    {
        "name": "Elfliq Blue Razz Lemonade",
        "description": "ლურჯი ჟოლოსა და ციტრუსოვანი ლიმონათის ტკბილ-მომჟავო მიქსი. ერთ-ერთი ყველაზე პოპულარული გემო.",
        "price": 25.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 12,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/102"
    },
    {
        "name": "Elfliq Kiwi Passion Fruit Guava",
        "description": "ეგზოტიკური ტროპიკული კოქტეილი: კივი, პეშენფრუტი და მწიფე გუავა.",
        "price": 25.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 10,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/103"
    },
    {
        "name": "Nasty Juice Bad Blood Salt",
        "description": "მწიფე შავი მოცხარი (Blackcurrant) პიტნის ნაზი სიგრილით. პრემიუმ მალაიზიური ხარისხი.",
        "price": 28.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "35mg",
        "stock_quantity": 8,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/104"
    },
    {
        "name": "Nasty Juice Cush Man Salt",
        "description": "ნამდვილი ტროპიკული მანგოს ინტენსიური გემო მსუბუქი მენთოლით. მანგოს მოყვარულთა რჩეული.",
        "price": 28.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "35mg",
        "stock_quantity": 14,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/105"
    },
    {
        "name": "Dinner Lady Lemon Tart Salt",
        "description": "ლეგენდარული ლიმონის ტარტი — გამომცხვარი ხრაშუნა ცომი და ნაზი ლიმონის კრემი.",
        "price": 30.0,
        "volume_ml": 30,
        "color_type": "Dessert Salt",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 6,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/106"
    },
    {
        "name": "Elfliq Spearmint",
        "description": "კლასიკური გამაგრილებელი ბაღის პიტნა, სუფთა და სასიამოვნო გემო მთელი დღის განმავლობაში მოსაწევად.",
        "price": 24.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 20,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/107"
    },
    {
        "name": "Elfliq Strawberry Kiwi",
        "description": "ტკბილი მარწყვისა და მომჟავო კივის იდეალური ბალანსი.",
        "price": 25.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 9,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/108"
    },
    {
        "name": "Pod Salt Cuban Creme",
        "description": "პრემიუმ კუბური სიგარის თამბაქო ვანილისა და კარამელის კრემით. კლასიკური გემოების მოყვარულთათვის.",
        "price": 27.0,
        "volume_ml": 30,
        "color_type": "Tobacco Salt",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 5,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/109"
    },
    {
        "name": "Elfliq Pink Lemonade",
        "description": "ვარდისფერი ლიმონათი — წითელი კენკრისა და გამაგრილებელი გაზიანი ლიმონათის ტანდემი.",
        "price": 25.0,
        "volume_ml": 30,
        "color_type": "Salt Nicotine",
        "vg_pg_ratio": "50/50",
        "nicotine_mg": "20mg",
        "stock_quantity": 11,
        "is_active": True,
        "channel_post_url": "https://t.me/your_channel/110"
    }
]

async def seed():
    print("🌱 Initializing Database...")
    await init_db()
    
    async with async_session_maker() as session:
        # Check if already seeded
        res = await session.execute(select(Product))
        existing = res.scalars().all()
        if existing:
            print(f"Database already has {len(existing)} products. Skipping seed.")
            return

        print("Adding 10 sample E-Liquids...")
        for p in SAMPLE_PRODUCTS:
            prod = Product(**p)
            session.add(prod)

        await session.commit()
        print("✅ 10 Vape E-Liquid products added successfully!")

if __name__ == "__main__":
    asyncio.run(seed())
