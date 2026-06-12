from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import base64
import os
from datetime import datetime, timedelta
from sqlalchemy import func, desc
from db.database import db
from models.domain import BalanceTransaction

from services.user_service import (
    get_all_users, get_user_by_email, get_user_by_uid as get_user_by_id, 
    create_user_db , delete_user, get_user_balance, search_users_by_email
)
from services.location_service import (
    get_all_locations, get_all_rooms, create_location, 
    create_room, delete_room, delete_location
)
from services.recharge_service import get_user_recharges, create_recharge_db as create_recharge, get_all_recharges
from services.booking_service import get_all_bookings, update_expired_bookings
from services.space_manager_amount_service import (
    get_manager_pending_balance, create_settlement, get_settlement_history, delete_settlement
)
from core.dependencies import get_admin_user_from_cookie

admin_bp = APIRouter(prefix='/admin')

templates = Jinja2Templates(directory=os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'templates')))

def b64encode_filter(data):
    if data:
        return base64.b64encode(data).decode('utf-8')
    return ''

def zfill_filter(s, width=2):
    return str(s).zfill(width)

def get_tx_description(tx):
    from models.domain import Booking
    if tx.type == 'recharge':
        return f"Recharge +{tx.amount} DA"
    elif tx.type == 'refund':
        return f"Remboursement +{tx.amount} DA"
    elif tx.type in ['booking', 'cancellation']:
        booking = Booking.query.get(tx.ref_id) if tx.ref_id else None
        room_name = booking.room.name if (booking and booking.room) else f"#{tx.ref_id}"
        if tx.type == 'booking':
            return f"Réservation salle {room_name}"
        else:
            return f"Annulation réservation salle {room_name} (+{tx.amount} DA remboursé)"
    return f"Transaction {tx.type}"

templates.env.filters['b64encode'] = b64encode_filter
templates.env.filters['zfill'] = zfill_filter
templates.env.filters['tx_description'] = get_tx_description

# --- AUTHENTICATION ROUTES ---

@admin_bp.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, 'admin_login.html', {"request": request})

@admin_bp.post('/login')
def login_post(request: Request, identifier: str = Form(...), password: str = Form(...)):
    from models.domain import User
    from core.hashing import verify_password
    from core.jwt import create_access_token
    
    # Simple login verification: checks username or email
    user = User.query.filter((User.email == identifier) | (User.username == identifier)).first()
    
    if not user:
        return templates.TemplateResponse(request, 'admin_login.html', {"request": request, "error": "Identifiants invalides"})
        
    if not user.hashed_password or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request, 'admin_login.html', {"request": request, "error": "Identifiants invalides"})
    
    # Check role
    if user.role not in ['admin', 'space_manager']:
        return templates.TemplateResponse(request, 'admin_login.html', {"request": request, "error": "Accès refusé"})
    
    access_token = create_access_token({"sub": user.id, "email": user.email})
    redirect = RedirectResponse(url="/admin/", status_code=303)
    redirect.set_cookie(key="admin_access_token", value=access_token, httponly=True)
    return redirect

@admin_bp.get('/logout')
def logout():
    redirect = RedirectResponse(url="/admin/login", status_code=303)
    redirect.delete_cookie("admin_access_token")
    return redirect


# --- PROTECTED ROUTES ---

