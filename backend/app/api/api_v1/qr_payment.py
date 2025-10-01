import asyncio
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

router = APIRouter(tags=["qr-payments"])


class QRPaymentRequest(BaseModel):
    account_number: str = Field(..., regex=r"^124\d+", description="Счёт, начинающийся с 124")
    qr_merchant_id: str = Field(..., max_length=32)
    recipient: str = Field(..., max_length=255)
    amount: float | None = Field(None, gt=0, description="Сумма в тыйынах, >0")
    currency: str = Field("KGS", description="По умолчанию KGS")
    ttl: int | None = Field(3600, le=63072000, description="В секундах, по умолчанию 3600")
    transaction_id: str | None = None
    qr_comment: str | None = Field(None, max_length=99)
    success_url: HttpUrl | None = None
    fail_url: HttpUrl | None = None


async def generate_qr_payment_link_async(
    data: QRPaymentRequest,
    test_mode: bool = True
) -> dict | None:
    url_base = "https://qrpay-test.bakai.kg" if test_mode else "https://qrpay.bakai.kg"
    url = f"{url_base}/api/v1/qr/generate"

    payload = {
        "account_number": data.account_number,
        "qr_merchant_id": data.qr_merchant_id,
        "recipient": data.recipient,
        "amount": data.amount,
        "currency": data.currency,
        "ttl": data.ttl,
        "transaction_id": data.transaction_id,
        "qr_comment": data.qr_comment,
        "success_url": str(data.success_url) if data.success_url else None,
        "fail_url": str(data.fail_url) if data.fail_url else None,
    }

    payload = {k: v for k, v in payload.items() if v is not None}

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                return response.json()
            elif response.status_code in (400, 404, 409, 500):
                # Ошибка со стороны банка — не повторяем
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.json()
                )
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected response: {response.text}"
            )

        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            continue
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return None


@router.post("/generate-qr/")
async def generate_qr(data: QRPaymentRequest, test_mode: bool = True):
    result = await generate_qr_payment_link_async(data, test_mode=test_mode)
    if result:
        return result
    raise HTTPException(
        status_code=502,
        detail="QR-сервис временно недоступен. Попробуйте позже."
    )
