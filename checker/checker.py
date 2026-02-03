"""
Payment API Health Checker
Периодически проверяет работоспособность платежного API и отправляет уведомления в Telegram.
"""
import httpx
import time
import uuid
import os
import logging
import signal
import sys
from typing import Optional, Dict, Any
from contextlib import contextmanager
from playwright.sync_api import sync_playwright, Browser, Page, Error as PlaywrightError

# === Настройка логирования ===
# Используем sys.stdout для гарантии вывода логов в Docker/консоль без буферизации
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)

# === Константы ===
DEFAULT_CHECK_INTERVAL = 300  # 5 минут
ERROR_CHECK_INTERVAL = 60     # 1 минута при ошибках
STARTUP_DELAY = 10            # Задержка перед первой проверкой
TELEGRAM_RETRY_COUNT = 3
TELEGRAM_RETRY_DELAY = 3
HTTP_TIMEOUT = 30
BROWSER_TIMEOUT = 45000
PAGE_LOAD_WAIT = 3000

# === Настройки из переменных окружения ===
PAYMENT_API_URL = os.getenv("PAYMENT_API_URL")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_TOPIC_ID = os.getenv("TELEGRAM_TOPIC_ID")
PAYMENT_API_TOKEN = os.getenv("PAYMENT_API_TOKEN")
REDIRECT_URL = os.getenv("REDIRECT_URL", "https://example.com/success")

# === Глобальное состояние ===
class CheckerState:
    """Состояние checker'а."""
    def __init__(self):
        self.running = True
        self.api_is_broken = False
        self.check_interval = DEFAULT_CHECK_INTERVAL
        self.consecutive_errors = 0
        self.consecutive_successes = 0
    
    def reset_to_normal(self):
        """Сброс состояния к нормальному режиму."""
        self.api_is_broken = False
        self.check_interval = DEFAULT_CHECK_INTERVAL
        self.consecutive_errors = 0
        self.consecutive_successes = 0
    
    def mark_error(self):
        """Отметить ошибку."""
        self.consecutive_errors += 1
        self.consecutive_successes = 0
        if not self.api_is_broken:
            self.api_is_broken = True
            self.check_interval = ERROR_CHECK_INTERVAL
    
    def mark_success(self):
        """Отметить успех."""
        self.consecutive_successes += 1
        self.consecutive_errors = 0

state = CheckerState()


def signal_handler(signum: int, frame) -> None:
    """Обработчик сигналов для корректного завершения."""
    logger.info(f"🛑 Получен сигнал {signum}. Завершаем работу...")
    state.running = False


