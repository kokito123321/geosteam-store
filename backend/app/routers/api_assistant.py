from typing import List, Optional
from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from pydantic import BaseModel

from backend.app.database import get_db
from backend.app.models import AdminUser, AdminAssistantMessage
from backend.app.services.auth_service import get_current_user
from backend.app.ai.admin_assistant import admin_assistant_service

router = APIRouter(prefix="/api/admin/assistant", tags=["admin_assistant"])

class AssistantChatRequest(BaseModel):
    message: str

@router.post("/chat")
async def chat_with_assistant(
    req: AssistantChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Processes admin instruction via Gemini 3.8 Flash tool-calling copilot."""
    user_prompt = req.message.strip()
    if not user_prompt:
        raise HTTPException(status_code=400, detail="შეტყობინება ცარიელია")

    # Fetch recent conversation history
    res_hist = await db.execute(
        select(AdminAssistantMessage).order_by(AdminAssistantMessage.id.desc()).limit(10)
    )
    raw_history = list(reversed(res_hist.scalars().all()))
    history_formatted = [
        {"sender": m.sender, "text": m.message_text}
        for m in raw_history
    ]

    # Save admin message
    admin_msg = AdminAssistantMessage(
        sender="admin",
        message_text=user_prompt
    )
    db.add(admin_msg)
    await db.commit()

    # Process with Gemini Copilot
    result = await admin_assistant_service.process_admin_message(
        user_message=user_prompt,
        conversation_history=history_formatted
    )

    reply_text = result.get("reply", "")
    actions = result.get("actions", [])

    # Save assistant response
    assistant_msg = AdminAssistantMessage(
        sender="assistant",
        message_text=reply_text,
        actions_performed=json.dumps(actions, ensure_ascii=False)
    )
    db.add(assistant_msg)
    await db.commit()

    return {
        "reply": reply_text,
        "actions": actions,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/history")
async def get_assistant_history(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns conversation history with the Admin Assistant."""
    res = await db.execute(
        select(AdminAssistantMessage).order_by(AdminAssistantMessage.id.asc()).limit(50)
    )
    messages = res.scalars().all()
    out = []
    for m in messages:
        actions = []
        try:
            actions = json.loads(m.actions_performed or "[]")
        except Exception:
            pass
        out.append({
            "id": m.id,
            "sender": m.sender,
            "text": m.message_text,
            "actions": actions,
            "timestamp": m.timestamp.isoformat() if m.timestamp else ""
        })
    return out

@router.delete("/history")
async def clear_assistant_history(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Clears conversation history with the Admin Assistant."""
    await db.execute(delete(AdminAssistantMessage))
    await db.commit()
    return {"status": "ok", "message": "ასისტენტის ჩატის ისტორია გასუფთავდა"}
