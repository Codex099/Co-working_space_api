from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import base64
import os
from datetime import datetime, timedelta
from sqlalchemy import func
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
from services.booking_service import get_all_bookings
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
def admin_home(request: Request, admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import User, Booking, Location, Room, Recharge, BalanceTransaction

    # Determine date range for the last 7 days (including today)
    today = datetime.utcnow().date()
    seven_days_ago = today - timedelta(days=6)

    # Prepare labels for Chart.js
    chart_labels = []
    current_date = seven_days_ago
    while current_date <= today:
        chart_labels.append(current_date.strftime('%d/%m'))
        current_date += timedelta(days=1)

    if admin_user.role == 'admin':
        # Admin: Global statistics (last 7 days)
        total_users = User.query.filter(User.created_at >= datetime.combine(seven_days_ago, datetime.min.time())).count()
        total_bookings = Booking.query.filter(Booking.start_time >= datetime.combine(seven_days_ago, datetime.min.time())).count()
        total_locations = Location.query.count()
        
        # Total revenue is the sum of recharge amounts (credits added to system) over last 7 days
        total_revenue_val = db.session.query(func.sum(Recharge.amount)).filter(Recharge.date >= datetime.combine(seven_days_ago, datetime.min.time())).scalar() or 0.0
        total_revenue = round(total_revenue_val, 2)

        # 7-day bookings and revenue data
        # Bookings per day (Booking.start_time is now a DateTime)
        bookings_by_day = db.session.query(
            func.date(Booking.start_time).label('day'),
            func.count(Booking.id)
        ).filter(Booking.start_time >= datetime.combine(seven_days_ago, datetime.min.time())).group_by('day').all()
        bookings_map = {}
        for b in bookings_by_day:
            day_key = b[0]
            if isinstance(day_key, str):
                try:
                    from datetime import date as dt_date
                    day_key = dt_date.fromisoformat(day_key)
                except ValueError:
                    pass
            bookings_map[day_key] = b[1]

        # Revenue (recharges) per day
        recharges_by_day = db.session.query(
            func.date(Recharge.date).label('day'),
            func.sum(Recharge.amount)
        ).filter(Recharge.date >= datetime.combine(seven_days_ago, datetime.min.time())).group_by('day').all()
        
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
        chart_bookings = []
        chart_revenue = []
        current_date = seven_days_ago
        while current_date <= today:
            chart_bookings.append(bookings_map.get(current_date, 0))
            rev_val = revenue_map.get(current_date) or revenue_map.get(current_date.strftime('%Y-%m-%d')) or 0.0
            chart_revenue.append(round(rev_val, 2))
            current_date += timedelta(days=1)

        # Recent activities (last 5 balance transactions)
        recent_txs = BalanceTransaction.query.order_by(BalanceTransaction.created_at.desc()).limit(5).all()
        recent_events = []
        for tx in recent_txs:
            recent_events.append({
                'username': tx.user.username if tx.user else 'Inconnu',
                'description': get_tx_description(tx),
                'date': tx.created_at,
                'amount': abs(tx.amount),
                'type': tx.type
            })

    else:
        # Space Manager: Specific to managed locations
        # Get manager's locations
        my_locations = Location.query.filter_by(manager_id=admin_user.id).all()
        my_location_ids = [loc.id for loc in my_locations]
        total_locations = len(my_location_ids)

        # Get rooms in these locations
        my_rooms = Room.query.filter(Room.location_id.in_(my_location_ids)).all() if my_location_ids else []
        my_room_ids = [room.id for room in my_rooms]

        # Get bookings for these rooms
        if my_room_ids:
            my_bookings_all = Booking.query.filter(Booking.room_id.in_(my_room_ids)).all()
            # Filter for the last 7 days only
            my_bookings = [b for b in my_bookings_all if b.start_time >= datetime.combine(seven_days_ago, datetime.min.time())]
            total_bookings = len(my_bookings)
            
            # Sum of total price of bookings on manager's rooms for last 7 days
            total_revenue_val = sum(b.total_price or 0.0 for b in my_bookings)
            total_revenue = round(total_revenue_val, 2)

            # Unique users who booked at least once in last 7 days
            my_user_ids = {b.user_id for b in my_bookings}
            total_users = len(my_user_ids)

            # Bookings per day in the last 7 days
            bookings_by_day = db.session.query(
                func.date(Booking.start_time).label('day'),
                func.count(Booking.id)
            ).filter(Booking.start_time >= datetime.combine(seven_days_ago, datetime.min.time()), Booking.room_id.in_(my_room_ids)).group_by('day').all()
            bookings_map = {}
            for b in bookings_by_day:
                day_key = b[0]
                if isinstance(day_key, str):
                    try:
                        from datetime import date as dt_date
                        day_key = dt_date.fromisoformat(day_key)
                    except ValueError:
                        pass
                bookings_map[day_key] = b[1]

            # Revenue (sum of booking total_price) per day in the last 7 days
            revenue_by_day = db.session.query(
                func.date(Booking.start_time).label('day'),
                func.sum(Booking.total_price)
            ).filter(Booking.start_time >= datetime.combine(seven_days_ago, datetime.min.time()), Booking.room_id.in_(my_room_ids)).group_by('day').all()
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
            chart_bookings = []
            chart_revenue = []
            current_date = seven_days_ago
            while current_date <= today:
                chart_bookings.append(bookings_map.get(current_date, 0))
                chart_revenue.append(round(revenue_map.get(current_date, 0.0), 2))
                current_date += timedelta(days=1)

            # Recent activities for Space Manager (only bookings of their rooms)
            recent_bookings = Booking.query.filter(Booking.room_id.in_(my_room_ids)).order_by(Booking.id.desc()).limit(5).all()
            recent_events = []
            for b in recent_bookings:
                recent_events.append({
                    'username': b.user.username if b.user else 'Inconnu',
                    'description': f"Réservation salle {b.room.name if b.room else ''}",
                    'date': b.start_time,
                    'amount': b.total_price or 0.0,
                    'type': 'booking'
                })
        else:
            total_bookings = 0
            total_revenue = 0.0
            total_users = 0
            chart_bookings = [0] * 30
            chart_revenue = [0.0] * 30
            recent_events = []

    return templates.TemplateResponse(request, 'home.html', {
        "request": request, 
        "admin_user": admin_user,
        "total_users": total_users,
        "total_bookings": total_bookings,
        "total_locations": total_locations,
        "total_revenue": total_revenue,
        "chart_labels": chart_labels,
        "chart_bookings": chart_bookings,
        "chart_revenue": chart_revenue,
        "recent_events": recent_events
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
    balance: float = Form(0.0),
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
            'balance': balance,
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
    image: UploadFile = File(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    if admin_user.role != 'admin':
        return RedirectResponse(url=request.url_for('locations_page'), status_code=303)
        
    image_data = await image.read() if image and image.filename else None
    
    # Enforce null logic for empty strings
    manager_id = manager_id if manager_id else None
        
    create_location({'name': name, 'image_data': image_data, 'manager_id': manager_id})
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
    custom_type_name: Optional[str] = Form(None),
    custom_type_duration: Optional[int] = Form(None),
    custom_type_price: Optional[float] = Form(None),
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
        create_booking_type({'room_id': new_room.id, 'name': '1 Hour', 'duration_minutes': 60, 'price': price_hourly, 'is_active': True})
    if type_half_day == 'on' and price_half_day is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'Half-day', 'duration_minutes': 300, 'price': price_half_day, 'is_active': True})
    if type_full_day == 'on' and price_full_day is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'Day', 'duration_minutes': 720, 'price': price_full_day, 'is_active': True})
    if type_weekly == 'on' and price_weekly is not None:
        create_booking_type({'room_id': new_room.id, 'name': 'Week', 'duration_minutes': 3600, 'price': price_weekly, 'is_active': True})
        
    if custom_type_name and custom_type_duration and custom_type_price is not None:
        create_booking_type({'room_id': new_room.id, 'name': custom_type_name, 'duration_minutes': custom_type_duration, 'price': custom_type_price, 'is_active': True})
    
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
    custom_type_name: Optional[str] = Form(None),
    custom_type_duration: Optional[int] = Form(None),
    custom_type_price: Optional[float] = Form(None),
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
        create_booking_type({'room_id': room_id, 'name': '1 Heure', 'duration_minutes': 60, 'price': price_hourly, 'is_active': True})
    if type_half_day == 'on' and price_half_day is not None:
        create_booking_type({'room_id': room_id, 'name': 'Demi-journée', 'duration_minutes': 300, 'price': price_half_day, 'is_active': True})
    if type_full_day == 'on' and price_full_day is not None:
        create_booking_type({'room_id': room_id, 'name': 'Journée', 'duration_minutes': 720, 'price': price_full_day, 'is_active': True})
    if type_weekly == 'on' and price_weekly is not None:
        create_booking_type({'room_id': room_id, 'name': 'Semaine', 'duration_minutes': 3600, 'price': price_weekly, 'is_active': True})
        
    if custom_type_name and custom_type_duration and custom_type_price is not None:
        create_booking_type({'room_id': room_id, 'name': custom_type_name, 'duration_minutes': custom_type_duration, 'price': custom_type_price, 'is_active': True})
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
def bookings_page(request: Request, search_email: Optional[str] = None, admin_user = Depends(get_admin_user_from_cookie)):
    search_email = search_email.strip().lower() if search_email else ''
    bookings = get_all_bookings()
    
    if admin_user.role == 'space_manager':
        my_locations = [loc.id for loc in get_all_locations() if loc.manager_id == admin_user.id]
        my_rooms = [room.id for room in get_all_rooms() if room.location_id in my_locations]
        bookings = [b for b in bookings if b.room_id in my_rooms]
        
    if search_email:
        bookings = [b for b in bookings if b.user and b.user.email and search_email in b.user.email.lower()]
    return templates.TemplateResponse(request, 'bookings.html', {"request": request, "bookings": bookings, "admin_user": admin_user})

