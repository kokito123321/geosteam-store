from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from backend.app.database import get_db
from backend.app.models import BlacklistUser, Customer, AdminUser
from backend.app.services.auth_service import get_current_user
from backend.app.services.notifications import ws_manager

router = APIRouter(prefix="/api/blacklist", tags=["blacklist"])

class BlacklistUserCreate(BaseModel):
    telegram_id: int
    username: Optional[str] = ""
    full_name: Optional[str] = ""
    reason: Optional[str] = "არასწორი / ყალბი ქვითარი"
    receipt_url: Optional[str] = ""

class BlacklistUserResponse(BaseModel):
    id: int
    telegram_id: int
    username: str
    full_name: str
    reason: str
    receipt_url: str
    created_at: datetime

    class Config:
        from_attributes = True

@router.get("", response_model=List[BlacklistUserResponse])
async def get_blacklist(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(BlacklistUser).order_by(BlacklistUser.id.desc()))
    return res.scalars().all()

@router.post("", response_model=BlacklistUserResponse)
async def add_to_blacklist(
    payload: BlacklistUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(BlacklistUser).where(BlacklistUser.telegram_id == payload.telegram_id))
    existing = res.scalars().first()
    if existing:
        existing.reason = payload.reason
        existing.receipt_url = payload.receipt_url or existing.receipt_url
        if payload.username:
            existing.username = payload.username
        if payload.full_name:
            existing.full_name = payload.full_name
        item = existing
    else:
        item = BlacklistUser(
            telegram_id=payload.telegram_id,
            username=payload.username or "",
            full_name=payload.full_name or f"User {payload.telegram_id}",
            reason=payload.reason or "ადმინისტრატორის მიერ დაბლოკილი",
            receipt_url=payload.receipt_url or ""
        )
        db.add(item)

    res_c = await db.execute(select(Customer).where(Customer.telegram_id == payload.telegram_id))
    cust = res_c.scalars().first()
    if cust:
        cust.is_blacklisted = True

    await db.commit()
    await db.refresh(item)

    await ws_manager.broadcast({
        "type": "blacklist_updated",
        "action": "added",
        "user_id": item.telegram_id,
        "username": item.username
    })

    return item

@router.delete("/{blacklist_id}")
async def remove_from_blacklist(
    blacklist_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(BlacklistUser).where(BlacklistUser.id == blacklist_id))
    item = res.scalars().first()
    if not item:
        raise HTTPException(status_code=404, detail="მომხმარებელი შავ სიაში ვერ მოიძებნა")

    telegram_id = item.telegram_id

    res_c = await db.execute(select(Customer).where(Customer.telegram_id == telegram_id))
    cust = res_c.scalars().first()
    if cust:
        cust.is_blacklisted = False

    await db.delete(item)
    await db.commit()

    await ws_manager.broadcast({
        "type": "blacklist_updated",
        "action": "removed",
        "user_id": telegram_id
    })

    return {"success": True, "message": "მომხმარებელი წარმატებით ამოიშალა შავი სიიდან"}
