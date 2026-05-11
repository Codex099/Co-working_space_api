from fastapi import APIRouter, Request, Form, File, UploadFile, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
import base64
import os

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

templates.env.filters['b64encode'] = b64encode_filter
templates.env.filters['zfill'] = zfill_filter

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
    return templates.TemplateResponse(request, 'home.html', {"request": request, "admin_user": admin_user})

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
def rooms_page(request: Request, admin_user = Depends(get_admin_user_from_cookie)):
    rooms = get_all_rooms()
    locations = get_all_locations()
    
    if admin_user.role == 'space_manager':
        locations = [loc for loc in locations if loc.manager_id == admin_user.id]
        my_location_ids = [loc.id for loc in locations]
        rooms = [r for r in rooms if r.location_id in my_location_ids]
        
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
    slot_price: float = Form(...),
    slot_duration: int = Form(...),
    location_id: int = Form(...),
    image: UploadFile = File(None),
    admin_user = Depends(get_admin_user_from_cookie)
):
    # Verify permission
    if admin_user.role == 'space_manager':
        loc = next((l for l in get_all_locations() if l.id == location_id), None)
        if not loc or loc.manager_id != admin_user.id:
            return RedirectResponse(url=request.url_for('rooms_page'), status_code=303)
            
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
    recharges = get_user_recharges(user_uid)
    return templates.TemplateResponse(request, 'user_detail.html', {"request": request, "user": user, "balance": balance, "recharges": recharges, "admin_user": admin_user})

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

