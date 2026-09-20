import asyncio
import logging
from typing import Optional
from telegram import Update
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ChatMemberHandler, filters
)
from backend.app.config import settings
from backend.app.bot.handlers_dm import (
    handle_start, handle_show_catalog, handle_store_info,
    handle_request_operator, handle_callback_query, handle_text_or_multimedia, start_order_workflow,
    handle_admin_command, handle_chat_member_update
)
from backend.app.bot.handlers_channel import handle_channel_post

logger = logging.getLogger(__name__)

class TelegramBotManager:
    def __init__(self):
        self.bot_app: Optional[Application] = None
        self._is_running: bool = False

    def build_app(self) -> Optional[Application]:
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN is not configured. Bot will not start polling.")
            return None

        app = ApplicationBuilder().token(token).build()

        # Commands
        app.add_handler(CommandHandler("start", handle_start))
        app.add_handler(CommandHandler("admin", handle_admin_command))
        app.add_handler(CommandHandler("catalog", handle_show_catalog))
        app.add_handler(CommandHandler("order", start_order_workflow))
        app.add_handler(CommandHandler("info", handle_store_info))
        app.add_handler(CommandHandler("operator", handle_request_operator))

        # Inline Button Callbacks
        app.add_handler(CallbackQueryHandler(handle_callback_query))

        # Channel Post Listener (Auto-Product Ingestion)
        app.add_handler(MessageHandler(filters.ChatType.CHANNEL, handle_channel_post))

        # Channel / Chat Member Updates (Auto-Index Channel Subscribers)
        app.add_handler(ChatMemberHandler(handle_chat_member_update, ChatMemberHandler.CHAT_MEMBER))

        # DM Messages (Text, Location, Contact)
        app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, handle_text_or_multimedia))

        self.bot_app = app
        return self.bot_app

    async def start(self):
        """Starts the bot in async mode alongside FastAPI."""
        if not self.bot_app:
            self.build_app()

        if not self.bot_app:
            logger.warning("Cannot start Telegram bot: application not built (check token).")
            return

        try:
            logger.info("Starting Telegram Bot polling...")
            await self.bot_app.initialize()
            await self.bot_app.start()
            await self.bot_app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES
            )
            self._is_running = True
            logger.info("Telegram Bot is running and polling for updates!")
        except Exception as e:
            logger.error(f"Error starting Telegram bot: {e}", exc_info=True)

    async def stop(self):
        """Gracefully stops the bot."""
        if self.bot_app and self._is_running:
            logger.info("Stopping Telegram Bot...")
            try:
                await self.bot_app.updater.stop()
                await self.bot_app.stop()
                await self.bot_app.shutdown()
                self._is_running = False
                logger.info("Telegram Bot stopped successfully.")
            except Exception as e:
                logger.error(f"Error shutting down Telegram bot: {e}")

bot_manager = TelegramBotManager()
