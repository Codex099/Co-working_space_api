from fastapi import APIRouter, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import base64
import os

from services.user_service import (
    get_all_users, get_user_by_email, get_user_by_id, 
    create_user_db as create_user, delete_user, get_user_balance
)
from services.location_service import (
    get_all_locations, get_all_rooms, create_location, 
    create_room, delete_room, delete_location
)
from services.recharge_service import get_user_recharges, create_recharge_db as create_recharge
from services.booking_service import get_all_bookings

admin_bp = APIRouter(prefix='/admin')

templates = Jinja2Templates(directory=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'templates')))

def b64encode_filter(data):
    if data:
        return base64.b64encode(data).decode('utf-8')
    return ''

def zfill_filter(s, width=2):
    return str(s).zfill(width)

templates.env.filters['b64encode'] = b64encode_filter
templates.env.filters['zfill'] = zfill_filter

@admin_bp.get('/', response_class=HTMLResponse)
def admin_home(request: Request):
    return templates.TemplateResponse(request, 'home.html', {"request": request})

@admin_bp.get('/users', response_class=HTMLResponse)
def users_page(request: Request, search_email: Optional[str] = None):
    if search_email:
        users = [get_user_by_email(search_email)] if get_user_by_email(search_email) else []
    else:
        users = get_all_users()
    return templates.TemplateResponse(request, 'users.html', {"request": request, "users": users})

@admin_bp.get('/locations', response_class=HTMLResponse)
def locations_page(request: Request):
    locations = get_all_locations()
    return templates.TemplateResponse(request, 'locations.html', {"request": request, "locations": locations})

@admin_bp.get('/rooms', response_class=HTMLResponse)
def rooms_page(request: Request):
    rooms = get_all_rooms()
    locations = get_all_locations()
    return templates.TemplateResponse(request, 'rooms.html', {"request": request, "rooms": rooms, "locations": locations})

@admin_bp.post('/users/f_balance/{user_id}')
async def update_balance(request: Request, user_id: int, balance: float = Form(...)):
    create_recharge({'user_id': user_id, 'amount': balance})
    return RedirectResponse(url=request.url_for('users_page'), status_code=303)

@admin_bp.post('/users/create')
async def create_user_admin(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    number: int = Form(...),
    password: str = Form(...),
    role: str = Form('Normal user'),
    balance: float = Form(0.0)
):
    data = {
        'name': name,
        'email': email,
        'number': number,
        'password': password,
        'role': role,
        'balance': balance,
    }
    create_user(data)
    return RedirectResponse(url=request.url_for('users_page'), status_code=303)

@admin_bp.post('/locations')
async def create_location_admin(
    request: Request,
    name: str = Form(...),
    image: UploadFile = File(None)
):
    image_data = await image.read() if image and image.filename else None
    create_location({'name': name, 'image_data': image_data})
    return RedirectResponse(url=request.url_for('locations_page'), status_code=303)

@admin_bp.post('/rooms')
async def create_room_admin(
    request: Request,
    name: str = Form(...),
    capacity: int = Form(...),
    slot_price: float = Form(...),
    slot_duration: int = Form(...),
    location_id: int = Form(...),
    image: UploadFile = File(None)
):
    image_data = await image.read() if image and image.filename else None
    create_room({
        'name': name,
        'capacity': capacity,
        'slot_price': slot_price,
        'slot_duration': slot_duration,
        'location_id': location_id,
        'image_data': image_data
    })
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

@admin_bp.post('/rooms/delete/{room_id}')
def delete_room_admin(request: Request, room_id: int):
    delete_room(room_id)
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

@admin_bp.post('/users/delete/{user_id}')
def delete_user_admin(request: Request, user_id: int):
    delete_user(user_id)
    return RedirectResponse(url=request.url_for('users_page'), status_code=303)

@admin_bp.post('/locations/delete/{location_id}')
def delete_location_admin(request: Request, location_id: int):
    delete_location(location_id)
    return RedirectResponse(url=request.url_for('locations_page'), status_code=303)

@admin_bp.get('/users/{user_id}', response_class=HTMLResponse)
def user_detail(request: Request, user_id: int):
    user = get_user_by_id(user_id)
    if not user:
        return HTMLResponse("User not found", status_code=404)
    balance = get_user_balance(user_id)
    recharges = get_user_recharges(user_id)
    return templates.TemplateResponse(request, 'user_detail.html', {"request": request, "user": user, "balance": balance, "recharges": recharges})

@admin_bp.get('/locations/{location_id}/rooms', response_class=HTMLResponse)
def location_rooms(request: Request, location_id: int):
    location = next((loc for loc in get_all_locations() if loc.id == location_id), None)
    if not location:
        return HTMLResponse("Location not found", status_code=404)
    rooms = [room for room in get_all_rooms() if room.location_id == location_id]
    return templates.TemplateResponse(request, 'location_rooms.html', {"request": request, "location": location, "rooms": rooms})

@admin_bp.get('/bookings', response_class=HTMLResponse)
def bookings_page(request: Request, search_email: Optional[str] = None):
    search_email = search_email.strip().lower() if search_email else ''
    bookings = get_all_bookings()
    if search_email:
        bookings = [b for b in bookings if b.user and b.user.email and search_email in b.user.email.lower()]
    return templates.TemplateResponse(request, 'bookings.html', {"request": request, "bookings": bookings})
