import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import uvicorn
from backend.app.config import settings

if __name__ == "__main__":
    port = int(os.environ.get("PORT", getattr(settings, "PORT", 8000) or 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    is_prod = bool(os.environ.get("RENDER")) or (os.environ.get("APP_ENV", "").lower() == "production") or (settings.APP_ENV.lower() == "production")
    reload_mode = False if is_prod else bool(settings.DEBUG)

    print("=" * 60)
    print(f"🚀 {settings.APP_NAME} is starting...")
    print(f"🌐 Listening on: http://{host}:{port}")
    print(f"🔑 Default Credentials: admin / admin123")
    print(f"🤖 Bot Polling Mode: {'Enabled' if settings.TELEGRAM_BOT_TOKEN else 'Disabled (Token Missing)'}")
    print(f"🧠 Gemini AI Model: {settings.GEMINI_MODEL}")
    print("=" * 60)
    
    uvicorn.run(
        "backend.app.main:app",
        host=host,
        port=port,
        reload=reload_mode,
        workers=1
    )
