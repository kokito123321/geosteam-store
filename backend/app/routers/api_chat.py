from typing import List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from backend.app.database import get_db
from backend.app.models import Customer, ChatMessage, AdminUser
from backend.app.services.auth_service import get_current_user
from backend.app.services.notifications import ws_manager
from backend.app.bot.bot_instance import bot_manager

router = APIRouter(prefix="/api/chat", tags=["chat"])

class SendMessageRequest(BaseModel):
    message: str

@router.get("/threads")
async def list_chat_threads(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns list of customer chat threads with latest messages."""
    res = await db.execute(select(Customer).order_by(Customer.last_active.desc()))
    customers = res.scalars().all()

    threads = []
    for c in customers:
        # Get last message
        res_msg = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.customer_telegram_id == c.telegram_id)
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        last_msg = res_msg.scalars().first()

        threads.append({
            "customer_id": c.telegram_id,
            "name": f"{c.first_name} {c.last_name}".strip() or f"@{c.username}" or f"User #{c.telegram_id}",
            "username": c.username,
            "phone": c.phone_number,
            "bot_paused": c.bot_paused,
            "last_active": c.last_active.isoformat() if c.last_active else None,
            "last_message": last_msg.message_text if last_msg else "",
            "last_sender": last_msg.sender if last_msg else ""
        })
    return threads

@router.get("/threads/{customer_id}/messages")
async def get_thread_messages(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns message history for a customer."""
    res = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.customer_telegram_id == customer_id)
        .order_by(ChatMessage.id.asc())
    )
    messages = res.scalars().all()
    return [
        {
            "id": m.id,
            "sender": m.sender,
            "text": m.message_text,
            "media_url": m.media_url or "",
            "timestamp": m.timestamp.isoformat() if m.timestamp else ""
        }
        for m in messages
    ]

@router.post("/threads/{customer_id}/send")
async def send_admin_message(
    customer_id: int,
    req: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Admin sends a reply directly to customer's Telegram."""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="შეტყობინება ცარიელია")

    # Send on Telegram
    if bot_manager.bot_app:
        try:
            formatted_text = f"👨‍💼 **ოპერატორი:**\n{req.message}"
            await bot_manager.bot_app.bot.send_message(
                chat_id=customer_id,
                text=formatted_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Telegram-ზე გაგზავნა ვერ მოხერხდა: {e}")

    # Save to chat history
    chat_msg = ChatMessage(
        customer_telegram_id=customer_id,
        sender="admin",
        message_text=req.message
    )
    db.add(chat_msg)
    await db.commit()

    # Broadcast to dashboard
    await ws_manager.broadcast({
        "type": "new_chat_message",
        "message": {
            "customer_id": customer_id,
            "sender": "admin",
            "text": req.message,
            "timestamp": datetime.utcnow().isoformat()
        }
    })

    return {"status": "sent"}

@router.post("/threads/{customer_id}/toggle-bot")
async def toggle_bot_status(
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Toggles bot active/paused state for Human Handoff."""
    res = await db.execute(select(Customer).where(Customer.telegram_id == customer_id))
    customer = res.scalars().first()
    if not customer:
        raise HTTPException(status_code=404, detail="მომხმარებელი ვერ მოიძებნა")

    customer.bot_paused = not customer.bot_paused
    await db.commit()

    await ws_manager.broadcast({
        "type": "bot_status_toggled",
        "customer_id": customer_id,
        "bot_paused": customer.bot_paused
    })

    return {"status": "success", "bot_paused": customer.bot_paused}

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep-alive ping/pong
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
