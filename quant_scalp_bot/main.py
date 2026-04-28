import os
import logging
from telegram.ext import Application
from db import init_db
from telegram_bot import get_handlers, track_job

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)

TOKEN = os.environ.get(
    "TELEGRAM_TOKEN",
    "8751027463:AAEt_Xg7nR0AAVJyXYkyUgkt6BXFbC_x28o",
)


def main():
    init_db()
    print("✅ DB 초기화 완료")

    app = Application.builder().token(TOKEN).build()

    for handler in get_handlers():
        app.add_handler(handler)

    # 15초마다 보유 종목 매도 신호 감시
    app.job_queue.run_repeating(track_job, interval=15, first=15)

    print("🚀 QuantScalpBot 가동 중 (Ctrl+C 로 종료)")
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
