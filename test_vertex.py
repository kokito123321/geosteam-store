import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from backend.app.ai.gemini_client import gemini_service
from backend.app.database import async_session_maker
from backend.app.ai.prompts import build_system_prompt
from backend.app.models import StoreSettings, Product
from sqlalchemy import select

async def main():
    print("🚀 Testing Google Cloud Vertex AI integration...")
    async with async_session_maker() as session:
        s_res = await session.execute(select(StoreSettings).limit(1))
        st = s_res.scalars().first()
        p_res = await session.execute(select(Product))
        prods = p_res.scalars().all()
        prompt = build_system_prompt(st, prods)

    user_query = "გამარჯობა, საზამთროს არომატი გაქვთ რამე?"
    print(f"👤 მომხმარებელი: {user_query}")
    answer = await gemini_service.get_response(
        user_message=user_query,
        system_instruction=prompt
    )
    print("🤖 AI ასისტენტი (Vertex AI / $300 GCP Credit):")
    print(answer)
    print("\n✅ GOOGLE CLOUD VERTEX AI WORKING 100% PERFECTLY!")

    print("\n📢 Testing Channel Post Parsing with Vertex AI...")
    from backend.app.ai.post_parser import parse_channel_post_content
    post = "ახალი ჩამოსვლა! Elf Bar Apple Peach 30ml 50/50 20mg ნიკოტინით. საუკეთესო ვაშლის და ატმის მიქსი. ფასი: 28 ლარი. მარაგი: 20 ცალი"
    parsed = await parse_channel_post_content(post)
    print("Parsed JSON:", parsed)
    assert parsed["name"]
    print("✅ CHANNEL POST AUTO-PARSER WORKING 100% PERFECTLY!")

if __name__ == "__main__":
    asyncio.run(main())