@admin_bp.get('/', response_class=HTMLResponse)
def admin_home(request: Request, days: int = 7, admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import User, Booking, Location, Room, Recharge, BalanceTransaction

    # Determine date range
    if days not in [7, 30, 90]:
        days = 7

    today = datetime.utcnow().date()
    days_ago = today - timedelta(days=days-1)

    # Prepare labels for Chart.js
    chart_labels = []
    current_date = days_ago
    while current_date <= today:
        if days == 7:
            chart_labels.append(current_date.strftime('%d/%m'))
        elif days == 30:
            chart_labels.append(current_date.strftime('%d/%m'))
        else:
            chart_labels.append(current_date.strftime('%d/%m'))
        current_date += timedelta(days=1)

    if admin_user.role == 'admin':
        # Admin: Global statistics (last N days)
        total_users = User.query.filter(User.created_at >= datetime.combine(days_ago, datetime.min.time())).count()
        total_bookings = Booking.query.filter(Booking.start_time >= datetime.combine(days_ago, datetime.min.time())).count()
        total_locations = Location.query.count()
        
        # Total revenue is the sum of recharge amounts (credits added to system) over last N days
        total_revenue_val = db.session.query(func.sum(Recharge.amount)).filter(Recharge.date >= datetime.combine(days_ago, datetime.min.time())).scalar() or 0.0
        total_revenue = round(total_revenue_val, 2)

        # Confirmed Bookings per day
        confirmed_by_day = db.session.query(
            func.date(Booking.start_time).label('day'),
            func.count(Booking.id)
        ).filter(
            Booking.start_time >= datetime.combine(days_ago, datetime.min.time()),
            (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
        ).group_by('day').all()
        confirmed_map = {}
        for b in confirmed_by_day:
            day_key = b[0]
            if isinstance(day_key, str):
                try:
                    from datetime import date as dt_date
                    day_key = dt_date.fromisoformat(day_key)
                except ValueError:
                    pass
            confirmed_map[day_key] = b[1]
            
        # Cancelled Bookings per day
        cancelled_by_day = db.session.query(
            func.date(func.coalesce(Booking.cancelled_at, Booking.start_time)).label('day'),
            func.count(Booking.id)
        ).filter(
            func.coalesce(Booking.cancelled_at, Booking.start_time) >= datetime.combine(days_ago, datetime.min.time()),
            Booking.status == 'cancelled'
        ).group_by('day').all()
        cancelled_map = {}
        for b in cancelled_by_day:
            day_key = b[0]
            if isinstance(day_key, str):
                try:
                    from datetime import date as dt_date
                    day_key = dt_date.fromisoformat(day_key)
                except ValueError:
                    pass
            cancelled_map[day_key] = b[1]

        # Revenue (recharges) per day
        recharges_by_day = db.session.query(
            func.date(Recharge.date).label('day'),
            func.sum(Recharge.amount)
        ).filter(Recharge.date >= datetime.combine(days_ago, datetime.min.time())).group_by('day').all()
        
        revenue_map = {}
        for r in recharges_by_day:
            day_key = r[0]
            if isinstance(day_key, str):
                try:
                    day_key = datetime.strptime(day_key, '%Y-%m-%d').date()
                except ValueError:
                    pass
            revenue_map[day_key] = float(r[1] or 0.0)

        # Compile data for Chart.js
        chart_confirmed = []
        chart_cancelled = []
        chart_revenue = []
        current_date = days_ago
        while current_date <= today:
            # Use both date object and string to be safe against different DB backends
            day_str = current_date.strftime('%Y-%m-%d')
            chart_confirmed.append(confirmed_map.get(current_date) or confirmed_map.get(day_str) or 0)
            chart_cancelled.append(cancelled_map.get(current_date) or cancelled_map.get(day_str) or 0)
            rev_val = revenue_map.get(current_date) or revenue_map.get(day_str) or 0.0
            chart_revenue.append(round(rev_val, 2))
            current_date += timedelta(days=1)

    else:
        # Space Manager: Specific to managed locations
        # Get manager's locations
        my_locations = Location.query.filter_by(manager_id=admin_user.id).all()
        my_location_ids = [loc.id for loc in my_locations]
        total_locations = len(my_location_ids)

        # Get rooms in these locations
        my_rooms = Room.query.filter(Room.location_id.in_(my_location_ids)).all() if my_location_ids else []
        my_room_ids = [room.id for room in my_rooms]

        if my_room_ids:
            my_bookings_all = Booking.query.filter(Booking.room_id.in_(my_room_ids)).all()
            my_bookings = [b for b in my_bookings_all if b.start_time >= datetime.combine(days_ago, datetime.min.time())]
            total_bookings = len(my_bookings)
            
            # Sum of total price of confirmed bookings on manager's rooms for last N days
            total_revenue_val = sum(b.total_price or 0.0 for b in my_bookings if b.status in ['confirmed', 'upcoming', None])
            total_revenue = round(total_revenue_val, 2)

            my_user_ids = {b.user_id for b in my_bookings}
            total_users = len(my_user_ids)

            # Confirmed per day
            confirmed_by_day = db.session.query(
                func.date(Booking.start_time).label('day'),
                func.count(Booking.id)
            ).filter(
                Booking.start_time >= datetime.combine(days_ago, datetime.min.time()),
                Booking.room_id.in_(my_room_ids),
                (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
            ).group_by('day').all()
            confirmed_map = {}
            for b in confirmed_by_day:
                day_key = b[0]
                if isinstance(day_key, str):
                    try:
                        from datetime import date as dt_date
                        day_key = dt_date.fromisoformat(day_key)
                    except ValueError:
                        pass
                confirmed_map[day_key] = b[1]
                
            # Cancelled per day
            cancelled_by_day = db.session.query(
                func.date(func.coalesce(Booking.cancelled_at, Booking.start_time)).label('day'),
                func.count(Booking.id)
            ).filter(
                func.coalesce(Booking.cancelled_at, Booking.start_time) >= datetime.combine(days_ago, datetime.min.time()),
                Booking.room_id.in_(my_room_ids),
                Booking.status == 'cancelled'
            ).group_by('day').all()
            cancelled_map = {}
            for b in cancelled_by_day:
                day_key = b[0]
                if isinstance(day_key, str):
                    try:
                        from datetime import date as dt_date
                        day_key = dt_date.fromisoformat(day_key)
                    except ValueError:
                        pass
                cancelled_map[day_key] = b[1]

            # Revenue per day
            revenue_by_day = db.session.query(
                func.date(Booking.start_time).label('day'),
                func.sum(Booking.total_price)
            ).filter(
                Booking.start_time >= datetime.combine(days_ago, datetime.min.time()),
                Booking.room_id.in_(my_room_ids),
                (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
            ).group_by('day').all()
            revenue_map = {}
            for r in revenue_by_day:
                day_key = r[0]
                if isinstance(day_key, str):
                    try:
                        from datetime import date as dt_date
                        day_key = dt_date.fromisoformat(day_key)
                    except ValueError:
                        pass
                revenue_map[day_key] = float(r[1] or 0.0)

            # Compile Chart.js datasets
            chart_confirmed = []
            chart_cancelled = []
            chart_revenue = []
            current_date = days_ago
            while current_date <= today:
                day_str = current_date.strftime('%Y-%m-%d')
                chart_confirmed.append(confirmed_map.get(current_date) or confirmed_map.get(day_str) or 0)
                chart_cancelled.append(cancelled_map.get(current_date) or cancelled_map.get(day_str) or 0)
                chart_revenue.append(round(revenue_map.get(current_date) or revenue_map.get(day_str) or 0.0, 2))
                current_date += timedelta(days=1)
        else:
            total_bookings = 0
            total_revenue = 0.0
            total_users = 0
            chart_confirmed = [0] * days
            chart_cancelled = [0] * days
            chart_revenue = [0.0] * days

    return templates.TemplateResponse(request, 'home.html', {
        "request": request, 
        "admin_user": admin_user,
        "days": days,
        "total_users": total_users,
        "total_bookings": total_bookings,
        "total_locations": total_locations,
        "total_revenue": total_revenue,
        "chart_labels": chart_labels,
        "chart_confirmed": chart_confirmed,
        "chart_cancelled": chart_cancelled,
        "chart_revenue": chart_revenue
    })

@admin_bp.get('/users', response_class=HTMLResponse)
def users_page(request: Request, search_email: Optional[str] = None, error: Optional[str] = None, admin_user = Depends(get_admin_user_from_cookie)):
    if search_email:
        users = search_users_by_email(search_email)
    else:
        users = get_all_users()
        
    # Space Manager sees only users who booked their locations
    if admin_user.role == 'space_manager':
        my_locations = [loc.id for loc in get_all_locations() if loc.manager_id == admin_user.id]
        my_rooms = [room.id for room in get_all_rooms() if room.location_id in my_locations]
        my_user_ids = {b.user_id for b in get_all_bookings() if b.room_id in my_rooms}
        users = [u for u in users if u.id in my_user_ids]
        
    all_locations = get_all_locations() if admin_user.role == 'admin' else []
        
    return templates.TemplateResponse(request, 'users.html', {
        "request": request, 
        "users": users, 
        "admin_user": admin_user, 
        "error": error,
        "locations": all_locations
    })

@admin_bp.get('/locations', response_class=HTMLResponse)
def locations_page(request: Request, admin_user = Depends(get_admin_user_from_cookie)):
    locations = get_all_locations()
    if admin_user.role == 'space_manager':
        locations = [loc for loc in locations if loc.manager_id == admin_user.id]
        
    # Admins need all users to assign manager
    all_managers = [u for u in get_all_users() if u.role == 'space_manager'] if admin_user.role == 'admin' else []
    
    return templates.TemplateResponse(request, 'locations.html', {"request": request, "locations": locations, "admin_user": admin_user, "managers": all_managers})

@admin_bp.get('/rooms', response_class=HTMLResponse)
def rooms_page(request: Request, 
               search_query: Optional[str] = None, 
               filter_location_id: Optional[str] = None,
               min_capacity: Optional[str] = None,
               admin_user = Depends(get_admin_user_from_cookie)):
    rooms = get_all_rooms()
    locations = get_all_locations()
    
    if admin_user.role == 'space_manager':
        locations = [loc for loc in locations if loc.manager_id == admin_user.id]
        my_location_ids = [loc.id for loc in locations]
        rooms = [r for r in rooms if r.location_id in my_location_ids]
        
    if search_query:
        search_query_lower = search_query.lower()
        rooms = [r for r in rooms if search_query_lower in r.name.lower()]
        
    if filter_location_id and filter_location_id.isdigit():
        rooms = [r for r in rooms if r.location_id == int(filter_location_id)]
        
    if min_capacity and min_capacity.isdigit():
        rooms = [r for r in rooms if r.capacity >= int(min_capacity)]
        
    return templates.TemplateResponse(request, 'rooms.html', {"request": request, "rooms": rooms, "locations": locations, "admin_user": admin_user})

@admin_bp.post('/users/f_balance/{user_uid}')
async def update_balance(request: Request, user_uid: str, balance: float = Form(...), admin_user = Depends(get_admin_user_from_cookie)):
    if admin_user.role != 'admin':
        return RedirectResponse(url=request.url_for('users_page'), status_code=303)
    create_recharge({'user_id': user_uid, 'amount': balance})
    return RedirectResponse(url=request.url_for('users_page'), status_code=303)

@admin_bp.post('/users/create')
async def create_user_admin(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    password: Optional[str] = Form(None),
    role: str = Form('user'),
    admin_user = Depends(get_admin_user_from_cookie)
):
    if admin_user.role != 'admin':
        return RedirectResponse(url=request.url_for('users_page'), status_code=303)
    
    from services.user_service import get_user_by_email, get_user_by_username, create_user_db
    from urllib.parse import urlencode
    from db.database import db
    
    try:
        if get_user_by_email(email):
            error_msg = f"L'email {email} est déjà utilisé."
            return RedirectResponse(url=f"{request.url_for('users_page')}?{urlencode({'error': error_msg})}", status_code=303)
            
        if get_user_by_username(username):
            error_msg = f"Le nom d'utilisateur {username} est déjà pris."
            return RedirectResponse(url=f"{request.url_for('users_page')}?{urlencode({'error': error_msg})}", status_code=303)
        
        from core.hashing import hash_password
        data = {
            'username': username,
            'email': email,
            'phone': phone,
            'role': role,
            'balance': 0.0,
            'hashed_password': hash_password(password) if password else None,
            'auth_provider': 'local',
            'is_verified': True
        }
        new_user = create_user_db(data)
        
        # Assigner les locations si c'est un space manager
        if role == 'space_manager':
            form_data = await request.form()
            location_ids = form_data.getlist('location_ids')
            if location_ids:
                from models.domain import Location
                for loc_id in location_ids:
                    loc = Location.query.get(int(loc_id))
                    if loc:
                        loc.manager_id = new_user.id
                db.session.commit()
                
    except Exception as e:
        error_msg = f"Erreur lors de la création : {str(e)}"
        return RedirectResponse(url=f"{request.url_for('users_page')}?{urlencode({'error': error_msg})}", status_code=303)
                
    return RedirectResponse(url=request.url_for('users_page'), status_code=303)

@admin_bp.post('/locations')
async def create_location_admin(
    request: Request,
    name: str = Form(...),
    manager_id: Optional[str] = Form(None),
    commission_rate: float = Form(0.15),
    opening_time: str = Form("08:00"),
    closing_time: str = Form("20:00"),
    image: UploadFile = File(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    if admin_user.role != 'admin':
        return RedirectResponse(url=request.url_for('locations_page'), status_code=303)
        
    from datetime import datetime as dt
    from urllib.parse import urlencode

    try:
        op_time = dt.strptime(opening_time, '%H:%M').time()
        cl_time = dt.strptime(closing_time, '%H:%M').time()
        
        if op_time >= cl_time:
            error_msg = "L'heure d'ouverture doit être avant l'heure de fermeture."
            return RedirectResponse(url=f"{request.url_for('locations_page')}?{urlencode({'error': error_msg})}", status_code=303)
            
    except ValueError:
        error_msg = "Format d'heure invalide."
        return RedirectResponse(url=f"{request.url_for('locations_page')}?{urlencode({'error': error_msg})}", status_code=303)

    image_data = await image.read() if image and image.filename else None
    
    # Enforce null logic for empty strings
    manager_id = manager_id if manager_id else None
        
    create_location({'name': name, 'image_data': image_data, 'manager_id': manager_id, 'commission_rate': commission_rate, 'opening_time': opening_time, 'closing_time': closing_time})
    return RedirectResponse(url=request.url_for('locations_page'), status_code=303)

@admin_bp.post('/rooms')
async def create_room_admin(
    request: Request,
    name: str = Form(...),
    capacity: int = Form(...),
    location_id: int = Form(...),
    type_hourly: Optional[str] = Form(None),
    price_hourly: Optional[float] = Form(None),
    type_half_day: Optional[str] = Form(None),
    price_half_day: Optional[float] = Form(None),
    type_full_day: Optional[str] = Form(None),
    price_full_day: Optional[float] = Form(None),
    type_weekly: Optional[str] = Form(None),
    price_weekly: Optional[float] = Form(None),
    image: UploadFile = File(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    from services.booking_service import create_booking_type
    
    # Verify permission
    if admin_user.role == 'space_manager':
        loc = next((l for l in get_all_locations() if l.id == location_id), None)
        if not loc or loc.manager_id != admin_user.id:
            return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)
            
    image_data = await image.read() if image and image.filename else None
    
    # 1. Créer la salle
    new_room = create_room({
        'name': name,
        'capacity': capacity,
        'location_id': location_id,
        'image_data': image_data
    })
    
    # 2. Créer les types de réservation sélectionnés
    if type_hourly == 'on' and price_hourly is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'By Hour', 'duration_minutes': 60, 'price': price_hourly, 'is_active': True})
    if type_half_day == 'on' and price_half_day is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'By Half-Day', 'duration_minutes': 300, 'price': price_half_day, 'is_active': True})
    if type_full_day == 'on' and price_full_day is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'By Day', 'duration_minutes': 720, 'price': price_full_day, 'is_active': True})
    if type_weekly == 'on' and price_weekly is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'By Week', 'duration_minutes': 3600, 'price': price_weekly, 'is_active': True})
        
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

