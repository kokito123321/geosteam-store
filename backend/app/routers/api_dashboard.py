from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, update
from backend.app.database import get_db
from backend.app.models import Order, Product, ChatMessage, Customer, AdminUser
from backend.app.services.auth_service import get_current_user
from backend.app.services.notifications import ws_manager

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

class ResetMetricRequest(BaseModel):
    metric: str # "revenue", "orders", "products", "chats", "all"

@router.post("/reset-metric")
async def reset_metric(
    payload: ResetMetricRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    metric = payload.metric.strip().lower()
    
    if metric in ["revenue", "orders"]:
        # Delete orders or reset
        await db.execute(delete(Order))
        await db.commit()
        msg = "შეკვეთები და შემოსავალი წარმატებით განულდა"
    elif metric == "products":
        # Reset products to inactive or 0 stock
        await db.execute(update(Product).values(is_active=False, stock_quantity=0))
        await db.commit()
        msg = "აქტიური პროდუქტები წარმატებით განულდა"
    elif metric == "chats":
        # Delete chat messages and unpause customers
        await db.execute(delete(ChatMessage))
        await db.execute(update(Customer).values(bot_paused=False, order_state="IDLE", temp_cart="{}"))
        await db.commit()
        msg = "მომხმარებელთა ჩატები წარმატებით განულდა"
    elif metric == "all":
        await db.execute(delete(Order))
        await db.execute(delete(ChatMessage))
        await db.execute(update(Product).values(is_active=False, stock_quantity=0))
        await db.execute(update(Customer).values(bot_paused=False, order_state="IDLE", temp_cart="{}"))
        await db.commit()
        msg = "ყველა მეტრიკა წარმატებით განულდა"
    else:
        raise HTTPException(status_code=400, detail="არასწორი მეტრიკის ტიპი")

    await ws_manager.broadcast({
        "type": "dashboard_reset",
        "metric": metric
    })

    return {"success": True, "message": msg}
