import asyncio
import logging
from enum import IntEnum

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["payments"])

BAKAI_PAYLINK_URL = "https://openbanking-api.bakai.kg/api/PayLink/CreatePayLink"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class QrTtlUnits(IntEnum):
    """Единицы измерения времени жизни платёжной ссылки."""
    SECONDS = 0
    MINUTES = 1
    HOURS = 2
    DAYS = 3
    MONTHS = 4
    YEARS = 5


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0, description="Сумма платежа", examples=[1500.0])
    transaction_id: str = Field(description="Уникальный ID транзакции на стороне мерчанта", examples=["order-12345"])
    comment: str = Field(description="Комментарий к платежу, отображается в банке", examples=["Оплата заказа #12345"])
    redirect_url: str = Field(description="URL, на который клиент вернётся после оплаты", examples=["https://example.com/success"])
    token: str = Field(min_length=1, description="Bearer-токен OpenBanking API Bakai")
    ttl: int | None = Field(
        None,
        description="Время жизни платёжной ссылки в единицах `ttl_units`. Если не указано — используется значение по умолчанию банка.",
        examples=[60],
    )
    ttl_units: QrTtlUnits | None = Field(
        None,
        description="Единицы измерения `ttl`: 0 — секунды, 1 — минуты, 2 — часы, 3 — дни, 4 — месяцы, 5 — годы.",
        examples=[QrTtlUnits.MINUTES],
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "amount": 1500.0,
                    "transaction_id": "order-12345",
                    "comment": "Оплата заказа #12345",
                    "redirect_url": "https://example.com/success",
                    "token": "eyJhbGciOi...",
                    "ttl": 60,
                    "ttl_units": 1,
                }
            ]
        }
    }


class PaymentResponse(BaseModel):
    pay_url: str = Field(description="Ссылка на оплату, сгенерированная банком", examples=["https://pay.bakai.kg/l/abc123"])


async def generate_payment_link_async(
    amount: float,
    transaction_id: str,
    comment: str,
    redirect_url: str,
    token: str,
    ttl: int | None = None,
    ttl_units: QrTtlUnits | None = None,
) -> str | None:
    payload = {
        "amount": amount,
        "transactionID": transaction_id,
        "comment": comment,
        "redirectURL": redirect_url
    }
    if ttl is not None:
        payload["ttl"] = ttl
    if ttl_units is not None:
        payload["ttlUnits"] = ttl_units.value
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Authorization": f"Bearer {token}"
    }
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                response = await client.post(BAKAI_PAYLINK_URL, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            logger.warning(
                "Payment link request failed (attempt %d/%d, transaction_id=%s): %s",
                attempt, MAX_RETRIES, transaction_id, e
            )
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
            continue
        except Exception:
            logger.exception(
                "Unexpected error while requesting payment link (transaction_id=%s)",
                transaction_id
            )
            return None

        if response.status_code == 200 and response.text.strip().startswith("http"):
            return response.text.strip()

        logger.error(
            "Bank rejected payment link request (transaction_id=%s, status=%d, body=%s)",
            transaction_id, response.status_code, response.text[:500]
        )

        if response.status_code == 200:
            # 200, но тело не похоже на ссылку — банк вернул неожиданный формат,
            # это не ошибка банка в привычном смысле, поэтому не пробрасываем 200 клиенту.
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected response from bank: {response.text.strip()[:500]!r}"
            )

        # Банк возвращает ошибки в формате RFC 9457 Problem Details
        # (например {"type": "...", "title": "Unauthorized", "status": 401, "traceId": "..."}).
        # Пробрасываем их как есть, чтобы клиент видел реальную причину, а не generic 502.
        try:
            detail = response.json()
        except ValueError:
            detail = response.text.strip() or "Bank returned an error"
        raise HTTPException(status_code=response.status_code, detail=detail)

    return None


@router.post(
    "/make-payment-link/",
    response_model=PaymentResponse,
    summary="Создать платёжную ссылку",
    description=(
        "Создаёт платёжную ссылку через OpenBanking API Bakai. "
        "Опциональные поля `ttl`/`ttl_units` задают время жизни ссылки; "
        "если не переданы — банк использует значение по умолчанию."
    ),
    responses={
        401: {
            "description": "Неверный или просроченный токен OpenBanking API (ошибка приходит от банка как есть, RFC 9457 Problem Details)",
            "content": {
                "application/json": {
                    "example": {
                        "detail": {
                            "type": "https://tools.ietf.org/html/rfc9110#section-15.5.2",
                            "title": "Unauthorized",
                            "status": 401,
                            "traceId": "00-224e845f4f2b71a30c522c6b6d2baf35-64b449dcf234cd8b-00",
                        }
                    }
                }
            },
        },
        502: {
            "description": "Банк недоступен, вернул ошибку связи или ответ в неожиданном формате",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Банк временно недоступен или произошла ошибка связи. Попробуйте ещё раз через пару минут."
                    }
                }
            },
        },
    },
)
async def make_payment_link(data: PaymentRequest):
    link = await generate_payment_link_async(
        transaction_id=data.transaction_id,
        amount=data.amount,
        comment=data.comment,
        redirect_url=data.redirect_url,
        token=data.token,
        ttl=data.ttl,
        ttl_units=data.ttl_units,
    )
    if link:
        return {"pay_url": link}
    raise HTTPException(
        status_code=502,
        detail="Банк временно недоступен или произошла ошибка связи. Попробуйте ещё раз через пару минут."
    )