@admin_bp.post('/rooms/delete/{room_id}')
def delete_room_admin(request: Request, room_id: int, admin_user = Depends(get_admin_user_from_cookie)):
    # Verify permission
    if admin_user.role == 'space_manager':
        rooms = get_all_rooms()
        room = next((r for r in rooms if r.id == room_id), None)
        if room:
            loc = next((l for l in get_all_locations() if l.id == room.location_id), None)
            if not loc or loc.manager_id != admin_user.id:
                return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)
                
    delete_room(room_id)
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)


@admin_bp.post('/rooms/{room_id}/booking-types')
async def create_booking_type_admin(
    request: Request,
    room_id: int,
    type_hourly: Optional[str] = Form(None),
    price_hourly: Optional[float] = Form(None),
    type_half_day: Optional[str] = Form(None),
    price_half_day: Optional[float] = Form(None),
    type_full_day: Optional[str] = Form(None),
    price_full_day: Optional[float] = Form(None),
    type_weekly: Optional[str] = Form(None),
    price_weekly: Optional[float] = Form(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    """Ajouter des types de réservation à une salle (formulaire admin)."""
    from services.booking_service import create_booking_type
    # Vérifier permission space_manager
    if admin_user.role == 'space_manager':
        rooms = get_all_rooms()
        room = next((r for r in rooms if r.id == room_id), None)
        if room:
            loc = next((l for l in get_all_locations() if l.id == room.location_id), None)
            if not loc or loc.manager_id != admin_user.id:
                return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

    if type_hourly == 'on' and price_hourly is not None:
        create_booking_type({'room_id': room_id, 'name': 'By Hour', 'duration_minutes': 60, 'price': price_hourly, 'is_active': True})
    if type_half_day == 'on' and price_half_day is not None:
        create_booking_type({'room_id': room_id, 'name': 'By Half-Day', 'duration_minutes': 300, 'price': price_half_day, 'is_active': True})
    if type_full_day == 'on' and price_full_day is not None:
        create_booking_type({'room_id': room_id, 'name': 'By Day', 'duration_minutes': 720, 'price': price_full_day, 'is_active': True})
    if type_weekly == 'on' and price_weekly is not None:
        create_booking_type({'room_id': room_id, 'name': 'By Week', 'duration_minutes': 3600, 'price': price_weekly, 'is_active': True})
        
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)


@admin_bp.post('/rooms/{room_id}/edit')
async def edit_room_admin(
    request: Request,
    room_id: int,
    name: str = Form(...),
    capacity: int = Form(...),
    location_id: int = Form(...),
    image: UploadFile = File(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    """Modifier les informations d'une salle existante."""
    from models.domain import Room

    # Permission check for space manager
    if admin_user.role == 'space_manager':
        room = next((r for r in get_all_rooms() if r.id == room_id), None)
        if room:
            loc = next((l for l in get_all_locations() if l.id == room.location_id), None)
            if not loc or loc.manager_id != admin_user.id:
                return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

    room = Room.query.get(room_id)
    if not room:
        return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

    room.name = name
    room.capacity = capacity
    room.location_id = location_id

    # Only update image if a new one is provided
    if image and image.filename:
        image_data = await image.read()
        if image_data:
            room.image_data = image_data

    db.session.commit()
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)


@admin_bp.post('/rooms/{room_id}/booking-types/{type_id}/delete')
def delete_booking_type_admin(
    request: Request,
    room_id: int,
    type_id: int,
    admin_user = Depends(get_admin_user_from_cookie)
):
    """Supprimer un type de réservation (formulaire admin)."""
    from services.booking_service import delete_booking_type
    delete_booking_type(type_id)
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

@admin_bp.post('/rooms/{room_id}/booking-types/{type_id}/edit')
def edit_booking_type_admin(
    request: Request,
    room_id: int,
    type_id: int,
    name: str = Form(...),
    price: float = Form(...),
    admin_user = Depends(get_admin_user_from_cookie)
):
    from services.booking_service import update_booking_type
    
    # Verify permission
    if admin_user.role == 'space_manager':
        rooms = get_all_rooms()
        room = next((r for r in rooms if r.id == room_id), None)
        if room:
            loc = next((l for l in get_all_locations() if l.id == room.location_id), None)
            if not loc or loc.manager_id != admin_user.id:
                return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)
                
    update_booking_type(type_id, {'name': name, 'price': price})
    return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)

