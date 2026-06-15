from models.domain import Booking, BookingType
from db.database import db
from datetime import datetime, timedelta, time
import base64



# ─── Utils ───────────────────────────────────────────
def get_room_schedule(room_id):
    from models.domain import Room
    from datetime import time as dtime
    room = Room.query.get(room_id)
    if room and room.location:
        return room.location.opening_time, room.location.closing_time, room.location.commission_rate, room.location.manager_id
    return dtime(8, 0), dtime(20, 0), 0.15, None

def log_manager_earning(db_session, booking_id, amount, commission_rate, manager_id):
    from models.domain import SpaceManagerEarning
    if manager_id and amount:
        commission = round(amount * commission_rate, 2)
        net = round(amount - commission, 2)
        earning = SpaceManagerEarning(
            booking_id=booking_id,
            manager_id=manager_id,
            gross_amount=amount,
            commission_amount=commission,
            net_amount=net
        )
        db_session.add(earning)

# ─── Booking Types ───────────────────────────────────────────

def get_booking_types_by_room(room_id):
    """Retourne tous les types actifs d'une salle."""
    return BookingType.query.filter_by(room_id=room_id, is_active=True).all()

def get_booking_type_by_id(type_id):
    return BookingType.query.get(type_id)

def create_booking_type(data):
    # Vérifier l'existence d'un type avec le même nom pour cette salle
    existing = BookingType.query.filter_by(room_id=data['room_id'], name=data['name']).first()
    if existing:
        return existing # Empêche d'ajouter un doublon

    bt = BookingType(
        room_id=data['room_id'],
        name=data['name'],
        duration_minutes=data['duration_minutes'],
        price=data['price'],
        is_active=data.get('is_active', True)
    )
    db.session.add(bt)
    db.session.commit()
    return bt

def update_booking_type(type_id, data):
    bt = BookingType.query.get(type_id)
    if not bt:
        return None
    if 'name' in data:
        bt.name = data['name']
    if 'duration_minutes' in data:
        bt.duration_minutes = data['duration_minutes']
    if 'price' in data:
        bt.price = data['price']
    if 'is_active' in data:
        bt.is_active = data['is_active']
    db.session.commit()
    return bt

def delete_booking_type(type_id):
    bt = BookingType.query.get(type_id)
    if not bt:
        return False
    db.session.delete(bt)
    db.session.commit()
    return True


# ─── Disponibilité ───────────────────────────────────────────

def is_available(room_id, start_dt, duration_minutes):
    """
    Vérifie si la salle est disponible pour l'intervalle demandé.
    end_dt est calculé depuis start_dt + duration_minutes.
    Retourne True si disponible, False sinon.
    Les réservations annulées ('cancelled') sont ignorées.
    """
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    # Récupérer toutes les réservations ACTIVES de cette salle qui chevauchent l'intervalle demandé
    # Chevauchement : b.start_time < end_dt AND b.end_time > start_dt
    bookings = Booking.query.filter(
        Booking.room_id == room_id,
        Booking.start_time < end_dt,
        Booking.end_time > start_dt,
        Booking.status != 'cancelled'   # ⚠️ ignorer les réservations annulées
    ).first()

    if bookings:
        return False
    return True

# ─── Création de réservation ─────────────────────────────────

def get_all_bookings():
    return Booking.query.all()

def update_expired_bookings():
    """Vérifie les réservations 'upcoming' dont le temps est passé et les passe en 'confirmed'."""
    now = datetime.utcnow()
    expired_bookings = Booking.query.filter(
        Booking.status == 'upcoming',
        Booking.start_time <= now
    ).all()
    
    if expired_bookings:
        for b in expired_bookings:
            b.status = 'confirmed'
        db.session.commit()
    return len(expired_bookings)

