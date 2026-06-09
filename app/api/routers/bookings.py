import os
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, HTMLResponse
from schemas import BookingCreate
from services.booking_service import create_booking, get_user_reservations, get_occupied_slots, cancel_booking
from core.dependencies import get_current_user
from urllib.parse import urlencode

router = APIRouter()


@router.post('/bookings', tags=["Bookings", "mcp_access"])
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


@router.get('/bookings/occupied-slots', tags=["Bookings", "mcp_access"])
def get_occupied_slots_route(
    room_id: int,
    booking_type_id: int,
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


@router.get('/bookings/link_flutter', tags=["Bookings", "mcp_access"], operation_id="prepare_booking_link")
def prepare_booking_link(
    request: Request,
    room_id: int = Query(..., description="ID de la salle"),
    room_name: str = Query(..., description="Nom de la salle"),
    location_name: str = Query(..., description="Nom de l'espace de coworking"),
    booking_type_name: str = Query(..., description="Nom du type de réservation"),
    total_price: float = Query(..., description="Prix total de la réservation en DZD"),
    date: str = Query(..., description="Date au format YYYY-MM-DD"),
    start_time: str = Query(..., description="Heure de début HH:MM"),
    end_time: str = Query(..., description="Heure de fin HH:MM"),
):
    """
    Génère un lien HTTPS cliquable (depuis Claude, WhatsApp, etc.) qui redirige
    vers l'app Flutter via la page /redirect-booking.
    L'agent IA appelle cette route et envoie le lien retourné à l'utilisateur.
    """
    params = {
        "room_id": room_id,
        "room_name": room_name,
        "location_name": location_name,
        "booking_type_name": booking_type_name,
        "total_price": total_price,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
    }
   # Url link 
    base_url = os.getenv("PUBLIC_BASE_URL", str(request.base_url)).rstrip("/")
    redirect_link = f"{base_url}/redirect-booking?{urlencode(params)}"
    return {
        "booking_link": redirect_link,
        "message": "Clique sur ce lien pour confirmer ta réservation dans l'application.",
    }


@router.get('/redirect-booking', response_class=HTMLResponse, tags=["Bookings", "mcp_access"], operation_id="redirect_to_app")
async def redirect_to_app(
    room_id: int = Query(...),
    room_name: str = Query(...),
    location_name: str = Query(...),
    booking_type_name: str = Query(...),
    total_price: float = Query(...),
    date: str = Query(...),
    start_time: str = Query(...),
    end_time: str = Query(...),
):
    """
    Redirige instantanément vers l'app Flutter via coworking://.
    Page invisible — redirection JavaScript à 0ms, aucun contenu visible.
    """
    params = {
        "room_id": room_id,
        "room_name": room_name,
        "location_name": location_name,
        "booking_type_name": booking_type_name,
        "total_price": total_price,
        "date": date,
        "start_time": start_time,
        "end_time": end_time,
    }
    app_deep_link = f"coworking://book?{urlencode(params)}"
    html = f'<script>window.location.replace("{app_deep_link}");</script>'
    return HTMLResponse(content=html, status_code=200)