@admin_bp.post('/users/delete/{user_uid}')
def delete_user_admin(request: Request, user_uid: str, admin_user = Depends(get_admin_user_from_cookie)):
    if admin_user.role != 'admin':
        return RedirectResponse(url=request.url_for('users_page'), status_code=303)
    
    if admin_user.id == user_uid:
        from urllib.parse import urlencode
        error_msg = "Vous ne pouvez pas supprimer votre propre compte."
        return RedirectResponse(url=f"{request.url_for('users_page')}?{urlencode({'error': error_msg})}", status_code=303)
        
    try:
        delete_user(user_uid)
    except Exception as e:
        from urllib.parse import urlencode
        error_msg = f"Erreur lors de la suppression : {str(e)}"
        return RedirectResponse(url=f"{request.url_for('users_page')}?{urlencode({'error': error_msg})}", status_code=303)
        
    return RedirectResponse(url=request.url_for('users_page'), status_code=303)

@admin_bp.post('/locations/delete/{location_id}')
def delete_location_admin(request: Request, location_id: int, admin_user = Depends(get_admin_user_from_cookie)):
    if admin_user.role != 'admin':
        return RedirectResponse(url=request.url_for('locations_page'), status_code=303)
    delete_location(location_id)
    return RedirectResponse(url=request.url_for('locations_page'), status_code=303)

