from fastapi import APIRouter
from fastapi.responses import Response

from config import settings
from .payment import router as payment_router
from .reviews_2gis import router as reviews_2gis_router

main_router = APIRouter(
    prefix=settings.api.v1.prefix,
)

# Включаем другие роутеры в основной
main_router.include_router(
    payment_router,
    prefix=settings.api.v1.payments
)
main_router.include_router(
    reviews_2gis_router,
    prefix='/2gis'
)

@main_router.head("/health", tags=["system"])
async def health_check():
    return Response(status_code=200)
