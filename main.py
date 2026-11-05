# main.py
import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from inn_checker.handlers import router as inn_router

# --- НАСТРОЙКИ ---
TOKEN = os.environ.get("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Не задана переменная окружения BOT_TOKEN")

# Render автоматически предоставляет внешний URL в этой переменной
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
if not RENDER_EXTERNAL_URL:
    # Запасной вариант, если переменная не задана (для локального теста)
    RENDER_EXTERNAL_URL = "http://localhost:8080"

WEBHOOK_PATH = "/webhook"
WEBHOOK_URL = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
dp.include_router(inn_router)


@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.answer(
        f"Привет, {message.from_user.first_name}! "
        f"Отправьте ИНН (10 или 12 цифр) — проверю компанию или ИП "
        f"по 8 источникам: ЕГРЮЛ/ЕГРИП, финансы, госзакупки, лизинг, "
        f"банкротство, ФССП, арбитраж и связи."
    )


async def on_startup(bot: Bot):
    # При старте сообщаем Telegram, куда присылать обновления
    await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
    logging.info(f"Вебхук установлен на {WEBHOOK_URL}")


def create_app() -> web.Application:
    app = web.Application()

    # Регистрируем обработчик вебхука от aiogram
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)

    # Health check — сюда будет стучаться UptimeRobot, чтобы Render не засыпал
    async def health(request):
        return web.Response(text="OK")

    app.router.add_get("/health", health)

    # Привязываем startup-хук для установки вебхука
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 8080))
    web.run_app(app, host="0.0.0.0", port=port)
