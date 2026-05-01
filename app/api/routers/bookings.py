from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.booking_service import create_booking, get_user_reservations
from schemas import BookingCreate

router = APIRouter()

@router.post('/bookings')
async def create_booking_route(data: BookingCreate):
    resp, code = create_booking(data.model_dump())
    return JSONResponse(content=resp, status_code=code)

@router.get('/reservations/user/{user_id}')
def get_user_reservations_route(user_id: int):
    resp, code = get_user_reservations(user_id)
    return JSONResponse(content=resp, status_code=code)
