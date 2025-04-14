from fastapi import APIRouter

from config import settings

from .payment import router as payment_router
from .reviews_2gis import router as reviews_2gis_router

router = APIRouter(
    prefix=settings.api.v1.prefix,
)
router.include_router(
    payment_router,
    prefix=settings.api.v1.payments
)
router.include_router(
    reviews_2gis_router,
    prefix='/2gis'
)