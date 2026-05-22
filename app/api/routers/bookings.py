from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from schemas import BookingCreate
from services.booking_service import create_booking, get_user_reservations, get_occupied_slots, cancel_booking
from core.dependencies import get_current_user, get_current_user_optional
from typing import Optional

router = APIRouter()


@router.post('/bookings', tags=["Bookings"])
async def create_booking_route(data: BookingCreate, current_user: dict = Depends(get_current_user)):
    """Créer une ou plusieurs réservations. Le user_id est extrait du token JWT."""
    payload = data.model_dump()
    payload['user_id'] = current_user["uid"]
    resp, code = create_booking(payload)
    return JSONResponse(content=resp, status_code=code)


@router.delete('/cancel/{booking_id}', tags=["Bookings"])
async def cancel_booking_route(booking_id: int, current_user: dict = Depends(get_current_user)):
    """
    Annule une réservation appartenant à l'utilisateur authentifié.

    Règles :
    - L'annulation est possible uniquement si le début est à plus de 24h.
    - Remboursement de 50% du prix total sur le solde du client.
    - La réservation passe au statut 'cancelled'.
    """
    resp, code = cancel_booking(booking_id, current_user["uid"])
    return JSONResponse(content=resp, status_code=code)


@router.get('/bookings/occupied-slots', tags=["Bookings"])
def get_occupied_slots_route(
    room_id: int,
    booking_type_id: int,
    current_user: dict = Depends(get_current_user)  # 🔒 JWT obligatoire
):
    """
    Retourne les créneaux occupés pour une salle et un type, depuis aujourd'hui sur 90 jours.
    Aucune date à envoyer — calculé automatiquement à partir de la date du jour.
    """
    resp, code = get_occupied_slots(room_id, booking_type_id)
    return JSONResponse(content=resp, status_code=code)


@router.get('/reservations', tags=["Bookings"])
def get_user_reservations_route(current_user: dict = Depends(get_current_user)):
    """Retourne toutes les réservations de l'utilisateur authentifié."""
    resp, code = get_user_reservations(current_user["uid"])
    return JSONResponse(content=resp, status_code=code)
