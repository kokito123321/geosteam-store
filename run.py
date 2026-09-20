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
    print("=" * 60)
    print(f"🚀 {settings.APP_NAME} is starting...")
    print(f"🌐 Dashboard URL: http://localhost:{settings.PORT}/admin")
    print(f"🔑 Default Credentials: admin / admin123")
    print(f"🤖 Bot Polling Mode: {'Enabled' if settings.TELEGRAM_BOT_TOKEN else 'Disabled (Token Missing)'}")
    print(f"🧠 Gemini AI Model: {settings.GEMINI_MODEL}")
    print("=" * 60)
    
    uvicorn.run(
        "backend.app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        workers=1
    )
