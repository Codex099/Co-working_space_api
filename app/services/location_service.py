from models.domain import Location, Room, BookingType
from db.database import db
import base64

def get_all_locations():
    return Location.query.all()

def create_location(data):
    image_data = data.get('image_data')
    from datetime import datetime as dt
    opening_time = dt.strptime(data.get('opening_time', '08:00'), '%H:%M').time() if data.get('opening_time') else dt.strptime('08:00', '%H:%M').time()
    closing_time = dt.strptime(data.get('closing_time', '20:00'), '%H:%M').time() if data.get('closing_time') else dt.strptime('20:00', '%H:%M').time()
    
    location = Location(
        name=data['name'],
        image_data=image_data,
        manager_id=data.get('manager_id'),
        commission_rate=data.get('commission_rate', 0.15),
        opening_time=opening_time,
        closing_time=closing_time
    )
    db.session.add(location)
    db.session.commit()
    return location

def delete_location(location_id):
    location = Location.query.get(location_id)
    if not location:
        return False
    db.session.delete(location)
    db.session.commit()
    return True

def get_all_rooms():
    return Room.query.all()

def create_room(data):
    room = Room(
        name=data['name'],
        capacity=data['capacity'],
        location_id=data['location_id'],
        image_data=data.get('image_data')
    )
    db.session.add(room)
    db.session.commit()
    return room

def delete_room(room_id):
    room = Room.query.get(room_id)
    if not room:
        return False
    db.session.delete(room)
    db.session.commit()
    return True

def get_all_locations_logic():
    locations = get_all_locations()
    result = []
    for loc in locations:
        image_base64 = None
        if loc.image_data:
            image_base64 = base64.b64encode(loc.image_data).decode('utf-8')
            
        mid_time = None
        if loc.opening_time and loc.closing_time:
            from datetime import datetime, timedelta
            dummy = datetime.today().date()
            op_dt = datetime.combine(dummy, loc.opening_time)
            cl_dt = datetime.combine(dummy, loc.closing_time)
            total_minutes = int((cl_dt - op_dt).total_seconds() / 60)
            mid_time = (op_dt + timedelta(minutes=total_minutes // 2)).time().strftime('%H:%M')

        result.append({
            "id": loc.id,
            "name": loc.name,
            "opening_time": loc.opening_time.strftime('%H:%M') if loc.opening_time else None,
            "closing_time": loc.closing_time.strftime('%H:%M') if loc.closing_time else None,
            "mid_time": mid_time,
            "image_base64": image_base64
        })
    return result, 200

def get_rooms_by_location_name(location_name):
    location = next((loc for loc in get_all_locations() if loc.name == location_name), None)
    if not location:
        return {"error": "Location not found"}, 404

    rooms = [room for room in get_all_rooms() if room.location_id == location.id]
    result = []
    
    mid_time = None
    op_time_str = None
    cl_time_str = None
    if location.opening_time and location.closing_time:
        from datetime import datetime, timedelta
        dummy = datetime.today().date()
        op_dt = datetime.combine(dummy, location.opening_time)
        cl_dt = datetime.combine(dummy, location.closing_time)
        total_minutes = int((cl_dt - op_dt).total_seconds() / 60)
        mid_time = (op_dt + timedelta(minutes=total_minutes // 2)).time().strftime('%H:%M')
        op_time_str = location.opening_time.strftime('%H:%M')
        cl_time_str = location.closing_time.strftime('%H:%M')

    for room in rooms:
        image_base64 = None
        if getattr(room, "image_data", None):
            image_base64 = base64.b64encode(room.image_data).decode('utf-8')

        booking_types = [
            {
                "id": bt.id,
                "name": bt.name,
                "duration_minutes": bt.resolved_duration_minutes,
                "price": bt.price,
                "is_active": bt.is_active
            }
            for bt in BookingType.query.filter_by(room_id=room.id, is_active=True).all()
        ]

        result.append({
            "id": room.id,
            "name": room.name,
            "capacity": room.capacity,
            "booking_types": booking_types,
            "image_base64": image_base64,
            "opening_time": op_time_str,
            "closing_time": cl_time_str,
            "mid_time": mid_time
        })
    return result, 200
