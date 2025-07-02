import asyncio
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, HttpUrl

router = APIRouter(tags=["payments"])


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0)
    transaction_id: str
    comment: str
    redirect_url: str
    token: str = Field(min_length=1)


async def generate_payment_link_async(
    amount: float,
    transaction_id: str,
    comment: str,
    redirect_url: str,
    token: str
) -> str | None:
    payload = {
        "amount": amount,
        "transactionID": transaction_id,
        "comment": comment,
        "redirectURL": redirect_url
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Authorization": f"Bearer {token}"
    }
    url = "https://openbanking-api.bakai.kg/api/PayLink/CreatePayLink"
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, json=payload, headers=headers)
            if response.status_code == 200 and response.text.strip().startswith("http"):
                return response.text.strip()
            # Если банк ответил ошибкой — не повторять
            break
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            continue
        except Exception as e:
            break
    return None


@router.post("/make-payment-link/")
async def make_payment_link(data: PaymentRequest):
    link = await generate_payment_link_async(
        transaction_id=data.transaction_id,
        amount=data.amount,
        comment=data.comment,
        redirect_url=data.redirect_url,
        token=data.token
    )
    if link:
        return {"pay_url": link}
    raise HTTPException(
        status_code=502,
        detail="Банк временно недоступен или произошла ошибка связи. Попробуйте ещё раз через пару минут."
    )
