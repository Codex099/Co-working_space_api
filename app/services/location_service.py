from models.domain import Location, Room
from db.database import db
import base64

def get_all_locations():
    return Location.query.all()

def create_location(data):
    image_data = data.get('image_data')
    location = Location(
        name=data['name'],
        image_data=image_data,
        manager_id=data.get('manager_id')
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
        slot_price=data['slot_price'],
        slot_duration=data['slot_duration'],
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
        result.append({
            "id": loc.id,
            "name": loc.name,
            "image_base64": image_base64
        })
    return result, 200

def get_rooms_by_location_name(location_name):
    location = next((loc for loc in get_all_locations() if loc.name == location_name), None)
    if not location:
        return {"error": "Location not found"}, 404

    rooms = [room for room in get_all_rooms() if room.location_id == location.id]
    result = []
    for room in rooms:
        image_base64 = None
        if getattr(room, "image_data", None):
            image_base64 = base64.b64encode(room.image_data).decode('utf-8')
        result.append({
            "id": room.id,
            "name": room.name,
            "capacity": room.capacity,
            "slot_price": room.slot_price,
            "slot_duration": room.slot_duration,
            "image_base64": image_base64
        })
    return result, 200
