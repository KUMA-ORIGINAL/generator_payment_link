from http.client import responses

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
TELEGRAM_TOPIC_ID = os.getenv("TELEGRAM_TOPIC_ID")
PAYMENT_API_TOKEN = os.getenv("PAYMENT_API_TOKEN")
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://example.com/success")

api_is_broken = False

def send_telegram_message(message, retries=3, delay=3):
    """
    Отправка сообщения в Telegram с ретраями при ошибках.
    """
    for attempt in range(retries):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"⚠️ {message}"
            }
            if TELEGRAM_TOPIC_ID:
                payload["message_thread_id"] = TELEGRAM_TOPIC_ID

            response = httpx.post(url, data=payload, timeout=30)
            response.raise_for_status()
            logging.info("📬 Уведомление отправлено в Telegram")
            return True
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение в Telegram (попытка {attempt+1}): {e}")
            time.sleep(delay)
    return False


def handle_api_error(msg):
    global api_is_broken
    if not api_is_broken:
        send_telegram_message(msg)
        api_is_broken = True
    logging.error(msg)


def check_api():
    global api_is_broken
    transaction_id = str(uuid.uuid4())
    payload = {
        "amount": "100.00",
        "transaction_id": transaction_id,
        "comment": "🚀 Health Check",
        "redirect_url": REDIRECT_URL,
        "token": PAYMENT_API_TOKEN
    }
    try:
        response = httpx.post(PAYMENT_API_URL, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        pay_url = data.get("pay_url")
        if not pay_url:
            msg = f"[💳 Ошибка платежной ссылки] ❗ API ответ без 'pay_url'. Код: {response.status_code}, ответ: {data}"
            handle_api_error(msg)
        else:
            if api_is_broken:
                send_telegram_message("[💳 платежная ссылка] ✅ Платежное API восстановилось и работает корректно!")
                api_is_broken = False
            logging.info(f"[💳 платежная ссылка] ✅ API работает. Ссылка: {pay_url}")
    except httpx.HTTPStatusError as e:
        msg = f"[💳 Ошибка платежной ссылки] ❌ API вернул ошибку {e.response.status_code}: {e.response.text}"
        handle_api_error(msg)
    except (httpx.TimeoutException, httpx.RequestError) as e:
        msg = f"[💳 Ошибка платежной ссылки] ❌ Ошибка подключения к API: {str(e)}"
        handle_api_error(msg)
    except Exception as e:
        msg = f"[💳 Ошибка платежной ссылки] ❌ Непредвиденная ошибка при проверке API: {str(e)}"
        handle_api_error(msg)


if __name__ == "__main__":
    logging.info("⏳ Ожидание запуска backend...")
    time.sleep(10)  # Подождать 10 секунд после старта
    logging.info("🔁 Запуск health-check каждые 5 минут...")
    while True:
        check_api()
        time.sleep(300)
