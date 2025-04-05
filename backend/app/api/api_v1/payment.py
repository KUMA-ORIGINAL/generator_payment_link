import httpx
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


async def generate_payment_link_async(
    amount: int,
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

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://openbanking-api.bakai.kg/api/PayLink/CreatePayLink",
                json=payload,
                headers=headers,
                timeout=10.0
            )

        logger.info(f"[BANK_API] status={response.status_code}, response={response.text}")

        if response.status_code == 200:
            return response.text.strip()

        logger.error(f"Ошибка внешнего API: {response.text}")
        return None

    except Exception as e:
        logger.exception("Ошибка запроса к банку")
        return None

router = APIRouter(tags=["payments"])


class PaymentRequest(BaseModel):
    amount: int
    transaction_id: str
    comment: str
    redirect_url: str
    token: str


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
    raise HTTPException(status_code=500, detail="Платёжная ссылка не создана")
