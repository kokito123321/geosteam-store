import asyncio
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.database import get_db
from backend.app.models import PromoCode, Customer, AdminUser
from backend.app.schemas import PromoCodeCreate, PromoCodeResponse, BroadcastRequest
from backend.app.services.auth_service import get_current_user
from backend.app.bot.bot_instance import bot_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/marketing", tags=["marketing"])

@router.get("/promos", response_model=List[PromoCodeResponse])
async def list_promos(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(PromoCode).order_by(PromoCode.id.desc()))
    return res.scalars().all()

@router.post("/promos", response_model=PromoCodeResponse)
async def create_promo(
    promo_data: PromoCodeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    # Check if exists
    res = await db.execute(select(PromoCode).where(PromoCode.code == promo_data.code.upper()))
    if res.scalars().first():
        raise HTTPException(status_code=400, detail="პრომო კოდი უკვე არსებობს")

    promo = PromoCode(
        code=promo_data.code.upper(),
        discount_percent=promo_data.discount_percent,
        discount_amount=promo_data.discount_amount,
        min_order_amount=promo_data.min_order_amount,
        is_active=promo_data.is_active,
        usage_limit=promo_data.usage_limit
    )
    db.add(promo)
    await db.commit()
    await db.refresh(promo)
    return promo

@router.delete("/promos/{promo_id}")
async def delete_promo(
    promo_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(PromoCode).where(PromoCode.id == promo_id))
    promo = res.scalars().first()
    if not promo:
        raise HTTPException(status_code=404, detail="პრომო კოდი ვერ მოიძებნა")

    await db.delete(promo)
    await db.commit()
    return {"status": "success", "message": "პრომო კოდი წაიშალა"}

from datetime import datetime
import os
import uuid
from pathlib import Path
from fastapi import UploadFile, File
from backend.app.config import settings
from backend.app.models import ScheduledPost
from backend.app.schemas import (
    PromoCodeCreate, PromoCodeResponse, BroadcastRequest,
    GenerateChannelPostRequest, PublishChannelPostRequest, ScheduledPostResponse
)
from backend.app.ai.gemini_client import gemini_service

async def check_channel_subscription(bot, channel_id: str, user_id: int) -> bool:
    """Checks if a Telegram user is an active subscriber/member of the specified channel."""
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        status = getattr(member, 'status', '')
        status_str = str(status).lower()
        return any(s in status_str for s in ("creator", "administrator", "member", "restricted", "owner"))
    except Exception as e:
        logger.debug(f"User {user_id} channel check ({channel_id}) returned: {e}")
        return False

async def send_single_dm(bot, telegram_id: int, message_text: str, photo_url: Optional[str] = None) -> bool:
    """Sends a private DM to a Telegram user with automatic photo, markdown & plain text fallbacks."""
    if photo_url:
        local_path = None
        if photo_url.startswith("/static/"):
            local_path = Path("frontend") / photo_url.lstrip("/")
        elif os.path.exists(photo_url):
            local_path = Path(photo_url)

        if local_path and local_path.exists():
            try:
                with open(local_path, "rb") as f:
                    await bot.send_photo(chat_id=telegram_id, photo=f, caption=message_text, parse_mode="Markdown")
                return True
            except Exception as e_photo_md:
                logger.debug(f"Photo MD send failed for {telegram_id}: {e_photo_md}, retrying plain text caption...")
                try:
                    with open(local_path, "rb") as f:
                        await bot.send_photo(chat_id=telegram_id, photo=f, caption=message_text, parse_mode=None)
                    return True
                except Exception as e_photo_plain:
                    logger.debug(f"Photo send failed for {telegram_id}: {e_photo_plain}, falling back to text...")
        elif photo_url.startswith("http://") or photo_url.startswith("https://"):
            try:
                await bot.send_photo(chat_id=telegram_id, photo=photo_url, caption=message_text, parse_mode="Markdown")
                return True
            except Exception as e_url_md:
                logger.debug(f"URL photo MD send failed for {telegram_id}: {e_url_md}, retrying plain text caption...")
                try:
                    await bot.send_photo(chat_id=telegram_id, photo=photo_url, caption=message_text, parse_mode=None)
                    return True
                except Exception as e_url_plain:
                    logger.debug(f"URL photo send failed for {telegram_id}: {e_url_plain}, falling back to text...")

    # Fallback to direct text message
    try:
        await bot.send_message(chat_id=telegram_id, text=message_text, parse_mode="Markdown")
        return True
    except Exception as e_text_md:
        logger.debug(f"Markdown DM failed for {telegram_id}: {e_text_md}, sending as plain text...")
        try:
            await bot.send_message(chat_id=telegram_id, text=message_text, parse_mode=None)
            return True
        except Exception as e_text_plain:
            logger.warning(f"Failed to deliver DM to {telegram_id}: {e_text_plain}")
            return False

@router.post("/broadcast")
async def send_broadcast(
    broadcast: BroadcastRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Sends broadcast direct messages (DM) to bot customers, channel subscribers, or both."""
    if not bot_manager.bot_app:
        raise HTTPException(status_code=500, detail="Telegram ბოტი არ არის გაშვებული")

    target = broadcast.target or "all"
    bot = bot_manager.bot_app.bot

    # Fetch all active (non-blacklisted) customers from DB
    res = await db.execute(select(Customer).where(Customer.is_blacklisted == False))
    all_customers = res.scalars().all()

    channel_chat = settings.TELEGRAM_CHANNEL_ID or "@Geosteamforeveryone"
    if channel_chat and not str(channel_chat).startswith("@") and not str(channel_chat).startswith("-100") and not str(channel_chat).lstrip("-").isdigit():
        channel_chat = f"@{channel_chat}"

    recipients = []

    if target == "channel":
        # Target: ONLY active subscribers of the Telegram channel (@Geosteamforeveryone)
        # Check membership for each customer
        for c in all_customers:
            is_sub = await check_channel_subscription(bot, channel_chat, c.telegram_id)
            if is_sub:
                recipients.append(c)
    elif target == "bot_users":
        # Target: ONLY bot users in DB (who have chatted/interacted with the bot)
        recipients = list(all_customers)
    else: # "all"
        # Target: Everyone in DB (bot users + channel subscribers in DB)
        recipients = list(all_customers)

    success_count = 0
    fail_count = 0

    for c in recipients:
        try:
            ok = await send_single_dm(bot, c.telegram_id, broadcast.message, broadcast.photo_url)
            if ok:
                success_count += 1
            else:
                fail_count += 1
            await asyncio.sleep(0.04) # Telegram broadcast rate limiting
        except Exception as e:
            logger.warning(f"Error broadcasting DM to {c.telegram_id}: {e}")
            fail_count += 1

    return {
        "status": "completed",
        "target": target,
        "total_candidates": len(all_customers),
        "total_recipients": len(recipients),
        "sent_successfully": success_count,
        "failed": fail_count,
        "message": f"პირადი შეტყობინება (DM) წარმატებით გაეგზავნა {success_count} მომხმარებელს!"
    }

# ----------------- Channel Post AI Creator & Scheduler -----------------

@router.post("/upload-image")
async def upload_marketing_image(
    file: UploadFile = File(...),
    current_user: AdminUser = Depends(get_current_user)
):
    """Uploads an image for channel post or broadcast."""
    upload_dir = Path("frontend/static/uploads/posts")
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    ext = Path(file.filename or "image.jpg").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex[:12]}{ext}"
    target_path = upload_dir / filename
    
    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)
        
    url = f"/static/uploads/posts/{filename}"
    return {"status": "success", "url": url}

@router.post("/posts/generate")
async def generate_channel_post(
    req: GenerateChannelPostRequest,
    current_user: AdminUser = Depends(get_current_user)
):
    """Generates a high-converting Telegram post text using Gemini AI."""
    notes_text = (req.notes or req.raw_notes or "").strip()
    if not notes_text:
        raise HTTPException(status_code=400, detail="გთხოვთ მიუთითოთ პროდუქტის მოკლე აღწერა ან ჩანაწერები.")
        
    img_url = req.photo_url or req.image_url
    generated = await gemini_service.generate_channel_post(notes_text, img_url)
    return {
        "status": "success",
        "generated_text": generated,
        "generated_post": generated
    }

@router.get("/posts", response_model=List[ScheduledPostResponse])
async def list_channel_posts(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns all scheduled, draft, and published channel posts."""
    res = await db.execute(select(ScheduledPost).order_by(ScheduledPost.id.desc()))
    return res.scalars().all()

@router.post("/posts/publish-now")
async def publish_post_now(
    req: PublishChannelPostRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Immediately publishes a post to the Telegram Channel."""
    if not bot_manager.bot_app:
        raise HTTPException(status_code=500, detail="Telegram ბოტი არ არის გაშვებული")
        
    channel_id = settings.TELEGRAM_CHANNEL_ID
    if not channel_id:
        raise HTTPException(status_code=400, detail="ტელეგრამ ჩანელის ID არ არის მითითებული (.env)")

    # Send to channel
    try:
        if req.photo_url:
            # Handle local static upload or remote URL
            photo_to_send = req.photo_url
            if req.photo_url.startswith("/static/"):
                local_file = Path("frontend" + req.photo_url)
                if local_file.exists():
                    with open(local_file, "rb") as pf:
                        await bot_manager.bot_app.bot.send_photo(
                            chat_id=channel_id,
                            photo=pf,
                            caption=req.text,
                            parse_mode="Markdown"
                        )
                else:
                    await bot_manager.bot_app.bot.send_message(
                        chat_id=channel_id,
                        text=req.text,
                        parse_mode="Markdown"
                    )
            else:
                await bot_manager.bot_app.bot.send_photo(
                    chat_id=channel_id,
                    photo=req.photo_url,
                    caption=req.text,
                    parse_mode="Markdown"
                )
        else:
            await bot_manager.bot_app.bot.send_message(
                chat_id=channel_id,
                text=req.text,
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error publishing post to channel {channel_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"ჩანელში დაპოსტვა ვერ მოხერხდა: {e}")

    # Record in database
    post = ScheduledPost(
        generated_text=req.text,
        image_path=req.photo_url or "",
        status="published",
        published_at=datetime.utcnow()
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return {"status": "published", "post_id": post.id}

@router.post("/posts/schedule")
async def schedule_channel_post(
    req: PublishChannelPostRequest,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Schedules a post to be published at a specified datetime (Georgia Time UTC+4)."""
    from datetime import timezone, timedelta
    if not req.scheduled_for:
        raise HTTPException(status_code=400, detail="გთხოვთ მიუთითოთ გამოქვეყნების დრო (scheduled_for)")
        
    try:
        # If timestamp is ISO with timezone offset or Z
        if "Z" in req.scheduled_for or ("+" in req.scheduled_for and req.scheduled_for.index("+") > 10):
            clean_dt = req.scheduled_for.replace("Z", "+00:00")
            dt_aware = datetime.fromisoformat(clean_dt)
            dt_utc = dt_aware.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            # Naive string from Georgian datetime picker (Asia/Tbilisi UTC+4)
            clean_dt = req.scheduled_for.split(".")[0]
            naive_georgia_dt = datetime.fromisoformat(clean_dt)
            dt_utc = naive_georgia_dt - timedelta(hours=4)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"თარიღის არასწორი ფორმატი: {e}")

    post = ScheduledPost(
        generated_text=req.text,
        image_path=req.photo_url or "",
        scheduled_for=dt_utc,
        status="scheduled"
    )
    db.add(post)
    await db.commit()
    await db.refresh(post)
    return {"status": "scheduled", "post_id": post.id, "scheduled_for": post.scheduled_for}

@router.delete("/posts/{post_id}")
async def delete_channel_post(
    post_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Deletes/cancels a scheduled or draft channel post."""
    res = await db.execute(select(ScheduledPost).where(ScheduledPost.id == post_id))
    post = res.scalars().first()
    if not post:
        raise HTTPException(status_code=404, detail="პოსტი ვერ მოიძებნა")
        
    await db.delete(post)
    await db.commit()
    return {"status": "success", "message": "პოსტი წაიშალა"}