@admin_bp.post('/locations/edit/{location_id}')
async def edit_location_admin(
    request: Request, 
    location_id: int, 
    name: str = Form(...), 
    manager_id: Optional[str] = Form(None), 
    commission_rate: Optional[float] = Form(None),
    opening_time: str = Form("08:00"),
    closing_time: str = Form("20:00"),
    admin_user = Depends(get_admin_user_from_cookie)
):
    from models.domain import Location
    from db.database import db
    from datetime import datetime as dt
    
    loc = Location.query.get(location_id)
    if not loc:
        return RedirectResponse(url=request.url_for('locations_page'), status_code=303)

    if admin_user.role == 'admin':
        loc.name = name
        loc.manager_id = manager_id if manager_id else None
        if commission_rate is not None:
            loc.commission_rate = commission_rate

    if admin_user.role in ['admin', 'space_manager']:
        if admin_user.role == 'space_manager' and loc.manager_id != admin_user.id:
            return RedirectResponse(url=request.url_for('locations_page'), status_code=303)
            
        from urllib.parse import urlencode
        try:
            op_time = dt.strptime(opening_time, '%H:%M').time()
            cl_time = dt.strptime(closing_time, '%H:%M').time()
            
            if op_time >= cl_time:
                error_msg = "L'heure d'ouverture doit être avant l'heure de fermeture."
                return RedirectResponse(url=f"{request.url_for('locations_page')}?{urlencode({'error': error_msg})}", status_code=303)
                
            loc.opening_time = op_time
            loc.closing_time = cl_time
            db.session.commit()
            
        except ValueError:
            error_msg = "Format d'heure invalide."
            return RedirectResponse(url=f"{request.url_for('locations_page')}?{urlencode({'error': error_msg})}", status_code=303)
        
    return RedirectResponse(url=request.url_for('locations_page'), status_code=303)

@admin_bp.get('/users/{user_uid}', response_class=HTMLResponse)
def user_detail(request: Request, user_uid: str, admin_user = Depends(get_admin_user_from_cookie)):
    user = get_user_by_id(user_uid)
    if not user:
        return HTMLResponse("User not found", status_code=404)
        
    # Space manager access check
    if admin_user.role == 'space_manager':
        my_locations = [loc.id for loc in get_all_locations() if loc.manager_id == admin_user.id]
        my_rooms = [room.id for room in get_all_rooms() if room.location_id in my_locations]
        has_booked = any(b.room_id in my_rooms for b in user.bookings)
        if not has_booked:
            return HTMLResponse("Accès refusé", status_code=403)
            
    balance = get_user_balance(user_uid)
    transactions = BalanceTransaction.query.filter_by(user_id=user_uid).order_by(BalanceTransaction.created_at.desc()).all()
    return templates.TemplateResponse(request, 'user_detail.html', {"request": request, "user": user, "balance": balance, "transactions": transactions, "admin_user": admin_user})

@admin_bp.get('/locations/{location_id}/rooms', response_class=HTMLResponse)
def location_rooms(request: Request, location_id: int, admin_user = Depends(get_admin_user_from_cookie)):
    location = next((loc for loc in get_all_locations() if loc.id == location_id), None)
    if not location:
        return HTMLResponse("Location not found", status_code=404)
        
    if admin_user.role == 'space_manager' and location.manager_id != admin_user.id:
        return HTMLResponse("Accès refusé", status_code=403)
        
    rooms = [room for room in get_all_rooms() if room.location_id == location_id]
    return templates.TemplateResponse(request, 'location_rooms.html', {"request": request, "location": location, "rooms": rooms, "admin_user": admin_user})

@admin_bp.get('/bookings', response_class=HTMLResponse)
def bookings_page(request: Request, 
                  search_email: Optional[str] = None, 
                  search_date: Optional[str] = None, 
                  search_status: Optional[str] = None,
                  admin_user = Depends(get_admin_user_from_cookie)):
    search_email = search_email.strip().lower() if search_email else ''
    update_expired_bookings()  # Mettre à jour les statuts en BDD avant d'afficher
    bookings = get_all_bookings()
    
    if admin_user.role == 'space_manager':
        my_locations = [loc.id for loc in get_all_locations() if loc.manager_id == admin_user.id]
        my_rooms = [room.id for room in get_all_rooms() if room.location_id in my_locations]
        bookings = [b for b in bookings if b.room_id in my_rooms]
        
    if search_email:
        bookings = [b for b in bookings if b.user and b.user.email and search_email in b.user.email.lower()]
        
    if search_date:
        bookings = [b for b in bookings if b.start_time.strftime('%Y-%m-%d') == search_date]
        
    if search_status:
        if search_status == 'confirmed':
            bookings = [b for b in bookings if b.status in ['confirmed', None]]
        elif search_status == 'upcoming':
            bookings = [b for b in bookings if b.status == 'upcoming']
        else:
            bookings = [b for b in bookings if b.status == search_status]
        
    context = {
        "request": request, 
        "bookings": bookings, 
        "admin_user": admin_user,
        "now": datetime.utcnow()
    }

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return templates.TemplateResponse(request, 'partials/bookings_table.html', context)

    return templates.TemplateResponse(request, 'bookings.html', context)



