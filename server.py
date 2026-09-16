from dotenv import load_dotenv
from pathlib import Path
import os

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Request, Query
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import logging
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
import re
import jwt
import bcrypt
from datetime import datetime, timezone, timedelta

# ------------------- DB -------------------
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

app = FastAPI(title="AUREN API")
api_router = APIRouter(prefix="/api")

JWT_ALGORITHM = "HS256"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=7),
        "type": "access",
    }
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


async def get_current_admin(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = await db.users.find_one({"id": payload["sub"]})
    if not user or user.get("role") != "admin":
        raise HTTPException(status_code=401, detail="Admin not found")
    user.pop("password_hash", None)
    user.pop("_id", None)
    return user


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s or "product"


# ------------------- Models -------------------
class LoginInput(BaseModel):
    email: str
    password: str


class Notes(BaseModel):
    top: List[str] = []
    heart: List[str] = []
    base: List[str] = []


class ProductInput(BaseModel):
    name: str
    brand: str
    price: int
    original_price: Optional[int] = None
    size: str = ""
    condition: str = ""
    remaining_percentage: Optional[int] = None
    description: str = ""
    notes: Notes = Field(default_factory=Notes)
    categories: List[str] = []
    gender: str = "Unisex"
    seller_type: str = "AUREN"  # AUREN | Community Seller
    seller_name: str = "AUREN"
    stock: int = 1
    status: str = "Available"  # Available | Reserved | Sold
    featured: bool = False
    badges: List[str] = []
    photos: List[str] = []
    verified: Optional[str] = None  # e.g. "Verified by AUREN"
    from_submission: Optional[str] = None


class SubmissionInput(BaseModel):
    seller_name: str
    phone: str
    instagram: Optional[str] = ""
    location: str = ""
    contact_method: str = "WhatsApp"
    perfume_name: str
    brand: str
    size: str = ""
    condition: str = ""
    remaining_percentage: Optional[int] = None
    asking_price: int
    box_available: bool = False
    proof_available: bool = False
    description: str = ""
    photos: List[str] = []


class SubmissionStatusInput(BaseModel):
    status: str
    admin_note: Optional[str] = None


class InterestInput(BaseModel):
    product_id: str
    buyer_name: str
    buyer_contact: str
    message: Optional[str] = ""


class ContactInput(BaseModel):
    name: str
    contact: str
    subject: str = ""
    message: str


class StatusUpdate(BaseModel):
    status: str


# ------------------- Auth routes -------------------
@api_router.post("/auth/login")
async def login(data: LoginInput):
    user = await db.users.find_one({"email": data.email.lower().strip()})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Email atau password salah")
    token = create_token(user["id"], user["email"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "name": user.get("name"), "role": user.get("role")},
    }


@api_router.get("/auth/me")
async def me(admin: dict = Depends(get_current_admin)):
    return admin


@api_router.post("/auth/logout")
async def logout():
    return {"ok": True}


# ------------------- Product routes -------------------
async def unique_slug(name: str, brand: str) -> str:
    base = slugify(f"{brand}-{name}")
    slug = base
    i = 1
    while await db.products.find_one({"slug": slug}):
        i += 1
        slug = f"{base}-{i}"
    return slug


def product_public(doc: dict) -> dict:
    doc.pop("_id", None)
    return doc


@api_router.get("/products")
async def list_products(
    search: Optional[str] = None,
    brand: Optional[str] = None,
    category: Optional[str] = None,
    gender: Optional[str] = None,
    condition: Optional[str] = None,
    size: Optional[str] = None,
    seller_type: Optional[str] = None,
    status: Optional[str] = None,
    featured: Optional[bool] = None,
    min_price: Optional[int] = None,
    max_price: Optional[int] = None,
    sort: str = "newest",
    page: int = 1,
    limit: int = 12,
):
    q: Dict[str, Any] = {}
    if search:
        rx = {"$regex": re.escape(search), "$options": "i"}
        q["$or"] = [
            {"name": rx}, {"brand": rx}, {"description": rx},
            {"categories": rx}, {"notes.top": rx}, {"notes.heart": rx}, {"notes.base": rx},
        ]
    if brand:
        q["brand"] = brand
    if category and category != "All Perfume":
        q["categories"] = category
    if gender:
        q["gender"] = gender
    if condition:
        q["condition"] = condition
    if size:
        q["size"] = size
    if seller_type:
        q["seller_type"] = seller_type
    if status:
        q["status"] = status
    if featured is not None:
        q["featured"] = featured
    if min_price is not None or max_price is not None:
        pr: Dict[str, Any] = {}
        if min_price is not None:
            pr["$gte"] = min_price
        if max_price is not None:
            pr["$lte"] = max_price
        q["price"] = pr

    sort_map = {
        "newest": [("created_at", -1)],
        "price_asc": [("price", 1)],
        "price_desc": [("price", -1)],
        "popular": [("views", -1)],
    }
    sort_spec = sort_map.get(sort, [("created_at", -1)])

    total = await db.products.count_documents(q)
    skip = (page - 1) * limit
    cursor = db.products.find(q).sort(sort_spec).skip(skip).limit(limit)
    items = [product_public(d) async for d in cursor]
    return {"items": items, "total": total, "page": page, "pages": max(1, (total + limit - 1) // limit)}


@api_router.get("/brands")
async def brands():
    vals = await db.products.distinct("brand")
    return sorted([v for v in vals if v])


@api_router.get("/sizes")
async def sizes():
    vals = await db.products.distinct("size")
    return sorted([v for v in vals if v])


@api_router.get("/products/{id_or_slug}")
async def get_product(id_or_slug: str):
    doc = await db.products.find_one({"$or": [{"id": id_or_slug}, {"slug": id_or_slug}]})
    if not doc:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return product_public(doc)


@api_router.post("/products/{product_id}/view")
async def add_view(product_id: str):
    await db.products.update_one({"id": product_id}, {"$inc": {"views": 1}})
    return {"ok": True}


@api_router.post("/products")
async def create_product(data: ProductInput, admin: dict = Depends(get_current_admin)):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["slug"] = await unique_slug(data.name, data.brand)
    doc["views"] = 0
    doc["interested_count"] = 0
    doc["created_at"] = now_iso()
    await db.products.insert_one(doc)
    return product_public(doc)


@api_router.put("/products/{product_id}")
async def update_product(product_id: str, data: ProductInput, admin: dict = Depends(get_current_admin)):
    existing = await db.products.find_one({"id": product_id})
    if not existing:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    doc = data.model_dump()
    if doc["name"] != existing["name"] or doc["brand"] != existing["brand"]:
        doc["slug"] = await unique_slug(data.name, data.brand)
    await db.products.update_one({"id": product_id}, {"$set": doc})
    updated = await db.products.find_one({"id": product_id})
    return product_public(updated)


@api_router.patch("/products/{product_id}/status")
async def set_product_status(product_id: str, data: StatusUpdate, admin: dict = Depends(get_current_admin)):
    res = await db.products.update_one({"id": product_id}, {"$set": {"status": data.status}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    return {"ok": True}


@api_router.delete("/products/{product_id}")
async def delete_product(product_id: str, admin: dict = Depends(get_current_admin)):
    await db.products.delete_one({"id": product_id})
    return {"ok": True}


# ------------------- Submission routes -------------------
def gen_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6].upper()}"


@api_router.post("/submissions")
async def create_submission(data: SubmissionInput):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["ref"] = gen_ref("AUR")
    doc["status"] = "Submitted"
    doc["admin_note"] = None
    doc["created_at"] = now_iso()
    await db.submissions.insert_one(doc)
    return {"id": doc["id"], "ref": doc["ref"], "status": doc["status"]}


@api_router.get("/submissions/track")
async def track_submission(ref: str, phone: str):
    doc = await db.submissions.find_one({"ref": ref.strip().upper(), "phone": phone.strip()})
    if not doc:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan. Periksa Listing ID dan nomor kontak.")
    return {
        "ref": doc["ref"],
        "perfume_name": doc["perfume_name"],
        "brand": doc["brand"],
        "status": doc["status"],
        "admin_note": doc.get("admin_note"),
        "created_at": doc["created_at"],
    }


@api_router.get("/submissions")
async def list_submissions(status: Optional[str] = None, admin: dict = Depends(get_current_admin)):
    q = {"status": status} if status else {}
    cursor = db.submissions.find(q).sort([("created_at", -1)])
    return [product_public(d) async for d in cursor]


@api_router.patch("/submissions/{sub_id}")
async def update_submission(sub_id: str, data: SubmissionStatusInput, admin: dict = Depends(get_current_admin)):
    update = {"status": data.status}
    if data.admin_note is not None:
        update["admin_note"] = data.admin_note
    res = await db.submissions.update_one({"id": sub_id}, {"$set": update})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    return {"ok": True}


@api_router.post("/submissions/{sub_id}/create-product")
async def create_product_from_submission(sub_id: str, admin: dict = Depends(get_current_admin)):
    sub = await db.submissions.find_one({"id": sub_id})
    if not sub:
        raise HTTPException(status_code=404, detail="Pengajuan tidak ditemukan")
    cats = ["Preloved"] if (sub.get("remaining_percentage") or 100) < 100 else ["New"]
    doc = {
        "id": str(uuid.uuid4()),
        "name": sub["perfume_name"],
        "brand": sub["brand"],
        "price": sub["asking_price"],
        "original_price": None,
        "size": sub.get("size", ""),
        "condition": sub.get("condition", ""),
        "remaining_percentage": sub.get("remaining_percentage"),
        "description": sub.get("description", ""),
        "notes": {"top": [], "heart": [], "base": []},
        "categories": cats,
        "gender": "Unisex",
        "seller_type": "Community Seller",
        "seller_name": "Community Seller",
        "stock": 1,
        "status": "Available",
        "featured": False,
        "badges": ["Preloved"] if "Preloved" in cats else ["New"],
        "photos": sub.get("photos", []),
        "verified": None,
        "from_submission": sub_id,
        "views": 0,
        "interested_count": 0,
    }
    doc["slug"] = await unique_slug(doc["name"], doc["brand"])
    doc["created_at"] = now_iso()
    await db.products.insert_one(doc)
    await db.submissions.update_one({"id": sub_id}, {"$set": {"status": "Listed", "product_id": doc["id"]}})
    return product_public(doc)


# ------------------- Interest routes -------------------
@api_router.post("/interests")
async def create_interest(data: InterestInput):
    product = await db.products.find_one({"id": data.product_id})
    if not product:
        raise HTTPException(status_code=404, detail="Produk tidak ditemukan")
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["product_name"] = product["name"]
    doc["status"] = "New"
    doc["created_at"] = now_iso()
    await db.interests.insert_one(doc)
    await db.products.update_one({"id": data.product_id}, {"$inc": {"interested_count": 1}})
    return {"ok": True, "id": doc["id"]}


@api_router.get("/interests")
async def list_interests(admin: dict = Depends(get_current_admin)):
    cursor = db.interests.find({}).sort([("created_at", -1)])
    return [product_public(d) async for d in cursor]


@api_router.patch("/interests/{interest_id}")
async def update_interest(interest_id: str, data: StatusUpdate, admin: dict = Depends(get_current_admin)):
    res = await db.interests.update_one({"id": interest_id}, {"$set": {"status": data.status}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ------------------- Contact routes -------------------
@api_router.post("/contacts")
async def create_contact(data: ContactInput):
    doc = data.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["status"] = "New"
    doc["created_at"] = now_iso()
    await db.contacts.insert_one(doc)
    return {"ok": True}


@api_router.get("/contacts")
async def list_contacts(admin: dict = Depends(get_current_admin)):
    cursor = db.contacts.find({}).sort([("created_at", -1)])
    return [product_public(d) async for d in cursor]


@api_router.patch("/contacts/{contact_id}")
async def update_contact(contact_id: str, data: StatusUpdate, admin: dict = Depends(get_current_admin)):
    await db.contacts.update_one({"id": contact_id}, {"$set": {"status": data.status}})
    return {"ok": True}


# ------------------- Admin overview -------------------
@api_router.get("/admin/overview")
async def overview(admin: dict = Depends(get_current_admin)):
    total_products = await db.products.count_documents({})
    available = await db.products.count_documents({"status": "Available"})
    sold = await db.products.count_documents({"status": "Sold"})
    reserved = await db.products.count_documents({"status": "Reserved"})
    pending_sub = await db.submissions.count_documents({"status": {"$in": ["Submitted", "Under Review"]}})
    accepted_sub = await db.submissions.count_documents({"status": {"$in": ["Accepted", "Listed"]}})
    total_sellers = len(await db.submissions.distinct("phone"))
    new_interests = await db.interests.count_documents({"status": "New"})
    new_contacts = await db.contacts.count_documents({"status": "New"})
    total_views = 0
    async for p in db.products.find({}, {"views": 1}):
        total_views += p.get("views", 0)
    total_interested = await db.interests.count_documents({})
    return {
        "total_products": total_products,
        "available_products": available,
        "sold_products": sold,
        "reserved_products": reserved,
        "pending_submissions": pending_sub,
        "accepted_submissions": accepted_sub,
        "total_sellers": total_sellers,
        "new_interests": new_interests,
        "new_contacts": new_contacts,
        "total_views": total_views,
        "total_interested": total_interested,
    }


@api_router.get("/admin/notifications")
async def notifications(admin: dict = Depends(get_current_admin)):
    return {
        "new_submissions": await db.submissions.count_documents({"status": "Submitted"}),
        "new_interests": await db.interests.count_documents({"status": "New"}),
        "new_contacts": await db.contacts.count_documents({"status": "New"}),
    }


class AnnouncementInput(BaseModel):
    enabled: bool = True
    text: str = ""
    bg_color: str = "#121212"
    text_color: str = "#C5A059"
    link: Optional[str] = ""


@api_router.get("/settings/announcement")
async def get_announcement():
    doc = await db.settings.find_one({"key": "announcement"})
    if not doc:
        return {"enabled": False, "text": "", "bg_color": "#121212", "text_color": "#C5A059", "link": ""}
    doc.pop("_id", None)
    doc.pop("key", None)
    return doc


@api_router.put("/settings/announcement")
async def update_announcement(data: AnnouncementInput, admin: dict = Depends(get_current_admin)):
    await db.settings.update_one(
        {"key": "announcement"},
        {"$set": {**data.model_dump(), "key": "announcement"}},
        upsert=True,
    )
    return {"ok": True}


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ------------------- Seeding -------------------
async def seed_admin():
    email = os.environ["ADMIN_EMAIL"].lower().strip()
    password = os.environ["ADMIN_PASSWORD"]
    existing = await db.users.find_one({"email": email})
    if not existing:
        await db.users.insert_one({
            "id": str(uuid.uuid4()),
            "email": email,
            "password_hash": hash_password(password),
            "name": os.environ.get("ADMIN_NAME", "Admin"),
            "role": "admin",
            "created_at": now_iso(),
        })
        logger.info("Seeded admin user")
    elif not verify_password(password, existing.get("password_hash", "")):
        await db.users.update_one({"email": email}, {"$set": {"password_hash": hash_password(password)}})


SAMPLE_IMAGES = {
    "bleu": "https://images.unsplash.com/photo-1523293182086-7651a899d37f?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "coco": "https://images.unsplash.com/photo-1594035910387-fea47794261f?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "no5": "https://images.unsplash.com/photo-1541643600914-78b084683601?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "prada": "https://images.unsplash.com/photo-1610461888750-10bfc601b874?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "br540": "https://images.unsplash.com/photo-1543422655-ac1c6ca993ed?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "santal": "https://images.unsplash.com/photo-1458538977777-0549b2370168?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "niche": "https://images.unsplash.com/photo-1593487568720-92097fb460fb?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
    "hero": "https://images.unsplash.com/photo-1622618991746-fe6004db3a47?crop=entropy&cs=srgb&fm=jpg&q=85&w=1000",
}


def _p(**kw):
    d = {
        "original_price": None, "remaining_percentage": None, "notes": {"top": [], "heart": [], "base": []},
        "seller_type": "AUREN", "seller_name": "AUREN", "stock": 1, "status": "Available",
        "featured": False, "badges": [], "photos": [], "verified": None, "from_submission": None,
        "views": 0, "interested_count": 0,
    }
    d.update(kw)
    return d


async def seed_products():
    if await db.products.count_documents({}) > 0:
        return
    samples = [
        _p(name="Bleu de Chanel Eau de Parfum", brand="Chanel", price=2450000, original_price=2900000,
           size="100ml", condition="New 100% (Sealed)", description="Aroma kayu aromatik yang segar dan maskulin. Segel penuh, box lengkap.",
           notes={"top": ["Grapefruit", "Lemon", "Mint"], "heart": ["Ginger", "Iso E Super", "Jasmine"], "base": ["Incense", "Vetiver", "Cedar"]},
           categories=["New", "Men", "Original"], gender="Men", featured=True, badges=["New", "AUREN Pick"],
           photos=[SAMPLE_IMAGES["bleu"], SAMPLE_IMAGES["niche"]], verified="Verified Original by AUREN", views=142),
        _p(name="Coco Noir Eau de Parfum", brand="Chanel", price=1950000, original_price=2600000,
           size="100ml", condition="Preloved 90%", remaining_percentage=90,
           description="Oriental elegan dengan sentuhan misterius. Sisa isi sekitar 90%.",
           notes={"top": ["Grapefruit", "Bergamot"], "heart": ["Rose", "Geranium", "Jasmine"], "base": ["Patchouli", "Tonka Bean", "Sandalwood"]},
           categories=["Preloved", "Women", "Original"], gender="Women", featured=True, badges=["Preloved"],
           photos=[SAMPLE_IMAGES["coco"]], views=98),
        _p(name="N°5 Eau de Parfum Spray", brand="Chanel", price=2800000, original_price=3100000,
           size="100ml", condition="New 100%", description="Ikon parfum klasik dunia. Baru dan tersegel.",
           notes={"top": ["Aldehydes", "Ylang-Ylang", "Neroli"], "heart": ["Jasmine", "Rose", "Lily-of-the-Valley"], "base": ["Vetiver", "Sandalwood", "Vanilla"]},
           categories=["New", "Women", "Original", "Rare"], gender="Women", featured=True, badges=["Rare", "AUREN Pick"],
           photos=[SAMPLE_IMAGES["no5"]], verified="Verified Original by AUREN", views=210),
        _p(name="L'Homme Intense EDP", brand="Prada", price=1650000, original_price=2200000,
           size="100ml", condition="Preloved 85%", remaining_percentage=85,
           description="Maskulin hangat dengan iris dan amber. Preloved, isi sekitar 85%.",
           notes={"top": ["Iris", "Amber"], "heart": ["Leather", "Patchouli"], "base": ["Tonka Bean", "Sandalwood"]},
           categories=["Preloved", "Men"], gender="Men", featured=True, badges=["Preloved"],
           photos=[SAMPLE_IMAGES["prada"]], views=64),
        _p(name="Baccarat Rouge 540 Extrait", brand="Maison Francis Kurkdjian", price=5400000, original_price=6800000,
           size="70ml", condition="Preloved 95%", remaining_percentage=95,
           description="Amber floral legendaris. Sangat dicari, isi 95%.",
           notes={"top": ["Bitter Almond", "Saffron"], "heart": ["Egyptian Jasmine", "Cedar"], "base": ["Ambergris", "Woody Notes", "Musk"]},
           categories=["Preloved", "Unisex", "Rare"], gender="Unisex", featured=True, badges=["Rare", "AUREN Pick"],
           photos=[SAMPLE_IMAGES["br540"]], verified="Verified Original by AUREN", views=305),
        _p(name="Santal 33 Eau de Parfum", brand="Le Labo", price=3200000, original_price=3800000,
           size="100ml", condition="Preloved 80%", remaining_percentage=80,
           description="Cedarwood ikonik yang smoky. Hard to find di Indonesia.",
           notes={"top": ["Violet Accord", "Cardamom"], "heart": ["Iris", "Ambrox"], "base": ["Cedarwood", "Leather", "Sandalwood"]},
           categories=["Preloved", "Unisex", "Rare"], gender="Unisex", featured=True, badges=["Rare"],
           photos=[SAMPLE_IMAGES["santal"]], views=178),
        _p(name="MYKONOS Eau de Parfum", brand="Luminos", price=420000, original_price=550000,
           size="50ml", condition="New 100%", description="Aroma fresh aquatic terinspirasi laut Mykonos. Lokal pride.",
           notes={"top": ["Sea Salt", "Bergamot"], "heart": ["Lavender", "Sage"], "base": ["Musk", "Amberwood"]},
           categories=["New", "Unisex", "Original"], gender="Unisex", badges=["New"],
           photos=[SAMPLE_IMAGES["niche"]], stock=3, views=52),
        _p(name="Vanilla Dreams EDP", brand="Luminos", price=380000,
           size="50ml", condition="Preloved 88%", remaining_percentage=88,
           description="Gourmand vanilla yang hangat dan manis. Preloved terawat.",
           notes={"top": ["Vanilla", "Bergamot"], "heart": ["Tonka Bean"], "base": ["Sandalwood", "Musk"]},
           categories=["Preloved", "Women"], gender="Women",
           seller_type="Community Seller", seller_name="Community Seller", badges=["Preloved"],
           photos=[SAMPLE_IMAGES["coco"]], views=41),
        _p(name="Aventus Cologne", brand="Creed", price=4200000, original_price=5000000,
           size="100ml", condition="Preloved 70%", remaining_percentage=70,
           description="Fruity chypre legendaris. Isi sekitar 70%, box ada.",
           notes={"top": ["Pineapple", "Bergamot", "Apple"], "heart": ["Birch", "Jasmine"], "base": ["Musk", "Oakmoss", "Vanilla"]},
           categories=["Preloved", "Men", "Rare"], gender="Men",
           seller_type="Community Seller", seller_name="Community Seller", badges=["Preloved", "Rare"],
           photos=[SAMPLE_IMAGES["bleu"]], status="Reserved", views=133),
        _p(name="Oud Wood Intense", brand="Tom Ford", price=3900000, original_price=4500000,
           size="50ml", condition="New 100%", description="Oud mewah yang smoky dan hangat. Baru, tersegel.",
           notes={"top": ["Oud", "Rosewood"], "heart": ["Sandalwood", "Cardamom"], "base": ["Amber", "Vanilla"]},
           categories=["New", "Unisex", "Original", "Rare"], gender="Unisex", featured=False, badges=["New", "Rare"],
           photos=[SAMPLE_IMAGES["santal"]], verified="Verified Original by AUREN", views=87),
        _p(name="Light Blue Eau Intense", brand="Dolce & Gabbana", price=980000, original_price=1300000,
           size="100ml", condition="Preloved 92%", remaining_percentage=92,
           description="Segar sitrus musim panas. Preloved hampir penuh.",
           notes={"top": ["Lemon", "Apple"], "heart": ["Jasmine", "Marigold"], "base": ["Musk", "Amber"]},
           categories=["Preloved", "Women"], gender="Women", badges=["Preloved"],
           photos=[SAMPLE_IMAGES["no5"]], views=29),
        _p(name="Sauvage EDT", brand="Dior", price=1450000,
           size="100ml", condition="New 100%", description="Fresh spicy yang populer sepanjang masa. Baru, box lengkap.",
           notes={"top": ["Bergamot", "Pepper"], "heart": ["Sichuan Pepper", "Lavender"], "base": ["Ambroxan", "Cedar"]},
           categories=["New", "Men", "Original"], gender="Men", badges=["New", "AUREN Pick"],
           photos=[SAMPLE_IMAGES["prada"]], stock=2, views=190),
        _p(name="Black Opium EDP", brand="Yves Saint Laurent", price=1750000, original_price=2100000,
           size="90ml", condition="Preloved 78%", remaining_percentage=78,
           description="Coffee vanilla yang adiktif. Isi sekitar 78%.",
           notes={"top": ["Pink Pepper", "Orange Blossom"], "heart": ["Coffee", "Jasmine"], "base": ["Vanilla", "Patchouli", "Cedar"]},
           categories=["Preloved", "Women"], gender="Women",
           seller_type="Community Seller", seller_name="Community Seller", badges=["Preloved"],
           photos=[SAMPLE_IMAGES["coco"]], status="Sold", views=76),
    ]
    for s in samples:
        s["id"] = str(uuid.uuid4())
        s["slug"] = await unique_slug(s["name"], s["brand"])
        s["created_at"] = now_iso()
    await db.products.insert_many(samples)
    logger.info("Seeded %d products", len(samples))


async def seed_submissions():
    if await db.submissions.count_documents({}) > 0:
        return
    subs = [
        {"id": str(uuid.uuid4()), "ref": gen_ref("AUR"), "seller_name": "Rani Putri", "phone": "6281234567890",
         "instagram": "@raniputri", "location": "Jakarta Selatan", "contact_method": "WhatsApp",
         "perfume_name": "Good Girl EDP", "brand": "Carolina Herrera", "size": "80ml", "condition": "Used",
         "remaining_percentage": 60, "asking_price": 850000, "box_available": True, "proof_available": False,
         "description": "Dipakai 1 tahun, masih wangi kuat. Box ada.", "photos": [SAMPLE_IMAGES["no5"]],
         "status": "Submitted", "admin_note": None, "created_at": now_iso()},
        {"id": str(uuid.uuid4()), "ref": gen_ref("AUR"), "seller_name": "Budi Santoso", "phone": "6289876543210",
         "instagram": "", "location": "Bandung", "contact_method": "WhatsApp",
         "perfume_name": "Acqua di Gio Profumo", "brand": "Giorgio Armani", "size": "75ml", "condition": "Like New",
         "remaining_percentage": 95, "asking_price": 1250000, "box_available": True, "proof_available": True,
         "description": "Baru pakai 2x, kondisi mulus, ada struk.", "photos": [SAMPLE_IMAGES["prada"]],
         "status": "Under Review", "admin_note": None, "created_at": now_iso()},
    ]
    await db.submissions.insert_many(subs)


CATALOG_IMG = {
    "mykonos": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/44cb59f2d9714bc0cbf96774a4a33c60ab3341e457f3d7f6035797ad35fb2512.jpeg",
    "velixir": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/2042297efe4a7742fac28d9d8ace7456c464f59bfd6db67d08820ceeb85d4821.jpeg",
    "afnan": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/163c1721ce5fc4118f3c4be734d54be710c3ca9972e8c0d8add384e7da440acb.jpeg",
    "baccarat": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/0c1a22c47cabfba097b66c8a37487278d1e63cad9638257839e6e2952de53409.jpeg",
    "santal": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/bc38f1e910d169da57cb245583a3d1dc3ecc60d6bcfc2bb99499f476149d528c.jpeg",
    "aventus": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/29a7b38701a9503cbc4c8d866a4d5820c0e73fc84af837f9179fd2803064adf3.jpeg",
    "goodgirl": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/026d8156da021fe7476e8e8d8b37d095c492f768b959a23c4c0f62171a85244b.jpeg",
    "blackopium": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/6908e7d1b5ef3872b4954616527921826926db65fe74832a529e3a73e586a146.jpeg",
    "oudwood": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/0ce0239510c2f7dccf389d3b8cd52b1755371605ffa639783584979f1e4580fd.jpeg",
    "sauvage": "https://static.prod-images.emergentagent.com/jobs/5b2591e7-a136-4f6e-af32-6d03cc358d3f/images/5cd10ff192785c8fef0cef2cc40fbffdfd72d83e88fb339b0651f1037c9b142a.jpeg",
}


async def seed_catalog():
    if await db.products.count_documents({}) > 0:
        return
    I = CATALOG_IMG
    samples = [
        _p(name="Mykonos", brand="Luminos", price=285000, original_price=350000, size="50ml",
           condition="Preloved 85%", remaining_percentage=85, gender="Unisex",
           categories=["Preloved", "Viral", "Unisex"], badges=["Viral", "Preloved"], featured=True,
           description="Parfum viral yang lagi banyak dicari. Aroma fresh aquatic terinspirasi laut Mykonos, cocok dipakai harian. Sisa isi sekitar 85%, botol terawat.",
           notes={"top": ["Sea Salt", "Bergamot"], "heart": ["Lavender", "Sage"], "base": ["Musk", "Amberwood"]},
           photos=[I["mykonos"]], views=520, interested_count=18),
        _p(name="Velixir", brand="Luminos", price=320000, size="50ml",
           condition="New 100%", gender="Unisex", categories=["New", "Viral", "Unisex"],
           badges=["Viral", "New"], featured=True,
           description="Gourmand manis yang lagi viral di TikTok. Baru & tersegel. Wangi tahan lama, cocok untuk acara malam.",
           notes={"top": ["Pink Pepper", "Bergamot"], "heart": ["Vanilla", "Tonka Bean"], "base": ["Amber", "Musk"]},
           photos=[I["velixir"]], views=610, interested_count=25),
        _p(name="Afnan 9PM", brand="Afnan", price=450000, original_price=600000, size="100ml",
           condition="New 100%", gender="Men", categories=["New", "Men", "Viral"],
           badges=["Viral", "New"], featured=True,
           description="Clone viral yang wanginya mirip parfum designer mahal. Sweet spicy, performa juara. Baru, box lengkap.",
           notes={"top": ["Apple", "Lavender", "Cinnamon"], "heart": ["Orchid", "Vanilla"], "base": ["Tonka Bean", "Amber"]},
           photos=[I["afnan"]], views=430, interested_count=14),
        _p(name="Baccarat Rouge 540 Extrait", brand="Maison Francis Kurkdjian", price=5400000,
           original_price=6800000, size="70ml", condition="Preloved 95%", remaining_percentage=95,
           gender="Unisex", categories=["Preloved", "Unisex", "Rare"], badges=["Rare", "AUREN Pick"],
           featured=True, verified="Sudah dicek keasliannya oleh AUREN",
           description="Amber floral legendaris, sangat dicari. Isi 95%, kondisi mulus.",
           notes={"top": ["Saffron", "Bitter Almond"], "heart": ["Egyptian Jasmine", "Cedar"], "base": ["Ambergris", "Woody Notes"]},
           photos=[I["baccarat"]], views=380, interested_count=9),
        _p(name="Santal 33", brand="Le Labo", price=3200000, size="100ml", condition="Preloved 80%",
           remaining_percentage=80, gender="Unisex", categories=["Preloved", "Unisex", "Rare"],
           badges=["Rare"], featured=True,
           description="Cedarwood ikonik yang smoky. Hard to find di Indonesia.",
           notes={"top": ["Violet Accord", "Cardamom"], "heart": ["Iris", "Ambrox"], "base": ["Cedarwood", "Leather"]},
           photos=[I["santal"]], views=290),
        _p(name="Aventus", brand="Creed", price=4200000, original_price=5000000, size="100ml",
           condition="Preloved 70%", remaining_percentage=70, gender="Men",
           categories=["Preloved", "Men", "Rare"], badges=["Rare", "Preloved"], status="Reserved",
           seller_type="Community Seller", seller_name="Community Seller",
           description="Fruity chypre legendaris. Isi 70%, box ada. (Sedang dalam proses reservasi)",
           notes={"top": ["Pineapple", "Bergamot", "Apple"], "heart": ["Birch", "Jasmine"], "base": ["Musk", "Oakmoss"]},
           photos=[I["aventus"]], views=210),
        _p(name="Good Girl", brand="Carolina Herrera", price=1450000, size="80ml",
           condition="New 100%", gender="Women", categories=["New", "Women"], badges=["New"],
           description="Ikon feminin dengan botol high-heel. Baru & tersegel. Sweet floral yang bold.",
           notes={"top": ["Almond", "Coffee"], "heart": ["Tuberose", "Jasmine"], "base": ["Tonka Bean", "Cacao"]},
           photos=[I["goodgirl"]], views=180),
        _p(name="Black Opium", brand="Yves Saint Laurent", price=1150000, original_price=1400000,
           size="90ml", condition="Preloved 78%", remaining_percentage=78, gender="Women",
           categories=["Preloved", "Women"], badges=["Preloved"],
           seller_type="Community Seller", seller_name="Community Seller",
           description="Coffee vanilla yang adiktif. Isi sekitar 78%.",
           notes={"top": ["Pink Pepper", "Orange Blossom"], "heart": ["Coffee", "Jasmine"], "base": ["Vanilla", "Cedar"]},
           photos=[I["blackopium"]], views=160),
        _p(name="Oud Wood", brand="Tom Ford", price=3900000, size="50ml", condition="New 100%",
           gender="Unisex", categories=["New", "Unisex", "Rare"], badges=["New", "Rare"],
           verified="Sudah dicek keasliannya oleh AUREN",
           description="Oud mewah yang smoky & hangat. Baru, tersegel.",
           notes={"top": ["Oud", "Rosewood"], "heart": ["Sandalwood", "Cardamom"], "base": ["Amber", "Vanilla"]},
           photos=[I["oudwood"]], views=140),
        _p(name="Sauvage EDT", brand="Dior", price=1450000, size="100ml", condition="New 100%",
           gender="Men", categories=["New", "Men", "Viral"], badges=["Viral", "New"], featured=True,
           stock=3, description="Fresh spicy paling laris sepanjang masa. Baru, box lengkap.",
           notes={"top": ["Bergamot", "Pepper"], "heart": ["Sichuan Pepper", "Lavender"], "base": ["Ambroxan", "Cedar"]},
           photos=[I["sauvage"]], views=350, interested_count=11),
    ]
    for s in samples:
        s["id"] = str(uuid.uuid4())
        s["slug"] = await unique_slug(s["name"], s["brand"])
        s["created_at"] = now_iso()
    await db.products.insert_many(samples)
    logger.info("Seeded catalog %d products", len(samples))


@app.on_event("startup")
async def startup():
    await db.products.create_index("slug")
    await db.products.create_index("id")
    await db.users.create_index("email", unique=True)
    await seed_admin()
    await seed_settings()
    # Catalog seeding can be disabled via environment variable SEED_CATALOG=0
    try:
        if os.environ.get("SEED_CATALOG", "1") not in ("0", "false", "False"):
            await seed_catalog()
    except Exception:
        # don't crash startup on seed problems
        logger.exception("Seed catalog failed")


async def seed_settings():
    if not await db.settings.find_one({"key": "announcement"}):
        await db.settings.insert_one({
            "key": "announcement",
            "enabled": True,
            "text": "✨ Selamat datang di AUREN — parfum baru, preloved & rare. Chat kami untuk info stok!",
            "bg_color": "#121212",
            "text_color": "#C5A059",
            "link": "/shop",
        })


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
