import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    # App Settings
    APP_NAME: str = "Telegram AI Vape Store"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000
    HOST: str = "0.0.0.0"
    SECRET_KEY: str = "change-this-to-a-super-secret-key-in-production-12345"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 days
    
    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHANNEL_ID: str = "" # e.g. @your_channel or -100xxxxxxxxxx
    ADMIN_TELEGRAM_IDS: str = "" # Comma-separated list of admin telegram user IDs (e.g. "12345678,87654321")
    WEBAPP_URL: str = "https://geosteam-store.onrender.com/admin"
    
    # Google Gemini AI & Google Cloud Vertex AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.0-flash"
    USE_VERTEX_AI: bool = False
    GCP_PROJECT_ID: str = ""
    GCP_LOCATION: str = "global"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    
    # Database
    DATABASE_URL: str = f"sqlite+aiosqlite:///{BASE_DIR / 'store.db'}"
    
    # Email / SMTP
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    ADMIN_EMAIL: str = ""
    
    # Defaults for store
    STORE_NAME: str = "Geosteam / ჯეოსტიმი"
    STORE_LOCATION_ADDRESS: str = "თბილისი, რუსთაველის გამზირი #1"
    STORE_LOCATION_LAT: float = 41.6938
    STORE_LOCATION_LNG: float = 44.8015
    STORE_BANK_NAME: str = "TBC Bank"
    STORE_IBAN: str = "GE00TB0000000000000000"
    STORE_RECIPIENT_NAME: str = "Geosteam"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