def create_booking(data):
    from fastapi import HTTPException
    from services.user_service import get_user_by_uid, insert_balance_tx

    user = get_user_by_uid(data['user_id'])
    bt   = get_booking_type_by_id(data['booking_type_id'])

    if not user:
        return {"error": "Utilisateur introuvable"}, 404
        
    if not user.is_verified or not user.phone:
        return {"error": "votre numéro de téléphone avant de pouvoir réserver."}, 403
        
    if not bt:
        return {"error": "Type de réservation introuvable"}, 404
    if not bt.is_active:
        return {"error": "Ce type de réservation n'est plus disponible"}, 400

    # Parse date
    if isinstance(data['date'], str):
        date_obj = datetime.strptime(data['date'], "%Y-%m-%d").date()
    else:
        date_obj = data['date']

    # ─── Cas 1: Réservation Semaine (3600 minutes = 5 jours consécutifs de 08:00 à 20:00) ───
    if bt.duration_minutes > 720:  # ex: Semaine (3600 min)
        total_price = bt.price
        if user.balance < total_price:
            return {"error": "Solde insuffisant"}, 402

        loc_op, loc_cl, loc_comm, loc_mgr = get_room_schedule(bt.room_id)
        start_dt = datetime.combine(date_obj, loc_op)
        end_dt = start_dt + timedelta(days=4)
        end_dt = datetime.combine(end_dt.date(), loc_cl)

        # Vérifier la disponibilité de la plage entière (en une seule requête via is_available)
        if not is_available(bt.room_id, start_dt, int((end_dt - start_dt).total_seconds() / 60)):
            return {"error": f"La salle n'est pas disponible pour toute la semaine"}, 409

        # Débiter le solde
        user.balance -= total_price
        db.session.add(user)

        booking = Booking(
            user_id=data['user_id'],
            room_id=bt.room_id,
            booking_type_id=bt.id,
            start_time=start_dt,
            end_time=end_dt,
            total_price=total_price
        )
        db.session.add(booking)
        db.session.flush()

        insert_balance_tx(
            db_session=db.session,
            user=user,
            tx_type='booking',
            amount=-total_price,
            ref_id=booking.id
        )
        log_manager_earning(db.session, booking.id, total_price, loc_comm, loc_mgr)
        db.session.commit()
        return {"message": "Réservations de semaine créées avec succès", "booking_ids": [booking.id]}, 201

    # ─── Cas 2: Réservation Journée (720 minutes = 1 jour entier de 08:00 à 20:00) ───
    elif bt.duration_minutes == 720:
        total_price = bt.price
        if user.balance < total_price:
            return {"error": "Solde insuffisant"}, 402

        loc_op, loc_cl, loc_comm, loc_mgr = get_room_schedule(bt.room_id)
        start_dt = datetime.combine(date_obj, loc_op)
        end_dt = datetime.combine(date_obj, loc_cl)
        
        if not is_available(bt.room_id, start_dt, 720):
            return {"error": f"La salle n'est pas disponible pour la journée du {date_obj.strftime('%Y-%m-%d')}"}, 409

        # Débiter le solde
        user.balance -= total_price
        db.session.add(user)

        booking = Booking(
            user_id=data['user_id'],
            room_id=bt.room_id,
            booking_type_id=bt.id,
            start_time=start_dt,
            end_time=end_dt,
            total_price=total_price
        )
        db.session.add(booking)
        db.session.flush()

        insert_balance_tx(
            db_session=db.session,
            user=user,
            tx_type='booking',
            amount=-total_price,
            ref_id=booking.id
        )
        log_manager_earning(db.session, booking.id, total_price, loc_comm, loc_mgr)
        db.session.commit()
        return {"message": "Réservation de journée créée avec succès", "booking_ids": [booking.id]}, 201

    # ─── Cas 3: Réservation Horaire et Demi-journée (durée <= 300 min) ───
    else:
        loc_op, loc_cl, loc_comm, loc_mgr = get_room_schedule(bt.room_id)
        start_time_str = data.get('start_time')
        end_time_str = data.get('end_time')

        if not start_time_str or not end_time_str:
            return {"error": "Heure de début et heure de fin requises"}, 400

        try:
            if isinstance(start_time_str, str):
                start_time_obj = datetime.strptime(start_time_str, "%H:%M").time()
            else:
                start_time_obj = start_time_str

            if isinstance(end_time_str, str):
                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
            else:
                end_time_obj = end_time_str
        except ValueError:
            return {"error": "Format d'heure invalide (HH:MM)"}, 400

        start_dt = datetime.combine(date_obj, start_time_obj)
        end_dt = datetime.combine(date_obj, end_time_obj)

        if end_dt <= start_dt:
            return {"error": "L'heure de fin doit être supérieure à l'heure de début"}, 400

        duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
        if not is_available(bt.room_id, start_dt, duration_minutes):
            return {"error": f"La plage horaire de {start_time_str} à {end_time_str} n'est pas disponible"}, 409

        slots_count = duration_minutes / bt.duration_minutes
        if slots_count <= 0:
            return {"error": "Durée invalide"}, 400

        total_price = bt.price * slots_count

        if user.balance < total_price:
            return {"error": "Solde insuffisant"}, 402

        user.balance -= total_price
        db.session.add(user)

        created_booking_ids = []
        from models.domain import BalanceTransaction, SpaceManagerEarning

        # Rechercher des réservations existantes adjacentes en BD (avec DateTime)
        existing_bookings = db.session.query(Booking).filter(
            Booking.user_id == data['user_id'],
            Booking.room_id == bt.room_id,
            Booking.booking_type_id == bt.id,
            (Booking.start_time >= datetime.combine(date_obj, time.min)) & 
            (Booking.end_time <= datetime.combine(date_obj, time.max))
        ).all()

        left_booking = None
        right_booking = None
        for eb in existing_bookings:
            if eb.end_time == start_dt:
                left_booking = eb
            elif eb.start_time == end_dt:
                right_booking = eb

        if left_booking and right_booking:
            left_booking.end_time = right_booking.end_time
            left_booking.total_price = (left_booking.total_price or 0.0) + total_price + (right_booking.total_price or 0.0)
            
            db.session.query(BalanceTransaction).filter(
                BalanceTransaction.ref_id == right_booking.id,
                BalanceTransaction.type == 'booking'
            ).update({BalanceTransaction.ref_id: left_booking.id}, synchronize_session=False)

            # Update manager earnings to point to the new main booking
            db.session.query(SpaceManagerEarning).filter(
                SpaceManagerEarning.booking_id == right_booking.id
            ).update({SpaceManagerEarning.booking_id: left_booking.id}, synchronize_session=False)

            db.session.delete(right_booking)
            db.session.flush()

            insert_balance_tx(
                db_session=db.session,
                user=user,
                tx_type='booking',
                amount=-total_price,
                ref_id=left_booking.id
            )
            log_manager_earning(db.session, left_booking.id, total_price, loc_comm, loc_mgr)
            created_booking_ids.append(left_booking.id)

        elif left_booking:
            left_booking.end_time = end_dt
            left_booking.total_price = (left_booking.total_price or 0.0) + total_price
            db.session.flush()

            insert_balance_tx(
                db_session=db.session,
                user=user,
                tx_type='booking',
                amount=-total_price,
                ref_id=left_booking.id
            )
            log_manager_earning(db.session, left_booking.id, total_price, loc_comm, loc_mgr)
            created_booking_ids.append(left_booking.id)

        elif right_booking:
            right_booking.start_time = start_dt
            right_booking.total_price = (right_booking.total_price or 0.0) + total_price
            db.session.flush()

            insert_balance_tx(
                db_session=db.session,
                user=user,
                tx_type='booking',
                amount=-total_price,
                ref_id=right_booking.id
            )
            log_manager_earning(db.session, right_booking.id, total_price, loc_comm, loc_mgr)
            created_booking_ids.append(right_booking.id)

        else:
            booking = Booking(
                user_id=data['user_id'],
                room_id=bt.room_id,
                booking_type_id=bt.id,
                start_time=start_dt,
                end_time=end_dt,
                total_price=total_price
            )
            db.session.add(booking)
            db.session.flush()

            insert_balance_tx(
                db_session=db.session,
                user=user,
                tx_type='booking',
                amount=-total_price,
                ref_id=booking.id
            )
            log_manager_earning(db.session, booking.id, total_price, loc_comm, loc_mgr)
            created_booking_ids.append(booking.id)

        db.session.commit()
        return {"message": "Réservations créées avec succès", "booking_ids": created_booking_ids}, 201


