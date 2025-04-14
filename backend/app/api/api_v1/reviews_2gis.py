import httpx
from fastapi import APIRouter
from config import settings

router = APIRouter(tags=["2gis"])

# === Ваша конфигурация ===
ORG_ID = "70000001051350763"
API_KEY = settings.API_KEY_2GIS

REVIEWS_URL = f"https://public-api.reviews.2gis.com/2.0/orgs/{ORG_ID}/reviews"
FIRST_PARAMS = {
    "key": API_KEY,
    "rated": "true",
    "limit": 50,
    "sort_by": "date_created",
    "fields": "meta.org_rating,meta.org_reviews_count"
}

async def fetch_five_star_reviews():
    async with httpx.AsyncClient() as client:
        reviews_5 = []

        resp = await client.get(REVIEWS_URL, params=FIRST_PARAMS)
        resp.raise_for_status()
        data = resp.json()

        while True:
            for r in data.get("reviews", []):
                if r.get("rating") == 5:
                    reviews_5.append({
                        "id": r.get("id"),
                        "date_created": r.get("date_created"),
                        "date_edited": r.get("date_edited"),
                        "rating": r.get("rating"),
                        "text": (r.get("text") or "").replace("\n", " "),
                        "user_name": r.get("user", {}).get("name"),
                        "comments_count": r.get("comments_count"),
                        "official_answer": (r.get("official_answer") or {}).get("text"),
                    })

            next_link = data.get("meta", {}).get("next_link")
            if not next_link:
                break

            resp = await client.get(next_link)
            resp.raise_for_status()
            data = resp.json()

    return reviews_5

@router.get("/five-star-reviews")
async def get_five_star_reviews():
    reviews = await fetch_five_star_reviews()
    return {"5_star_reviews": reviews}