# Регистрируем обработчики сигналов
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def send_telegram_message(message: str, retries: int = TELEGRAM_RETRY_COUNT, delay: int = TELEGRAM_RETRY_DELAY) -> bool:
    """
    Отправка сообщения в Telegram с ретраями при ошибках.
    
    Args:
        message: Текст сообщения
        retries: Количество попыток
        delay: Задержка между попытками в секундах
    
    Returns:
        True если сообщение отправлено успешно, иначе False
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Telegram не настроен (отсутствует TOKEN или CHAT_ID)")
        return False
    
    for attempt in range(1, retries + 1):
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            payload: Dict[str, Any] = {
                "chat_id": TELEGRAM_CHAT_ID,
                "text": f"⚠️ {message}",
                "parse_mode": "HTML"
            }
            if TELEGRAM_TOPIC_ID:
                payload["message_thread_id"] = TELEGRAM_TOPIC_ID

            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
            
            logger.info("📬 Уведомление отправлено в Telegram")
            return True
            
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Telegram API вернул ошибку {e.response.status_code} (попытка {attempt}/{retries})")
        except httpx.RequestError as e:
            logger.error(f"❌ Ошибка подключения к Telegram (попытка {attempt}/{retries}): {e}")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка при отправке в Telegram (попытка {attempt}/{retries}): {e}")
        
        if attempt < retries:
            time.sleep(delay)
    
    logger.error("❌ Не удалось отправить сообщение в Telegram после всех попыток")
    return False


def handle_api_error(msg: str) -> None:
    """
    Обработка ошибки API.
    
    Args:
        msg: Сообщение об ошибке
    """
    logger.error(msg)
    state.mark_error()
    
    # Отправляем уведомление только при первой ошибке или каждой 10-й подряд
    if state.consecutive_errors == 1 or state.consecutive_errors % 10 == 0:
        error_context = f" (ошибка #{state.consecutive_errors})" if state.consecutive_errors > 1 else ""
        send_telegram_message(f"{msg}{error_context}")
        
        if state.consecutive_errors == 1:
            logger.info(f"⏱ Переключаем health-check на каждые {ERROR_CHECK_INTERVAL} секунд")


@contextmanager
def get_browser():
    """Контекстный менеджер для безопасной работы с браузером."""
    playwright = None
    browser = None
    try:
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']  # Для Docker
        )
        yield browser
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске браузера: {e}")
        raise
    finally:
        if browser:
            try:
                browser.close()
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при закрытии браузера: {e}")
        if playwright:
            try:
                playwright.stop()
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при остановке Playwright: {e}")


def check_link(url: str) -> tuple[bool, str]:
    """
    Проверяет доступность ссылки через браузер.
    
    Args:
        url: URL для проверки
    
    Returns:
        Кортеж (успех, сообщение)
    """
    try:
        with get_browser() as browser:
            page = browser.new_page()
            try:
                logger.debug(f"🌐 Открываем страницу: {url}")
                page.goto(url, timeout=BROWSER_TIMEOUT, wait_until="domcontentloaded")
                page.wait_for_timeout(PAGE_LOAD_WAIT)
                html = page.content().lower()
                
                # Проверяем на наличие ошибок 404
                error_indicators = ["app-not-found", "page not found", "assets/404.svg", "error-404", "404 not found"]
                if any(indicator in html for indicator in error_indicators):
                    return False, f"Страница не найдена (SPA 404)"
                
                # Проверяем, что страница не пустая
                if len(html.strip()) < 100:
                    return False, f"Страница слишком короткая (возможно, пустая)"
                
                return True, "Страница открывается корректно"
                
            finally:
                try:
                    page.close()
                except Exception:
                    pass
                    
    except PlaywrightError as e:
        return False, f"Ошибка Playwright: {str(e)}"
    except Exception as e:
        return False, f"Неожиданная ошибка при проверке: {str(e)}"


def check_api_cycle() -> None:
    """Один цикл проверки API."""
    transaction_id = str(uuid.uuid4())
    payload = {
        "amount": "100.00",
        "transaction_id": transaction_id,
        "comment": "🚀 Health Check",
        "redirect_url": REDIRECT_URL,
        "token": PAYMENT_API_TOKEN
    }
    
    try:
        logger.info("📡 Отправляем запрос к Payment API...")
        
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            response = client.post(PAYMENT_API_URL, json=payload)
            response.raise_for_status()
            data = response.json()
        
        pay_url = data.get("pay_url")
        if not pay_url:
            msg = f"[💳 Ошибка] API ответ без 'pay_url'. Код: {response.status_code}, ответ: {data}"
            handle_api_error(msg)
            return

        logger.info(f"🔗 Получена ссылка: {pay_url}")
        logger.info("🌐 Проверяем доступность страницы...")
        
        success, message = check_link(pay_url)
        
        if not success:
            handle_api_error(f"[💳 Ошибка ссылки] {message}: {pay_url}")
            return
        
        # Успешная проверка
        state.mark_success()
        logger.info(f"✅ {message}")
        
        # Если API восстановилось после ошибок
        if state.api_is_broken and state.consecutive_successes >= 2:
            send_telegram_message(
                f"[💳 Восстановление] ✅ Платежное API восстановилось после {state.consecutive_errors} ошибок!"
            )
            state.reset_to_normal()
            logger.info(f"⏱ Переключаем health-check обратно на каждые {DEFAULT_CHECK_INTERVAL} секунд")
        
        logger.info("[💳 Health Check] ✅ Все системы работают корректно")

    except httpx.HTTPStatusError as e:
        error_text = e.response.text[:200] if e.response.text else "нет тела ответа"
        msg = f"[💳 HTTP Ошибка] API вернул {e.response.status_code}: {error_text}"
        handle_api_error(msg)
        
    except httpx.TimeoutException:
        msg = f"[💳 Timeout] Превышено время ожидания ответа от API ({HTTP_TIMEOUT}s)"
        handle_api_error(msg)
        
    except httpx.RequestError as e:
        msg = f"[💳 Сетевая ошибка] Не удалось подключиться к API: {type(e).__name__}"
        handle_api_error(msg)
        
    except ValueError as e:
        msg = f"[💳 Ошибка данных] Невалидный JSON в ответе API: {str(e)}"
        handle_api_error(msg)
        
    except Exception as e:
        msg = f"[💳 Непредвиденная ошибка] {type(e).__name__}: {str(e)}"
        handle_api_error(msg)
        logger.exception("Детали ошибки:")


def validate_config() -> bool:
    """
    Проверяет наличие всех необходимых переменных окружения.
    
    Returns:
        True если конфигурация валидна, иначе False
    """
    required_vars = {
        "PAYMENT_API_URL": PAYMENT_API_URL,
        "PAYMENT_API_TOKEN": PAYMENT_API_TOKEN,
    }
    
    missing = [name for name, value in required_vars.items() if not value]
    
    if missing:
        logger.error(f"❌ Отсутствуют обязательные переменные окружения: {', '.join(missing)}")
        logger.error("💡 Проверьте файл .env")
        return False
    
    # Предупреждения о необязательных переменных
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("⚠️ Telegram уведомления не настроены (отсутствует TELEGRAM_TOKEN или TELEGRAM_CHAT_ID)")
    
    logger.info("✅ Конфигурация валидна")
    logger.info(f"📍 API URL: {PAYMENT_API_URL}")
    logger.info(f"📍 Redirect URL: {REDIRECT_URL}")
    
    return True


def interruptible_sleep(seconds: int) -> None:
    """
    Сон с возможностью прерывания по сигналу.
    
    Args:
        seconds: Количество секунд для сна
    """
    for _ in range(seconds):
        if not state.running:
            break
        time.sleep(1)


def main() -> None:
    """Главная функция запуска checker'а."""
    logger.info("=" * 60)
    logger.info("🚀 Payment API Health Checker")
    logger.info("=" * 60)
    
    # Валидация конфигурации
    if not validate_config():
        logger.error("❌ Запуск невозможен из-за ошибок конфигурации")
        sys.exit(1)
    
    # Начальная задержка
    logger.info(f"⏳ Ожидание запуска backend ({STARTUP_DELAY} сек)...")
    interruptible_sleep(STARTUP_DELAY)
    
    if not state.running:
        logger.info("🛑 Остановка до начала проверок")
        return
    
    logger.info(f"🔄 Запуск цикла проверок (интервал: {DEFAULT_CHECK_INTERVAL} сек)")
    logger.info("=" * 60)
    
    check_count = 0
    
    while state.running:
        check_count += 1
        logger.info(f"\n{'=' * 60}")
        logger.info(f"🔍 Проверка #{check_count}")
        logger.info(f"{'=' * 60}")
        
        try:
            check_api_cycle()
        except Exception as e:
            # Последняя линия защиты - ловим всё
            logger.critical(f"🔥 КРИТИЧЕСКАЯ ОШИБКА В ЦИКЛЕ ПРОВЕРКИ: {e}", exc_info=True)
            send_telegram_message(f"🔥 Checker: критическая ошибка в цикле #{check_count}: {type(e).__name__}")
            
            # Увеличиваем интервал при критических ошибках
            error_sleep = min(ERROR_CHECK_INTERVAL * 2, 300)
            logger.info(f"⏸ Ожидание {error_sleep} сек перед повторной попыткой...")
            interruptible_sleep(error_sleep)
            continue
        
        # Ожидание перед следующей проверкой
        if state.running:
            logger.info(f"💤 Следующая проверка через {state.check_interval} сек...")
            interruptible_sleep(state.check_interval)
    
    logger.info("=" * 60)
    logger.info("👋 Checker корректно остановлен")
    logger.info(f"📊 Всего выполнено проверок: {check_count}")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 Остановка по Ctrl+C")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"💀 Фатальная ошибка при запуске: {e}", exc_info=True)
        send_telegram_message(f"💀 Checker: фатальная ошибка при запуске: {type(e).__name__}")
        sys.exit(1)
