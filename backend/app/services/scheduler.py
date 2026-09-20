import asyncio
import logging
from datetime import datetime
from pathlib import Path
from sqlalchemy import select
from backend.app.database import async_session_maker
from backend.app.models import ScheduledPost
from backend.app.bot.bot_instance import bot_manager
from backend.app.config import settings

logger = logging.getLogger(__name__)

class ChannelPostScheduler:
    def __init__(self):
        self._running = False
        self._task: asyncio.Task = None

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("ChannelPostScheduler background worker started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            logger.info("ChannelPostScheduler stopped.")

    async def _run_loop(self):
        while self._running:
            try:
                await self._check_and_publish_due_posts()
            except Exception as e:
                logger.error(f"Error in ChannelPostScheduler loop: {e}", exc_info=True)
            
            # Wait 30 seconds before next check
            await asyncio.sleep(30)

    async def _check_and_publish_due_posts(self):
        if not bot_manager.bot_app or not settings.TELEGRAM_CHANNEL_ID:
            return

        now = datetime.utcnow()
        async with async_session_maker() as session:
            stmt = select(ScheduledPost).where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.scheduled_for <= now
            )
            res = await session.execute(stmt)
            due_posts = res.scalars().all()

            for post in due_posts:
                logger.info(f"Publishing scheduled post #{post.id} to {settings.TELEGRAM_CHANNEL_ID}...")
                try:
                    if post.image_path:
                        if post.image_path.startswith("/static/"):
                            local_file = Path("frontend" + post.image_path)
                            if local_file.exists():
                                with open(local_file, "rb") as pf:
                                    await bot_manager.bot_app.bot.send_photo(
                                        chat_id=settings.TELEGRAM_CHANNEL_ID,
                                        photo=pf,
                                        caption=post.generated_text,
                                        parse_mode="Markdown"
                                    )
                            else:
                                await bot_manager.bot_app.bot.send_message(
                                    chat_id=settings.TELEGRAM_CHANNEL_ID,
                                    text=post.generated_text,
                                    parse_mode="Markdown"
                                )
                        else:
                            await bot_manager.bot_app.bot.send_photo(
                                chat_id=settings.TELEGRAM_CHANNEL_ID,
                                photo=post.image_path,
                                caption=post.generated_text,
                                parse_mode="Markdown"
                            )
                    else:
                        await bot_manager.bot_app.bot.send_message(
                            chat_id=settings.TELEGRAM_CHANNEL_ID,
                            text=post.generated_text,
                            parse_mode="Markdown"
                        )
                    
                    post.status = "published"
                    post.published_at = datetime.utcnow()
                    logger.info(f"Successfully published scheduled post #{post.id}!")
                except Exception as ex:
                    logger.error(f"Failed to publish scheduled post #{post.id}: {ex}")
                    post.status = "failed"
                    post.error_message = str(ex)

            if due_posts:
                await session.commit()

post_scheduler = ChannelPostScheduler()
