from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from services.location_service import get_all_locations_logic, get_rooms_by_location_name
from services.booking_service import (
    get_booking_types_by_room,
    create_booking_type,
    update_booking_type,
    delete_booking_type
)
from schemas import BookingTypeCreate, BookingTypeUpdate

router = APIRouter()


# ─── Locations ───────────────────────────────────────────────

@router.get('/locations', tags=["Locations","mcp_access"])
def get_all_locations_route():
    resp, code = get_all_locations_logic()
    return JSONResponse(content=resp, status_code=code)


@router.get('/rooms/by-location/{location_name}', tags=["Locations","mcp_access"], operation_id="rooms_by_location_name")
def rooms_by_location_name_route(location_name: str):
    """Retourne les salles d'un espace avec leurs types de réservation disponibles."""
    resp, code = get_rooms_by_location_name(location_name)
    return JSONResponse(content=resp, status_code=code)


# ─── Booking Types par salle ─────────────────────────────────

@router.get('/rooms/{room_id}/booking-types', tags=["Booking Types","mcp_access"])
def get_room_booking_types_route(room_id: int):
    """Liste tous les types de réservation actifs d'une salle."""
    types = get_booking_types_by_room(room_id)
    result = [
        {
            "id":               bt.id,
            "name":             bt.name,
            "duration_minutes": bt.resolved_duration_minutes,
            "price":            bt.price,
            "is_active":        bt.is_active
        }
        for bt in types
    ]
    return JSONResponse(content=result, status_code=200)


@router.post('/rooms/booking-types', tags=["Booking Types"])
def create_booking_type_route(data: BookingTypeCreate):
    """Créer un type de réservation pour une salle (admin)."""
    bt = create_booking_type(data.model_dump())
    return JSONResponse(content={
        "message":          "Type créé",
        "id":               bt.id,
        "name":             bt.name,
        "duration_minutes": bt.resolved_duration_minutes,
        "price":            bt.price
    }, status_code=201)


@router.put('/rooms/booking-types/{type_id}', tags=["Booking Types"])
def update_booking_type_route(type_id: int, data: BookingTypeUpdate):
    """Mettre à jour un type de réservation (admin)."""
    bt = update_booking_type(type_id, data.model_dump(exclude_none=True))
    if not bt:
        return JSONResponse(content={"error": "Type introuvable"}, status_code=404)
    return JSONResponse(content={"message": "Type mis à jour", "id": bt.id}, status_code=200)


@router.delete('/rooms/booking-types/{type_id}', tags=["Booking Types"])
def delete_booking_type_route(type_id: int):
    """Supprimer un type de réservation (admin)."""
    success = delete_booking_type(type_id)
    if not success:
        return JSONResponse(content={"error": "Type introuvable"}, status_code=404)
    return JSONResponse(content={"message": "Type supprimé"}, status_code=200)