# ─── Réservations utilisateur ────────────────────────────────

def get_user_reservations(user_uid):
    from services.location_service import get_all_rooms, get_all_locations
    bookings  = sorted([b for b in get_all_bookings() if b.user_id == user_uid], key=lambda b: b.start_time)
    rooms     = get_all_rooms()
    locations = get_all_locations()
    result    = []
    now       = datetime.utcnow()

    for b in bookings:
        room     = next((r for r in rooms if r.id == b.room_id), None)
        location = next((l for l in locations if l.id == room.location_id), None) if room else None
        image_b64 = None
        if getattr(room, "image_data", None):
            image_b64 = base64.b64encode(room.image_data).decode('utf-8')

        total_duration = int((b.end_time - b.start_time).total_seconds() / 60)

        # Calcul annulation : possible uniquement si confirmed ET plus de 24h avant
        seconds_until_start = (b.start_time - now).total_seconds()
        hours_until_start   = max(0, int(seconds_until_start / 3600))
        is_confirmed        = (b.status if b.status else "confirmed") == "confirmed"
        can_cancel          = is_confirmed and seconds_until_start >= 24 * 3600

        # Calcul du statut à afficher : on utilise maintenant celui stocké en BDD
        # mais on s'assure d'avoir appelé update_expired_bookings() avant.
        if b.status == 'cancelled':
            display_status = "Annulée"
        elif b.status == 'upcoming':
            display_status = "Prochaine"
        else:
            display_status = "Confirmée"

        result.append({
            "booking_id":        b.id,
            "room_name":         room.name if room else "",
            "location":          location.name if location else "",
            "booking_type":      b.booking_type.name,
            "start_date":        b.start_time.strftime("%Y-%m-%d"),
            "start_time":        b.start_time.strftime("%H:%M"),
            "end_date":          b.end_time.strftime("%Y-%m-%d"),
            "end_time":          b.end_time.strftime("%H:%M"),
            "duration_min":      total_duration,
            "price":             b.total_price,
            "room_image":        f"data:image/jpeg;base64,{image_b64}" if image_b64 else "",
            "status":            display_status,
            "internal_status":   b.status if b.status else "confirmed",
            "cancelled_at":      b.cancelled_at.strftime("%Y-%m-%d %H:%M") if b.cancelled_at else None,
            "refund_amount":     b.refund_amount,
            # Champs pour Flutter (annulation)
            "can_cancel":        can_cancel,           # True = bouton annuler visible
            "hours_until_start": hours_until_start,    # Heures restantes avant le debut
        })
    return result, 200



