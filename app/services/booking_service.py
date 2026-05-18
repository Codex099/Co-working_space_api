from models.domain import Booking
from db.database import db
from datetime import datetime, timedelta, time
import base64

def get_all_bookings():
    return Booking.query.all()

def create_booking_db(data, commit=True):
    if isinstance(data['date'], str):
        date_obj = datetime.strptime(data['date'], "%Y-%m-%d").date()
    else:
        date_obj = data['date']
    if isinstance(data['start_time'], str):
        time_obj = datetime.strptime(data['start_time'], "%H:%M").time()
    else:
        time_obj = data['start_time']

    booking = Booking(
        user_id=data['user_id'],
        room_id=data['room_id'],
        date=date_obj,
        start_time=time_obj,
        slot_count=data['slot_count'],
        total_price=data.get('total_price')
    )
    db.session.add(booking)
    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return booking

def create_booking(data):
    from fastapi import HTTPException
    from services.user_service import get_user_by_uid, insert_balance_tx
    from services.location_service import get_all_rooms
    user = get_user_by_uid(data['user_id'])
    room = next((r for r in get_all_rooms() if r.id == data['room_id']), None)
    if not user or not room:
        return {"error": "User or room not found"}, 404

    slot_price = room.slot_price
    total_price = slot_price * data['slot_count']

    if user.balance < total_price:
        raise HTTPException(status_code=402, detail="Insufficient balance")

    user.balance -= total_price
    db.session.add(user)

    booking = create_booking_db({
        "user_id": data['user_id'],
        "room_id": data['room_id'],
        "date": data['date'],
        "start_time": data['start_time'],
        "slot_count": data['slot_count'],
        "total_price": total_price
    }, commit=False)

    insert_balance_tx(
        db_session=db.session,
        user=user,
        tx_type='booking',
        amount=-total_price,
        ref_id=booking.id,
        description=f"Réservation salle #{room.id}"
    )

    db.session.commit()

    return {"message": "Booking created", "booking_id": booking.id}, 201

def get_available_slots_range(room_id, start_date_str, end_date_str):
    from services.location_service import get_all_rooms
    room = next((r for r in get_all_rooms() if r.id == room_id), None)
    if not room:
        return {"error": "Room not found"}, 404

    slot_duration = room.slot_duration
    opening_time = time(8, 0)
    closing_time = time(20, 0)

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    result = {}

    for n in range((end_date - start_date).days + 1):
        current_date = start_date + timedelta(days=n)
        slots = []
        current = datetime.combine(current_date, opening_time)
        closing = datetime.combine(current_date, closing_time)
        while current + timedelta(minutes=slot_duration) <= closing:
            slots.append(current.time().strftime('%H:%M'))
            current += timedelta(minutes=slot_duration)

        bookings = [
            b for b in get_all_bookings()
            if b.room_id == room_id and str(b.date) == str(current_date)
        ]

        unavailable = set()
        for booking in bookings:
            booking_start = datetime.combine(booking.date, booking.start_time)
            for i in range(booking.slot_count):
                slot_time = (booking_start + timedelta(minutes=i * slot_duration)).time().strftime('%H:%M')
                unavailable.add(slot_time)

        available_slots = [slot for slot in slots if slot not in unavailable]
        result[str(current_date)] = {
            "available_slots": available_slots,
            "unavailable_slots": list(unavailable)
        }

    return result, 200

def get_user_reservations(user_uid):
    from services.location_service import get_all_rooms, get_all_locations
    bookings = [b for b in get_all_bookings() if b.user_id == user_uid]
    result = []
    for b in bookings:
        rooms = get_all_rooms()
        room = next((r for r in rooms if r.id == b.room_id), None)
        locations = get_all_locations()
        location = next((l for l in locations if l.id == room.location_id), None) if room else None
        image_base64 = None
        if getattr(room, "image_data", None):
            image_base64 = base64.b64encode(room.image_data).decode('utf-8')
        result.append({
            "room_name": room.name if room else "",
            "location": location.name if location else "",
            "date": b.date.strftime("%Y-%m-%d"),
            "start_time": b.start_time.strftime("%H:%M"),
            "slot_count": b.slot_count,
            "price": b.total_price,
            "room_image": f"data:image/jpeg;base64,{image_base64}" if image_base64 else "",
            "status": "Confirmed"
        })
    return result, 200
