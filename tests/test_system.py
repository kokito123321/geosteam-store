import asyncio
import sys
import httpx

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.main import app
from backend.app.database import init_db

async def run_tests():
    print("🧪 Running System Verification Tests...")
    await init_db()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Healthcheck
        res = await client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print("✅ 1. Healthcheck: OK")

        # 2. Login Page HTML
        res = await client.get("/login")
        assert res.status_code == 200, f"Login page failed: {res.text}"
        assert "ავტორიზაცია" in res.text
        print("✅ 2. Login Page HTML Template: OK")

        # 3. Admin Dashboard HTML
        res = await client.get("/admin")
        assert res.status_code == 200, f"Admin dashboard failed: {res.text}"
        assert "Geosteam Admin" in res.text
        print("✅ 3. Admin Dashboard HTML Template: OK (Geosteam Branding verified)")

        # 4. Auth API Login
        login_res = await client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {token}"}
        print("✅ 4. JWT Admin Authentication: OK")

        # 5. List Products
        prod_res = await client.get("/api/products")
        assert prod_res.status_code == 200, f"Products list failed: {prod_res.text}"
        products = prod_res.json()
        print(f"✅ 5. Products Catalog API: OK ({len(products)} E-Liquids verified)")

        # 5.1 Test Bulk Delete on Products
        new_prod_1 = await client.post("/api/products", json={"name": "Temp Test 1", "price": 10.0, "volume_ml": 30, "vg_pg_ratio": "50/50", "nicotine_mg": "20mg", "stock_quantity": 5}, headers=auth_headers)
        new_prod_2 = await client.post("/api/products", json={"name": "Temp Test 2", "price": 12.0, "volume_ml": 30, "vg_pg_ratio": "50/50", "nicotine_mg": "20mg", "stock_quantity": 5}, headers=auth_headers)
        p1_id = new_prod_1.json()["id"]
        p2_id = new_prod_2.json()["id"]
        bulk_del_res = await client.post("/api/products/bulk-delete", json={"product_ids": [p1_id, p2_id]}, headers=auth_headers)
        assert bulk_del_res.status_code == 200, f"Bulk delete failed: {bulk_del_res.text}"
        assert bulk_del_res.json()["deleted_count"] == 2
        print("✅ 5.1 Product Bulk Checkbox Deletion: OK")

        # 6. Store Settings & Gemini Model Selection API
        settings_res = await client.get("/api/settings", headers=auth_headers)
        assert settings_res.status_code == 200, f"Settings fetch failed: {settings_res.text}"
        settings_data = settings_res.json()
        assert "შპს" not in (settings_data.get("bank_recipient") or "")
        assert settings_data.get("gemini_model") in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.7-flash", "gemini-3.8-flash"]

        # Update Gemini model dynamically
        update_model_res = await client.put("/api/settings", json={"gemini_model": "gemini-2.5-flash"}, headers=auth_headers)
        assert update_model_res.status_code == 200
        assert update_model_res.json()["gemini_model"] == "gemini-2.5-flash"
        print(f"✅ 6. Store Logistics & Dynamic Gemini Model Selector: OK (Model: {update_model_res.json()['gemini_model']})")

        # 7. Orders API
        orders_res = await client.get("/api/orders", headers=auth_headers)
        assert orders_res.status_code == 200, f"Orders fetch failed: {orders_res.text}"
        print("✅ 7. Orders Management & Receipt Field API: OK")

        # 8. Chat Threads API
        threads_res = await client.get("/api/chat/threads", headers=auth_headers)
        assert threads_res.status_code == 200, f"Chat threads fetch failed: {threads_res.text}"
        print("✅ 8. Live Chat Threads API: OK")

        # 9. Channel Posts AI & Scheduling API
        from datetime import datetime, timedelta
        future_time = (datetime.utcnow() + timedelta(hours=2)).isoformat()
        sched_res = await client.post("/api/marketing/posts/schedule", json={
            "text": "🧪 Geosteam Test Post with AI",
            "photo_url": None,
            "scheduled_for": future_time
        }, headers=auth_headers)
        assert sched_res.status_code == 200, f"Schedule post failed: {sched_res.text}"
        post_id = sched_res.json()["post_id"]

        # List scheduled posts
        list_posts_res = await client.get("/api/marketing/posts", headers=auth_headers)
        assert list_posts_res.status_code == 200
        assert any(p["id"] == post_id for p in list_posts_res.json())

        # Delete scheduled post
        del_post_res = await client.delete(f"/api/marketing/posts/{post_id}", headers=auth_headers)
        assert del_post_res.status_code == 200
        print("✅ 9. Channel Post AI Scheduler & Queue Management API: OK")

        # 10. Test Dynamic AI Prompt Builder & Strict Anti-Hallucination
        from backend.app.ai.prompts import build_system_prompt
        from backend.app.models import StoreSettings, Product
        from backend.app.database import async_session_maker
        from sqlalchemy import select
        async with async_session_maker() as session:
            s_res = await session.execute(select(StoreSettings).limit(1))
            st = s_res.scalars().first()
            p_res = await session.execute(select(Product))
            prods = p_res.scalars().all()
            prompt = build_system_prompt(st, prods)
            assert "Geosteam" in prompt, "Dynamic prompt missing Geosteam branding"
            assert "შპს" not in prompt, "Prompt must NOT contain შპს"
            assert st.bank_iban in prompt, "Dynamic prompt missing exact bank IBAN"
            print(f"✅ 10. Strict Anti-Hallucination & Dynamic Geosteam Prompt: OK (IBAN: {st.bank_iban})")

    print("\n🎉 ALL 10 COMPREHENSIVE SYSTEM VERIFICATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(run_tests())
