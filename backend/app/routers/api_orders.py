from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.database import get_db
from backend.app.models import Order, AdminUser, Customer
from backend.app.schemas import OrderResponse, OrderUpdate
from backend.app.services.auth_service import get_current_user
from backend.app.services.notifications import ws_manager
from backend.app.bot.bot_instance import bot_manager

router = APIRouter(prefix="/api/orders", tags=["orders"])

@router.get("", response_model=List[OrderResponse])
async def list_orders(
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    query = select(Order).order_by(Order.id.desc())
    if status:
        query = query.where(Order.order_status == status)
    result = await db.execute(query)
    return result.scalars().all()

@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(Order).where(Order.id == order_id))
    order = res.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="შეკვეთა ვერ მოიძებნა")
    return order

@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order_status(
    order_id: int,
    order_update: OrderUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(Order).where(Order.id == order_id))
    order = res.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="შეკვეთა ვერ მოიძებნა")

    old_status = order.order_status
    if order_update.order_status:
        order.order_status = order_update.order_status
    if order_update.payment_status:
        order.payment_status = order_update.payment_status
    if order_update.notes is not None:
        order.notes = order_update.notes

    await db.commit()
    await db.refresh(order)

    # If status changed, notify customer on Telegram!
    if order_update.order_status and order_update.order_status != old_status:
        status_translations = {
            "processing": "მზადდება / გადაცემულია კურიერს 🛵",
            "delivered": "ჩაბარებულია / დასრულებულია ✅",
            "cancelled": "გაუქმებულია ❌"
        }
        translated = status_translations.get(order.order_status, order.order_status)
        tg_text = (
            f"🔔 **განახლება თქვენს შეკვეთაზე #{order.order_number}!**\n\n"
            f"სტატუსი შეიცვალა: **{translated}**\n\n"
            f"გმადლობთ, რომ სარგებლობთ ჩვენი მომსახურებით!"
        )
        if bot_manager.bot_app:
            try:
                await bot_manager.bot_app.bot.send_message(
                    chat_id=order.customer_telegram_id,
                    text=tg_text,
                    parse_mode="Markdown"
                )
            except Exception:
                pass

    await ws_manager.broadcast({
        "type": "order_updated",
        "order_id": order.id,
        "new_status": order.order_status,
        "payment_status": order.payment_status
    })
    return order

@router.post("/{order_id}/approve-receipt")
async def approve_receipt(
    order_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """დაადასტურებს ქვითარს, მონიშნავს გადახდას წარმატებულად და შეკვეთას გადაიყვანს processing-ზე."""
    res = await db.execute(select(Order).where(Order.id == order_id))
    order = res.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="შეკვეთა ვერ მოიძებნა")

    order.payment_status = "paid"
    order.order_status = "processing"
    await db.commit()
    await db.refresh(order)

    # Send confirmation to customer via Telegram
    if bot_manager.bot_app and order.customer_telegram_id:
        try:
            tg_msg = (
                f"✅ **გადახდა დადასტურებულია!**\n\n"
                f"თქვენი შეკვეთის (#{order.order_number}) ქვითარი წარმატებით გადამოწმდა.\n"
                f"შეკვეთა გადავიდა მომზადების ეტაპზე 🛵💨\n\n"
                f"დიდი მადლობა Geosteam-ის არჩევისთვის!"
            )
            await bot_manager.bot_app.bot.send_message(
                chat_id=order.customer_telegram_id,
                text=tg_msg,
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await ws_manager.broadcast({
        "type": "order_updated",
        "order_id": order.id,
        "order_number": order.order_number,
        "new_status": "processing",
        "payment_status": "paid"
    })

    return {"success": True, "message": "გადახდა დადასტურებულია", "order_id": order.id}

@router.post("/{order_id}/reject-receipt")
async def reject_receipt(
    order_id: int,
    reason: Optional[str] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """უარყოფს ქვითარს (არასწორი/დაუმთხვეველი თანხა ან რეკვიზიტი)."""
    res = await db.execute(select(Order).where(Order.id == order_id))
    order = res.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="შეკვეთა ვერ მოიძებნა")

    order.payment_status = "rejected"
    if reason:
        order.notes = f"ქვითარი უარყოფილია: {reason}"
    await db.commit()
    await db.refresh(order)

    # Notify customer via Telegram
    if bot_manager.bot_app and order.customer_telegram_id:
        try:
            reason_text = f"\nმიზეზი: {reason}" if reason else ""
            tg_msg = (
                f"⚠️ **შეტყობინება შეკვეთაზე #{order.order_number}**\n\n"
                f"გამოგზავნილი გადარიცხვის ქვითარი ვერ დადასტურდა.{reason_text}\n"
                f"გთხოვთ გადაამოწმოთ რეკვიზიტები ან გადმოგვიგზავნოთ სწორი ქვითრის ფოტო."
            )
            await bot_manager.bot_app.bot.send_message(
                chat_id=order.customer_telegram_id,
                text=tg_msg,
                parse_mode="Markdown"
            )
        except Exception:
            pass

    await ws_manager.broadcast({
        "type": "order_updated",
        "order_id": order.id,
        "order_number": order.order_number,
        "new_status": order.order_status,
        "payment_status": "rejected"
    })

    return {"success": True, "message": "ქვითარი უარყოფილია", "order_id": order.id}
