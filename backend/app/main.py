import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse

from backend.app.config import settings
from backend.app.database import init_db
from backend.app.bot.bot_instance import bot_manager
from backend.app.routers import (
    api_auth, api_products, api_orders, api_chat, api_settings, api_marketing, api_assistant,
    api_blacklist, api_dashboard
)

from backend.app.services.scheduler import post_scheduler

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
(FRONTEND_DIR / "static" / "uploads" / "receipts").mkdir(parents=True, exist_ok=True)
(FRONTEND_DIR / "static" / "uploads" / "posts").mkdir(parents=True, exist_ok=True)
(FRONTEND_DIR / "static" / "uploads" / "chat_media").mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting up Telegram AI Store Application...")
    await init_db()
    logger.info("Database initialized.")

    # Start Telegram bot polling in background
    if settings.TELEGRAM_BOT_TOKEN:
        await bot_manager.start()
        post_scheduler.start()
    else:
        logger.warning("No TELEGRAM_BOT_TOKEN provided. Telegram bot is idle.")

    yield

    # Shutdown
    logger.info("Shutting down...")
    await post_scheduler.stop()
    await bot_manager.stop()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for Telegram WebApp
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files & Templates
static_path = FRONTEND_DIR / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

templates_path = FRONTEND_DIR / "templates"
templates_path.mkdir(parents=True, exist_ok=True)
templates = Jinja2Templates(directory=str(templates_path))

# Include Routers
app.include_router(api_auth.router)
app.include_router(api_products.router)
app.include_router(api_orders.router)
app.include_router(api_chat.router)
app.include_router(api_settings.router)
app.include_router(api_marketing.router)
app.include_router(api_assistant.router)
app.include_router(api_blacklist.router)
app.include_router(api_dashboard.router)

@app.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse(url="/admin")

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"app_name": settings.APP_NAME}
    )

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.APP_NAME,
            "host": settings.HOST,
            "port": settings.PORT
        }
    )

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "bot_active": bot_manager._is_running
    }

@app.get("/api/debug-ai")
async def debug_ai():
    from backend.app.ai.gemini_client import gemini_service
    client_status = bool(gemini_service.client)
    api_key_len = len(settings.GEMINI_API_KEY) if settings.GEMINI_API_KEY else 0
    test_result = None
    working_model = None
    error_msg = None
    try:
        if gemini_service.client:
            for m in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]:
                try:
                    resp = await gemini_service.client.aio.models.generate_content(
                        model=m,
                        contents="Hello, reply with 1 word: OK"
                    )
                    if resp and resp.text:
                        test_result = resp.text.strip()
                        working_model = m
                        gemini_service.model_name = m
                        break
                except Exception as mex:
                    error_msg = f"{m} failed: {mex}"
        else:
            error_msg = "Client is None (GEMINI_API_KEY not configured or empty)"
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}"

    return {
        "client_initialized": client_status,
        "api_key_present": api_key_len > 0,
        "api_key_masked": f"{settings.GEMINI_API_KEY[:6]}...{settings.GEMINI_API_KEY[-4:]}" if api_key_len > 10 else "",
        "active_model": working_model or gemini_service.model_name,
        "test_result": test_result,
        "error": error_msg if not test_result else None
    }