# ─── Annulation de réservation ───────────────────────────────

def cancel_booking(booking_id: int, user_uid: str):
    """
    Annule une réservation avec les règles suivantes :
    - La réservation doit appartenir à l'utilisateur authentifié.
    - L'annulation n'est autorisée que si le début est dans plus de 24h.
    - Remboursement de 50% du prix total sur le solde du client.
    - Enregistre une BalanceTransaction de type 'cancellation'.
    """
    from services.user_service import get_user_by_uid, insert_balance_tx

    # 1. Chercher la réservation
    booking = Booking.query.get(booking_id)
    if not booking:
        return {"error": "Réservation introuvable"}, 404

    # 2. Vérifier que la réservation appartient bien à ce user
    if booking.user_id != user_uid:
        return {"error": "Accès refusé : cette réservation ne vous appartient pas"}, 403

    # 3. Vérifier que la réservation n'est pas déjà annulée
    if booking.status == 'cancelled':
        return {"error": "Cette réservation est déjà annulée"}, 400

    # 4. Vérifier la règle des 24 heures
    now = datetime.utcnow()
    time_until_start = booking.start_time - now
    if time_until_start.total_seconds() < 24 * 3600:
        hours_left = max(0, int(time_until_start.total_seconds() / 3600))
        return {
            "error": f"Impossible d'annuler : le début de la réservation est dans moins de 24h "
                     f"({hours_left}h restantes). L'annulation doit être effectuée au moins 24h à l'avance."
        }, 409

    # 5. Calculer le remboursement à 50%
    total_price   = booking.total_price or 0.0
    refund_amount = round(total_price * 0.50, 2)

    # 6. Récupérer l'utilisateur et créditer le solde
    user = get_user_by_uid(user_uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404

    user.balance += refund_amount
    db.session.add(user)

    # 7. Mettre à jour la réservation
    booking.status        = 'cancelled'
    booking.cancelled_at  = now
    booking.refund_amount = refund_amount
    db.session.add(booking)
    db.session.flush()

    # 7.5 Mettre à jour les revenus du Space Manager
    # Le manager gagne maintenant une commission sur la partie non-remboursée (pénalité)
    remaining_amount = total_price - refund_amount
    earning_list = getattr(booking, 'earnings', [])
    if earning_list:
        commission_rate = 0.15
        if booking.room and booking.room.location:
            commission_rate = booking.room.location.commission_rate
            
        for e in earning_list:
            e.gross_amount      = remaining_amount
            e.commission_amount = round(remaining_amount * commission_rate, 2)
            e.net_amount        = round(remaining_amount - e.commission_amount, 2)
            db.session.add(e)

    # 8. Enregistrer la transaction de remboursement
    insert_balance_tx(
        db_session=db.session,
        user=user,
        tx_type='cancellation',
        amount=refund_amount,
        ref_id=booking.id
    )

    db.session.commit()

    return {
        "message":       "Réservation annulée avec succès",
        "booking_id":    booking_id,
        "refund_amount": refund_amount,
        "new_balance":   round(user.balance, 2),
        "note":          "50% du prix a été remboursé sur votre solde."
    }, 200

def get_occupied_slots(room_id, booking_type_id=None, date_str=None, start_date_str=None, end_date_str=None):
    """
    Retourne les slots/dates occupés pour une salle donnée, tous types de réservation confondus.
    booking_type_id est optionnel : s'il est fourni, il permet de calculer les créneaux horaires
    selon la durée du type. Sinon, on renvoie toutes les plages occupées.
    """
    from datetime import date as dt_date
    bt = None
    duration = None
    if booking_type_id is not None:
        bt = get_booking_type_by_id(booking_type_id)
        if not bt or bt.room_id != room_id:
            return {"error": "Type de réservation invalide pour cette salle"}, 400
        duration = bt.duration_minutes

    # Cas 1: Date unique spécifiée
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Format de date invalide (YYYY-MM-DD)"}, 400

        occupied_slots = []
        if duration is not None and duration <= 720:
            loc_op, loc_cl, _, _ = get_room_schedule(room_id)
            opening = datetime.combine(date_obj, loc_op)
            closing = datetime.combine(date_obj, loc_cl)
            current = opening
            while current + timedelta(minutes=duration) <= closing:
                if not is_available(room_id, current, duration):
                    occupied_slots.append(current.strftime("%H:%M"))
                current += timedelta(minutes=duration)
        elif duration is not None and duration > 720:
            loc_op, loc_cl, _, _ = get_room_schedule(room_id)
            start_dt = datetime.combine(date_obj, loc_op)
            if not is_available(room_id, start_dt, duration):
                occupied_slots.append(loc_op.strftime('%H:%M'))
        else:
            # Pas de booking_type_id fourni : vérifier si la journée est occupée
            loc_op, loc_cl, _, _ = get_room_schedule(room_id)
            start_dt = datetime.combine(date_obj, loc_op)
            end_dt   = datetime.combine(date_obj, loc_cl)
            bookings_day = Booking.query.filter(
                Booking.room_id == room_id,
                Booking.start_time < end_dt,
                Booking.end_time > start_dt
            ).all()
            if bookings_day:
                occupied_slots.append("08:00")

        return {
            "room_id": room_id,
            "booking_type_id": booking_type_id,
            "booking_type": bt.name if bt else None,
            "date": date_str,
            "occupied_slots": occupied_slots
        }, 200

    # Cas 2: Plage de dates
    if not start_date_str:
        start_date = dt_date.today()
    else:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Format de start_date invalide (YYYY-MM-DD)"}, 400

    if not end_date_str:
        # Cherche la date de la réservation la plus lointaine pour cette salle
        last_booking = Booking.query.filter(
            Booking.room_id == room_id,
            Booking.status != 'cancelled'
        ).order_by(Booking.end_time.desc()).first()

        if last_booking and last_booking.end_time.date() > start_date:
            end_date = last_booking.end_time.date()
        else:
            # Aucune réservation dans le futur : on ne vérifie que la semaine en cours
            end_date = start_date + timedelta(days=7)
    else:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            return {"error": "Format de end_date invalide (YYYY-MM-DD)"}, 400

    loc_op, loc_cl, _, _ = get_room_schedule(room_id)
    opening_time = loc_op
    closing_time = loc_cl

    # ─── Semaine : retourner les plages de semaines occupées ───
    if duration is not None and duration > 720:
        # ⚠️ On ne filtre PAS par booking_type_id ici :
        # toute réservation existante (quel que soit son type) bloque la salle.
        week_bookings = Booking.query.filter(
            Booking.room_id == room_id,
            Booking.start_time >= datetime.combine(start_date, time.min),
            Booking.end_time   <= datetime.combine(end_date,   time.max)
        ).order_by(Booking.start_time).all()

        occupied_weeks = []
        covered_dates  = set()
        occupied_slots_dict = {}

        for b in week_bookings:
            w_start = b.start_time.date()
            if w_start not in covered_dates:
                w_end = b.end_time.date()
                occupied_weeks.append({
                    "start_date": w_start.strftime("%Y-%m-%d"),
                    "start_time": b.start_time.strftime("%H:%M"),
                    "end_date":   w_end.strftime("%Y-%m-%d"),
                    "end_time":   b.end_time.strftime("%H:%M")
                })
                # Marquer tous les jours couverts par ce booking
                current = w_start
                while current <= w_end:
                    covered_dates.add(current)
                    loc_op, loc_cl, _, _ = get_room_schedule(room_id)
                    occupied_slots_dict[current.strftime("%Y-%m-%d")] = [loc_op.strftime('%H:%M')]
                    current += timedelta(days=1)

        return {
            "room_id":          room_id,
            "booking_type_id":  booking_type_id,
            "booking_type":     bt.name if bt else None,
            "start_date":       start_date.strftime("%Y-%m-%d"),
            "end_date":         end_date.strftime("%Y-%m-%d"),
            "occupied_periods": occupied_weeks,
            "occupied_slots":   occupied_slots_dict
        }, 200

    # ─── Horaire / Demi-journée / Journée : slots par jour ───
    # is_available() vérifie TOUS les bookings (sans filtre booking_type_id) → correct par design.
    occupied_slots_by_date = {}

    for n in range((end_date - start_date).days + 1):
        current_date = start_date + timedelta(days=n)
        current_date_str = current_date.strftime("%Y-%m-%d")

        day_occupied = []

        if duration is None:
            # Pas de type fourni : marquer la journée entière si occupée
            opening = datetime.combine(current_date, opening_time)
            closing = datetime.combine(current_date, closing_time)
            all_bookings_day = Booking.query.filter(
                Booking.room_id == room_id,
                Booking.start_time < closing,
                Booking.end_time   > opening
            ).all()
            if all_bookings_day:
                day_occupied.append(opening_time.strftime('%H:%M'))
        else:
            opening = datetime.combine(current_date, opening_time)
            closing = datetime.combine(current_date, closing_time)
            current = opening
            # is_available vérifie tous les bookings existants (tous types confondus)
            while current + timedelta(minutes=duration) <= closing:
                if not is_available(room_id, current, duration):
                    day_occupied.append(current.strftime("%H:%M"))
                current += timedelta(minutes=duration)

        if day_occupied:
            occupied_slots_by_date[current_date_str] = day_occupied

    return {
        "room_id":         room_id,
        "booking_type_id": booking_type_id,
        "booking_type":    bt.name if bt else None,
        "start_date":      start_date.strftime("%Y-%m-%d"),
        "end_date":        end_date.strftime("%Y-%m-%d"),
        "occupied_slots":  occupied_slots_by_date
    }, 200
