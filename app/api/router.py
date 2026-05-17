from fastapi import APIRouter
from .routers import users, bookings, locations, admin

api_router = APIRouter()

@api_router.get('/')
async def home():
    return "this is my api"

api_router.include_router(users.router, tags=["Users"])
api_router.include_router(bookings.router, tags=["bookings"])
api_router.include_router(locations.router, tags=["locations"])
api_router.include_router(admin.admin_bp, tags=["M3alem"] )
