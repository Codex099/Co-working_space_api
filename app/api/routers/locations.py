from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from services.location_service import get_all_locations_logic, get_rooms_by_location_name
from services.booking_service import get_available_slots_range

router = APIRouter()

@router.get('/locations')
def get_all_locations_route():
    resp, code = get_all_locations_logic()
    return JSONResponse(content=resp, status_code=code)

@router.get('/rooms/by-location/{location_name}')
def rooms_by_location_name_route(location_name: str):
    resp, code = get_rooms_by_location_name(location_name)
    return JSONResponse(content=resp, status_code=code)

@router.get('/rooms/{room_id}/slots')
def available_slots_range_route(room_id: int, start: Optional[str] = None, end: Optional[str] = None):
    resp, code = get_available_slots_range(room_id, start, end)
    return JSONResponse(content=resp, status_code=code)
