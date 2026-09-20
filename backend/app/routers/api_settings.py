from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from backend.app.database import get_db
from backend.app.models import StoreSettings, AdminUser
from backend.app.schemas import StoreSettingsSchema
from backend.app.services.auth_service import get_current_user
from backend.app.ai.gemini_client import gemini_service
from backend.app.config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

import json
import re
import socket
from datetime import datetime

def get_lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def validate_and_sanitize_iban(iban: str) -> str:
    """Validates and formats Georgian IBAN (GE + 2 digits + 2 chars + 16 digits)."""
    cleaned = re.sub(r"\s+", "", iban.strip()).upper()
    if not cleaned:
        return ""
    if not re.match(r"^GE\d{2}[A-Z]{2}\d{16}$", cleaned):
        # Allow partial entry if admin is typing, but strip dangerous characters
        cleaned = re.sub(r"[^A-Za-z0-9]", "", cleaned)
    return cleaned

@router.get("", response_model=StoreSettingsSchema)
async def get_settings(db: AsyncSession = Depends(get_db)):
    res = await db.execute(select(StoreSettings).limit(1))
    s = res.scalars().first()
    if not s:
        s = StoreSettings()
        db.add(s)
        await db.commit()
        await db.refresh(s)
    return s

@router.put("", response_model=StoreSettingsSchema)
async def update_settings(
    settings_data: StoreSettingsSchema,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    res = await db.execute(select(StoreSettings).limit(1))
    s = res.scalars().first()
    if not s:
        s = StoreSettings()
        db.add(s)

    dump = settings_data.model_dump(exclude_unset=True)
    old_iban = s.bank_iban
    old_recipient = s.bank_recipient

    if "bank_iban" in dump and dump["bank_iban"]:
        dump["bank_iban"] = validate_and_sanitize_iban(dump["bank_iban"])

    # Security Audit Logging
    audit_events = []
    try:
        existing_logs = json.loads(s.security_audit_logs or "[]")
    except Exception:
        existing_logs = []

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if "bank_iban" in dump and dump["bank_iban"] != old_iban:
        existing_logs.insert(0, {
            "timestamp": now_str,
            "user": current_user.username,
            "action": "საბანკო IBAN განახლდა",
            "details": f"ახალი IBAN: {dump['bank_iban'][:6]}••••••••{dump['bank_iban'][-4:] if len(dump['bank_iban']) > 10 else ''}",
            "status": "დაცულია"
        })

    if "bank_recipient" in dump and dump["bank_recipient"] != old_recipient:
        existing_logs.insert(0, {
            "timestamp": now_str,
            "user": current_user.username,
            "action": "მიმღების სახელი განახლდა",
            "details": f"მიმღები: {dump['bank_recipient']}",
            "status": "დაცულია"
        })

    # Keep only last 20 audit events
    s.security_audit_logs = json.dumps(existing_logs[:20], ensure_ascii=False)

    for field, value in dump.items():
        setattr(s, field, value)

    if s.gemini_model:
        gemini_service.update_model_name(s.gemini_model)

    await db.commit()
    await db.refresh(s)
    return s

@router.get("/mobile-info")
async def get_mobile_access_info(
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns local network URL and details for mobile/mini-app access."""
    lan_ip = get_lan_ip()
    port = settings.PORT or 8000
    mobile_url = f"http://{lan_ip}:{port}/admin"
    return {
        "status": "success",
        "lan_ip": lan_ip,
        "port": port,
        "mobile_url": mobile_url,
        "admin_command": "/admin",
        "bot_username": "GeoSteamSupportBot"
    }

@router.get("/security-logs")
async def get_security_audit_logs(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Returns the list of security and anti-tamper audit logs."""
    res = await db.execute(select(StoreSettings).limit(1))
    s = res.scalars().first()
    logs = []
    if s and s.security_audit_logs:
        try:
            logs = json.loads(s.security_audit_logs)
        except Exception:
            logs = []
    return {"logs": logs}

@router.post("/test-gemini")
async def test_gemini_connection(
    current_user: AdminUser = Depends(get_current_user)
):
    """Verifies that Google Gemini API is responsive."""
    if not gemini_service.client:
        return {
            "status": "error",
            "message": "Gemini API Key არ არის კონფიგურირებული (.env ფაილში GEMINI_API_KEY)."
        }
    try:
        reply = await gemini_service.get_response(
            user_message="მოგესალმები! მითხარი მოკლედ (ერთი წინადადებით), რა ხარ?",
            system_instruction="შენ ხარ ტესტური ასისტენტი. უპასუხე ქართულად მოკლედ."
        )
        if "ტექნიკური შეფერხება" in reply:
            return {
                "status": "error",
                "message": f"Gemini API ტესტი ჩაიშალა: არჩეული მოდელი ({gemini_service.model_name}) მიუწვდომელია. გთხოვთ აირჩიოთ gemini-2.5-flash."
            }
        return {
            "status": "success",
            "model": gemini_service.model_name,
            "reply": reply
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Gemini API ტესტი ჩაიშალა: {str(e)}"
        }

@router.post("/test-email")
async def test_email_connection(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_user)
):
    """Sends a test email to the configured admin_email."""
    from backend.app.services.notifications import send_email_alert
    from datetime import datetime

    res = await db.execute(select(StoreSettings).limit(1))
    s = res.scalars().first()

    to_email = (s.admin_email if s else "") or settings.ADMIN_EMAIL
    host = (s.smtp_host if s else "") or settings.SMTP_HOST

    if not host or not to_email:
        return {
            "status": "error",
            "message": "SMTP პარამეტრები ან ადმინის ელ-ფოსტა არ არის შევსებული (SMTP Host, Admin Email)."
        }

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    subject = "📧 Geosteam - სატესტო შეტყობინება"
    body = (
        f"გამარჯობა!\n\n"
        f"ეს არის Geosteam Vape Store-ის სისტემური სატესტო იმეილი.\n"
        f"თქვენი SMTP სერვერი და ელ-ფოსტა ({to_email}) წარმატებით არის დაკავშირებული!\n\n"
        f"გაგზავნის დრო: {now_str}"
    )
    html_body = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px; background: #f8fafc;">
        <div style="max-width: 500px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 10px; border: 1px solid #e2e8f0;">
            <h2 style="color: #6366f1; margin: 0 0 12px 0;">🎉 SMTP შეტყობინება წარმატებულია!</h2>
            <p style="color: #334155; font-size: 15px;">ეს არის სატესტო იმეილი <strong>Geosteam Admin Panel</strong>-იდან.</p>
            <p style="color: #64748b; font-size: 13px;">ადმინის ელ-ფოსტა: <strong>{to_email}</strong><br>გაგზავნის დრო: {now_str}</p>
        </div>
    </div>
    """

    ok = await send_email_alert(subject=subject, body=body, store_settings=s, html_body=html_body)
    if ok:
        return {
            "status": "success",
            "message": f"სატესტო იმეილი წარმატებით გაიგზავნა მისამართზე: {to_email}"
        }
    else:
        return {
            "status": "error",
            "message": f"იმეილის გაგზავნა ვერ მოხერხდა. გადაამოწმეთ SMTP Host ({host}), Port, მომხმარებელი და პაროლი."
        }

@router.post("/backup/create")
async def trigger_manual_backup(
    current_user: AdminUser = Depends(get_current_user)
):
    """Triggers an immediate database backup and sends it to admin Telegram accounts."""
    from backend.app.services.backup_service import backup_service
    success = await backup_service.send_backup_to_telegram()
    if success:
        return {
            "status": "success",
            "message": "მონაცემთა ბაზის სარეზერვო ასლი (Backup) წარმატებით შეიქმნა და გაიგზავნა თქვენს Telegram-ში!"
        }
    else:
        return {
            "status": "partial_success",
            "message": "სარეზერვო ფაილი შეიქმნა სერვერზე, მაგრამ Telegram-ში გაგზავნისას დაფიქსირდა შეფერხება. შეგიძლიათ ჩამოტვირთოთ ბრაუზერით."
        }

@router.get("/backup/download")
async def download_backup_file(
    current_user: AdminUser = Depends(get_current_user)
):
    """Generates and directly returns the JSON backup file for local download."""
    from fastapi.responses import FileResponse
    from backend.app.services.backup_service import backup_service
    backup_file = await backup_service.create_backup_file()
    return FileResponse(
        path=str(backup_file),
        filename=backup_file.name,
        media_type="application/json"
    )