@admin_bp.get('/transactions', response_class=HTMLResponse)
def transactions_page(request: Request, 
                      search_email: Optional[str] = None, 
                      search_date: Optional[str] = None, 
                      search_type: Optional[str] = None,
                      admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import BalanceTransaction, Location, Room, Booking
    
    query = BalanceTransaction.query
    
    if search_type:
        query = query.filter(BalanceTransaction.type == search_type)
        
    if admin_user.role == 'space_manager':
        # Space Manager sees only transactions of users who booked their locations
        my_locations = Location.query.filter_by(manager_id=admin_user.id).all()
        my_location_ids = [loc.id for loc in my_locations]
        
        my_rooms = Room.query.filter(Room.location_id.in_(my_location_ids)).all() if my_location_ids else []
        my_room_ids = [room.id for room in my_rooms]
        
        if my_room_ids:
            my_user_ids = {b.user_id for b in Booking.query.filter(Booking.room_id.in_(my_room_ids)).all()}
            if my_user_ids:
                query = query.filter(BalanceTransaction.user_id.in_(list(my_user_ids)))
            else:
                return templates.TemplateResponse(request, 'transactions.html', {"request": request, "transactions": [], "admin_user": admin_user})
        else:
            return templates.TemplateResponse(request, 'transactions.html', {"request": request, "transactions": [], "admin_user": admin_user})
            
    transactions = query.order_by(BalanceTransaction.created_at.desc()).all()
    
    if search_email:
        search_email = search_email.strip().lower()
        transactions = [tx for tx in transactions if tx.user and tx.user.email and search_email in tx.user.email.lower()]
        
    if search_date:
        transactions = [tx for tx in transactions if tx.created_at.strftime('%Y-%m-%d') == search_date]
        
    return templates.TemplateResponse(request, 'transactions.html', {"request": request, "transactions": transactions, "admin_user": admin_user})

@admin_bp.get('/profile', response_class=HTMLResponse)
def admin_profile(request: Request, admin_user = Depends(get_admin_user_from_cookie)):
    return templates.TemplateResponse(request, 'profile.html', {"request": request, "admin_user": admin_user})

@admin_bp.post('/profile')
def admin_profile_update(
    request: Request, 
    username: str = Form(...),
    email: str = Form(...),
    phone: str = Form(None),
    current_password: str = Form(...),
    new_password: Optional[str] = Form(None), 
    confirm_password: Optional[str] = Form(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    from core.hashing import hash_password, verify_password
    from db.database import db
    from services.user_service import get_user_by_email, get_user_by_username
    
    # 0. L'admin n'a pas le droit de modifier son propre profil (selon la règle métier)
    if admin_user.role == 'admin':
        return templates.TemplateResponse(request, 'profile.html', {
            "request": request, 
            "admin_user": admin_user, 
            "error": "Les administrateurs ne peuvent pas modifier leur profil."
        })

    # 1. Toujours vérifier le mot de passe actuel pour toute modification
    if not verify_password(current_password, admin_user.hashed_password):
        return templates.TemplateResponse(request, 'profile.html', {
            "request": request, 
            "admin_user": admin_user, 
            "error": "L'ancien mot de passe est incorrect."
        })
    
    # 2. Vérifier l'unicité de l'email s'il a changé
    if email != admin_user.email:
        existing_user = get_user_by_email(email)
        if existing_user:
            return templates.TemplateResponse(request, 'profile.html', {
                "request": request, "admin_user": admin_user, "error": f"L'email {email} est déjà utilisé."
            })
        admin_user.email = email

    # 3. Vérifier l'unicité du nom d'utilisateur s'il a changé
    if username != admin_user.username:
        existing_user = get_user_by_username(username)
        if existing_user:
            return templates.TemplateResponse(request, 'profile.html', {
                "request": request, "admin_user": admin_user, "error": f"Le nom d'utilisateur {username} est déjà pris."
            })
        admin_user.username = username

    # 4. Mettre à jour le téléphone
    admin_user.phone = phone
    
    # 5. Mettre à jour le mot de passe si fourni
    if new_password:
        if new_password != confirm_password:
            return templates.TemplateResponse(request, 'profile.html', {
                "request": request, 
                "admin_user": admin_user, 
                "error": "Les nouveaux mots de passe ne correspondent pas."
            })
        admin_user.hashed_password = hash_password(new_password)
        
    db.session.commit()
    return templates.TemplateResponse(request, 'profile.html', {
        "request": request, 
        "admin_user": admin_user, 
        "success": "Profil mis à jour avec succès"
    })

@admin_bp.get('/revenue_stats', response_class=HTMLResponse)
def revenue_stats_page(request: Request, days: int = 7, admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import Booking, Location, Room
    
    if days not in [7, 30, 90]:
        days = 7

    today = datetime.utcnow().date()
    days_ago = today - timedelta(days=days-1)

    chart_labels = []
    current_date = days_ago
    while current_date <= today:
        chart_labels.append(current_date.strftime('%d/%m'))
        current_date += timedelta(days=1)

    my_location_ids = []
    if admin_user.role == 'space_manager':
        my_locations = Location.query.filter_by(manager_id=admin_user.id).all()
        my_location_ids = [loc.id for loc in my_locations]
    else:
        my_locations = Location.query.all()
        my_location_ids = [loc.id for loc in my_locations]

    my_rooms = Room.query.filter(Room.location_id.in_(my_location_ids)).all() if my_location_ids else []
    my_room_ids = [room.id for room in my_rooms]

    if my_room_ids:
        confirmed_by_day = db.session.query(
            func.date(Booking.start_time).label('day'),
            func.count(Booking.id)
        ).filter(
            Booking.start_time >= datetime.combine(days_ago, datetime.min.time()),
            Booking.room_id.in_(my_room_ids),
            (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
        ).group_by('day').all()
        confirmed_map = { (b[0] if not isinstance(b[0], str) else datetime.strptime(b[0], '%Y-%m-%d').date()): b[1] for b in confirmed_by_day }

        cancelled_by_day = db.session.query(
            func.date(func.coalesce(Booking.cancelled_at, Booking.start_time)).label('day'),
            func.count(Booking.id)
        ).filter(
            func.coalesce(Booking.cancelled_at, Booking.start_time) >= datetime.combine(days_ago, datetime.min.time()),
            Booking.room_id.in_(my_room_ids),
            Booking.status == 'cancelled'
        ).group_by('day').all()
        cancelled_map = { (b[0] if not isinstance(b[0], str) else datetime.strptime(b[0], '%Y-%m-%d').date()): b[1] for b in cancelled_by_day }

        revenue_by_day = db.session.query(
            func.date(Booking.start_time).label('day'),
            func.sum(Booking.total_price)
        ).filter(
            Booking.start_time >= datetime.combine(days_ago, datetime.min.time()),
            Booking.room_id.in_(my_room_ids),
            (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
        ).group_by('day').all()
        revenue_map = { (r[0] if not isinstance(r[0], str) else datetime.strptime(r[0], '%Y-%m-%d').date()): float(r[1] or 0.0) for r in revenue_by_day }

        chart_confirmed = []
        chart_cancelled = []
        chart_revenue = []
        current_date = days_ago
        while current_date <= today:
            day_str = current_date.strftime('%Y-%m-%d')
            chart_confirmed.append(confirmed_map.get(current_date) or confirmed_map.get(day_str) or 0)
            chart_cancelled.append(cancelled_map.get(current_date) or cancelled_map.get(day_str) or 0)
            chart_revenue.append(round(revenue_map.get(current_date) or revenue_map.get(day_str) or 0.0, 2))
            current_date += timedelta(days=1)
    else:
        chart_confirmed = [0] * days
        chart_cancelled = [0] * days
        chart_revenue = [0.0] * days

    locations_stats = []
    for loc in my_locations:
        loc_data = {
            'id': loc.id,
            'name': loc.name,
            'total_revenue': 0.0,
            'rooms': []
        }
        for room in loc.rooms:
            room_revenue_val = db.session.query(func.sum(Booking.total_price)).filter(
                Booking.room_id == room.id,
                Booking.start_time >= datetime.combine(days_ago, datetime.min.time()),
                (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
            ).scalar() or 0.0
            
            room_revenue = round(room_revenue_val, 2)
            
            loc_data['rooms'].append({
                'id': room.id,
                'name': room.name,
                'revenue': room_revenue
            })
            loc_data['total_revenue'] += room_revenue
            
        loc_data['total_revenue'] = round(loc_data['total_revenue'], 2)
        locations_stats.append(loc_data)

    # --- KPI STATS ---
    total_rev_current = sum(chart_revenue)
    total_conf_current = sum(chart_confirmed)
    total_canc_current = sum(chart_cancelled)
    
    total_all_current = total_conf_current + total_canc_current
    cancel_rate_current = round((total_canc_current / total_all_current * 100) if total_all_current > 0 else 0)
    avg_rev_current = round((total_rev_current / total_conf_current) if total_conf_current > 0 else 0)
    
    # Previous period
    prev_days_ago = days_ago - timedelta(days=days)
    prev_end_date = days_ago - timedelta(days=1)
    
    if my_room_ids:
        prev_conf_val = db.session.query(func.count(Booking.id)).filter(
            Booking.start_time >= datetime.combine(prev_days_ago, datetime.min.time()),
            Booking.start_time <= datetime.combine(prev_end_date, datetime.max.time()),
            Booking.room_id.in_(my_room_ids),
            (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
        ).scalar() or 0
        
        prev_canc_val = db.session.query(func.count(Booking.id)).filter(
            func.coalesce(Booking.cancelled_at, Booking.start_time) >= datetime.combine(prev_days_ago, datetime.min.time()),
            func.coalesce(Booking.cancelled_at, Booking.start_time) <= datetime.combine(prev_end_date, datetime.max.time()),
            Booking.room_id.in_(my_room_ids),
            Booking.status == 'cancelled'
        ).scalar() or 0
        
        prev_rev_val = db.session.query(func.sum(Booking.total_price)).filter(
            Booking.start_time >= datetime.combine(prev_days_ago, datetime.min.time()),
            Booking.start_time <= datetime.combine(prev_end_date, datetime.max.time()),
            Booking.room_id.in_(my_room_ids),
            (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
        ).scalar() or 0.0
    else:
        prev_conf_val = 0
        prev_canc_val = 0
        prev_rev_val = 0.0

    total_all_prev = prev_conf_val + prev_canc_val
    cancel_rate_prev = round((prev_canc_val / total_all_prev * 100) if total_all_prev > 0 else 0)
    avg_rev_prev = round((prev_rev_val / prev_conf_val) if prev_conf_val > 0 else 0)

    # % Variations
    def calc_variation(curr, prev):
        if prev == 0:
            return 100 if curr > 0 else 0
        return round(((curr - prev) / prev) * 100)

    # Salle la plus réservée dans tout le réseau
    top_room_booking = db.session.query(
        Booking.room_id, 
        func.count(Booking.id).label('booking_count')
    ).filter(
        Booking.room_id.in_(my_room_ids),
        (Booking.status.in_(['confirmed', 'upcoming'])) | (Booking.status == None)
    ).group_by(Booking.room_id).order_by(desc('booking_count')).first()
    
    top_room = None
    if top_room_booking:
        r_obj = next((r for r in my_rooms if r.id == top_room_booking[0]), None)
        if r_obj:
            top_room = {
                'name': r_obj.name,
                'count': top_room_booking[1],
                'location': r_obj.location.name if r_obj.location else ""
            }

    kpi = {
        'top_room': top_room,
        'revenue': {
            'value': round(total_rev_current),
            'variation': calc_variation(total_rev_current, prev_rev_val)
        },
        'bookings': {
            'value': total_conf_current,
            'variation': calc_variation(total_conf_current, prev_conf_val)
        },
        'cancel_rate': {
            'value': cancel_rate_current,
            'is_good': cancel_rate_current <= 15
        },
        'avg_revenue': {
            'value': avg_rev_current,
            'variation': calc_variation(avg_rev_current, avg_rev_prev)
        }
    }

    return templates.TemplateResponse(request, 'revenue_stats.html', {
        "request": request,
        "admin_user": admin_user,
        "days": days,
        "chart_labels": chart_labels,
        "chart_confirmed": chart_confirmed,
        "chart_cancelled": chart_cancelled,
        "chart_revenue": chart_revenue,
        "locations_stats": locations_stats,
        "kpi": kpi
    })



@admin_bp.get('/earnings', response_class=HTMLResponse, name='admin_earnings')
def earnings_page(request: Request, 
                  location_id: Optional[int] = Query(None), 
                  manager_id: Optional[str] = Query(None), 
                  search_date: Optional[str] = Query(None),
                  selected_month: Optional[str] = Query(None),
                  sort_order: str = Query('desc'),
                  admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import SpaceManagerEarning, User, Location, Room, Booking
    from db.database import db
    from sqlalchemy import func, desc, asc, extract, or_, and_
    from datetime import datetime, timedelta
    import calendar

    # 1. Available Months for filtering (last 12 months)
    available_months = []
    curr_yr, curr_mo = datetime.now().year, datetime.now().month
    for i in range(12):
        mo = curr_mo - i
        yr = curr_yr
        if mo <= 0:
            mo += 12
            yr -= 1
        available_months.append({
            'value': f"{yr}-{mo:02d}",
            'label': f"{calendar.month_name[mo]} {yr}"
        })

    # Default to current month if no filter is set
    if selected_month is None and search_date is None:
        selected_month = datetime.now().strftime("%Y-%m")

    # 2. Fetch Summary Data (Managers -> Locations -> Total Net/Gross/Comm)
    managers_list = User.query.filter_by(role='space_manager').all()
    if admin_user.role == 'space_manager':
        managers_list = [m for m in managers_list if m.id == admin_user.id]

    manager_data = []
    global_total_gross = 0.0
    global_total_comm = 0.0
    global_total_net = 0.0

    for manager in managers_list:
        locs = Location.query.filter_by(manager_id=manager.id).all()
        locations_summary = []
        for loc in locs:
            # Stats per location
            query_stats = db.session.query(
                func.sum(SpaceManagerEarning.gross_amount).label('gross'),
                func.sum(SpaceManagerEarning.commission_amount).label('comm'),
                func.sum(SpaceManagerEarning.net_amount).label('net')
            ).join(Booking, SpaceManagerEarning.booking_id == Booking.id)\
             .join(Room, Booking.room_id == Room.id)\
             .filter(Room.location_id == loc.id)\
             .filter(or_(
                 Booking.status.in_(['confirmed', 'cancelled']),
                 and_(Booking.status == 'upcoming', Booking.start_time <= datetime.utcnow() + timedelta(hours=24))
             ))
            
            if selected_month:
                year, month = map(int, selected_month.split('-'))
                query_stats = query_stats.filter(extract('year', Booking.start_time) == year, 
                                               extract('month', Booking.start_time) == month)
            
            stats = query_stats.first()
            
            locations_summary.append({
                'id': loc.id,
                'name': loc.name,
                'commission_rate': loc.commission_rate,
                'total_gross': round(stats.gross or 0.0, 2),
                'total_comm': round(stats.comm or 0.0, 2),
                'total_net': round(stats.net or 0.0, 2)
            })
        
        m_total_gross = sum(l['total_gross'] for l in locations_summary)
        m_total_comm = sum(l['total_comm'] for l in locations_summary)
        m_total_net = sum(l['total_net'] for l in locations_summary)

        global_total_gross += m_total_gross
        global_total_comm += m_total_comm
        global_total_net += m_total_net

        manager_data.append({
            'id': manager.id,
            'username': manager.username,
            'locations': locations_summary,
            'total_gross': round(m_total_gross, 2),
            'total_comm': round(m_total_comm, 2),
            'total_net': round(m_total_net, 2)
        })

    # 3. Fetch History
    query = SpaceManagerEarning.query.join(Booking, SpaceManagerEarning.booking_id == Booking.id)\
                                     .join(Room, Booking.room_id == Room.id)\
                                     .filter(or_(
                                         Booking.status.in_(['confirmed', 'cancelled']),
                                         and_(Booking.status == 'upcoming', Booking.start_time <= datetime.utcnow() + timedelta(hours=24))
                                     ))
    
    if admin_user.role == 'space_manager':
        query = query.filter(SpaceManagerEarning.manager_id == admin_user.id)
    
    selected_location = None
    selected_manager = None

    if location_id:
        query = query.filter(Room.location_id == location_id)
        selected_location = Location.query.get(location_id)
    elif manager_id:
        query = query.filter(SpaceManagerEarning.manager_id == manager_id)
        selected_manager = User.query.get(manager_id)

    if search_date:
        query = query.filter(func.date(Booking.start_time) == search_date)
    elif selected_month:
        year, month = map(int, selected_month.split('-'))
        query = query.filter(extract('year', Booking.start_time) == year, 
                             extract('month', Booking.start_time) == month)

    # Sorting
    if sort_order == 'asc':
        query = query.order_by(asc(Booking.start_time))
    else:
        query = query.order_by(desc(Booking.start_time))

    earnings = query.all()
    
    return templates.TemplateResponse(request, 'earnings.html', {
        "request": request, 
        "earnings": earnings, 
        "admin_user": admin_user,
        "manager_data": manager_data,
        "global_total_gross": round(global_total_gross, 2),
        "global_total_comm": round(global_total_comm, 2),
        "global_total_net": round(global_total_net, 2),
        "selected_location_id": location_id,
        "selected_location": selected_location,
        "selected_manager_id": manager_id,
        "selected_manager": selected_manager,
        "search_date": search_date,
        "selected_month": selected_month,
        "available_months": available_months,
        "sort_order": sort_order
    })


@admin_bp.get('/payments', response_class=HTMLResponse)
def payments_page(request: Request, manager_id: Optional[str] = Query(None), error: Optional[str] = Query(None), admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import User, Settlement
    from db.database import db
    
    # 1. Access Control: Admins see all, Managers see only themselves
    if admin_user.role not in ['admin', 'space_manager']:
        return RedirectResponse(url="/admin/", status_code=303)

    if admin_user.role == 'space_manager':
        manager_id = admin_user.id # Force manager to see only their history
        managers = [admin_user]
    else:
        # Admin: get all managers
        managers = User.query.filter_by(role='space_manager').all()

    # 2. Compute pending balances
    manager_list = []
    for m in managers:
        pending = get_manager_pending_balance(db.session, m.id)
        manager_list.append({
            'id': m.id,
            'username': m.username,
            'email': m.email,
            'pending_balance': round(pending, 2)
        })
    
    # 3. Get settlement history (filtered by manager_id if provided/forced)
    history = get_settlement_history(db.session, manager_id)
    
    return templates.TemplateResponse(request, 'payments.html', {
        "request": request,
        "admin_user": admin_user,
        "managers": manager_list,
        "history": history,
        "selected_manager_id": manager_id,
        "error": error
    })

@admin_bp.post('/payments/create')
async def process_payment(
    request: Request,
    manager_id: str = Form(...),
    amount: float = Form(...),
    notes: Optional[str] = Form(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    from db.database import db
    from urllib.parse import urlencode
    if admin_user.role != 'admin':
        return RedirectResponse(url="/admin/", status_code=303)
        
    try:
        create_settlement(db.session, manager_id, amount, notes)
    except Exception as e:
        error_msg = str(e.detail) if hasattr(e, 'detail') else str(e)
        return RedirectResponse(url=f"{request.url_for('payments_page')}?{urlencode({'error': error_msg})}", status_code=303)
        
    return RedirectResponse(url=request.url_for('payments_page'), status_code=303)

@admin_bp.post('/payments/delete/{settlement_id}')
def cancel_payment(request: Request, settlement_id: int, admin_user = Depends(get_admin_user_from_cookie)):
    from db.database import db
    if admin_user.role != 'admin':
        return RedirectResponse(url="/admin/", status_code=303)
        
    try:
        delete_settlement(db.session, settlement_id)
    except Exception:
        pass
        
    return RedirectResponse(url=request.url_for('payments_page'), status_code=303)