@admin_bp.get('/recharges', response_class=HTMLResponse)
def recharges_page(request: Request, admin_user = Depends(get_admin_user_from_cookie)):
    if admin_user.role == 'space_manager':
        # Recharges are typically global. If you want Space Managers to see recharges of their users:
        my_locations = [loc.id for loc in get_all_locations() if loc.manager_id == admin_user.id]
        my_rooms = [room.id for room in get_all_rooms() if room.location_id in my_locations]
        my_user_ids = {b.user_id for b in get_all_bookings() if b.room_id in my_rooms}
        recharges = [r for r in get_all_recharges() if r.user_id in my_user_ids]
    else:
        recharges = get_all_recharges()
        
    # Trier par date décroissante pour voir les plus récentes en premier
    recharges = sorted(recharges, key=lambda r: r.date, reverse=True)
    return templates.TemplateResponse(request, 'recharges.html', {"request": request, "recharges": recharges, "admin_user": admin_user})

@admin_bp.get('/transactions', response_class=HTMLResponse)
def transactions_page(request: Request, admin_user = Depends(get_admin_user_from_cookie)):
    from models.domain import BalanceTransaction, Location, Room, Booking
    
    if admin_user.role == 'space_manager':
        # Space Manager sees only transactions of users who booked their locations
        my_locations = Location.query.filter_by(manager_id=admin_user.id).all()
        my_location_ids = [loc.id for loc in my_locations]
        
        my_rooms = Room.query.filter(Room.location_id.in_(my_location_ids)).all() if my_location_ids else []
        my_room_ids = [room.id for room in my_rooms]
        
        if my_room_ids:
            my_user_ids = {b.user_id for b in Booking.query.filter(Booking.room_id.in_(my_room_ids)).all()}
            if my_user_ids:
                transactions = BalanceTransaction.query.filter(BalanceTransaction.user_id.in_(list(my_user_ids))).order_by(BalanceTransaction.created_at.desc()).all()
            else:
                transactions = []
        else:
            transactions = []
    else:
        transactions = BalanceTransaction.query.order_by(BalanceTransaction.created_at.desc()).all()
        
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

