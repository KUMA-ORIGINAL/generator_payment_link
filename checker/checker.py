import httpx
import time
import uuid
import os
import logging

# === Настройка логирования ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(),  # Вывод в консоль
    ]
)

# === Настройки ===
PAYMENT_API_URL = os.getenv("PAYMENT_API_URL")  # URL до вашего backend API
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PAYMENT_API_TOKEN = os.getenv("PAYMENT_API_TOKEN")
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://example.com/success")


def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": f"⚠️ {message}"
        }
        httpx.post(url, data=payload)
        logging.info("📬 Уведомление отправлено в Telegram")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение в Telegram: {e}")


def check_api():
    transaction_id = str(uuid.uuid4())
    payload = {
        "amount": "100.00",
        "transaction_id": transaction_id,
        "comment": "🚀 Health Check",
        "redirect_url": REDIRECT_URL,
        "token": PAYMENT_API_TOKEN
    }

    try:
        response = httpx.post(PAYMENT_API_URL, json=payload)
        data = response.json()

        if response.status_code != 200 or "pay_url" not in data:
            msg = f"❗ Ошибка API: {response.status_code}, ответ: {data}"
            send_telegram_message(msg)
            logging.warning(msg)
        else:
            logging.info(f"✅ API работает. Ссылка: {data['pay_url']}")
    except Exception as e:
        msg = f"❌ Ошибка подключения к API: {e}"
        send_telegram_message(msg)
        logging.error(msg)


if __name__ == "__main__":
    logging.info("⏳ Ожидание запуска backend...")
    time.sleep(10)  # Подождать 10 секунд после старта
    logging.info("🔁 Запуск health-check каждые 5 минут...")
    while True:
        check_api()
        time.sleep(300)
