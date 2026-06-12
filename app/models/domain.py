from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, Time, DateTime, LargeBinary, Boolean, Text
from sqlalchemy.orm import relationship
from datetime import datetime, time as dtime
from db.database import Base, db, db_session
import uuid

# ============================================================
#  USER — supporte Firebase ET auth locale
#  - firebase_uid  : rempli si le user vient de Firebase (Google, GitHub...)
#  - hashed_password : rempli si le user s'inscrit en local (email+mdp)
#  - auth_provider : "local" | "google.com" | "github.com" | ...
#  - is_verified   : False par défaut pour local (attend confirmation email)
#                    True directement pour Firebase (déjà vérifié)
# ============================================================
class User(Base):
    __tablename__ = 'users'

    
    id               = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    email            = Column(String(120), unique=True, nullable=False)
    username         = Column(String(100), nullable=False)
    phone            = Column(String(20), nullable=True)   # nullable car Firebase ne donne pas le phone
    role             = Column(String(20), default='user')
    balance          = Column(Float, default=0.0)

    # --- Champs auth hybride ---
    auth_provider    = Column(String(50), nullable=False, default='local')  # "local" | "google.com" | ...
    firebase_uid     = Column(String(128), unique=True, nullable=True)      # NULL si auth locale
    hashed_password  = Column(String(256), nullable=True)                   # NULL si Firebase
    is_verified      = Column(Boolean, default=False)                       # email vérifié ?
    created_at       = Column(DateTime, default=datetime.utcnow)

    bookings         = relationship('Booking', backref='user', cascade="all, delete-orphan")
    recharges        = relationship('Recharge', backref='user', cascade="all, delete-orphan")
    balance_transactions = relationship('BalanceTransaction', backref='user', cascade="all, delete-orphan")


class BalanceTransaction(Base):
    __tablename__ = 'balance_transactions'
    id            = Column(Integer, primary_key=True, autoincrement=True)
    user_id       = Column(String(36), ForeignKey('users.id'), nullable=False, index=True)
    type          = Column(String(20), nullable=False)
    amount        = Column(Float, nullable=False)
    balance_after = Column(Float, nullable=False)
    ref_id        = Column(Integer, nullable=True) # ID of the booking or recharge
    created_at    = Column(DateTime, default=datetime.utcnow)



class Location(Base):
    __tablename__ = 'locations'
    id         = Column(Integer, primary_key=True)
    name       = Column(String(100), nullable=False)
    image_data = Column(LargeBinary, nullable=True)
    manager_id = Column(String(36), ForeignKey('users.id'), nullable=True) # ID of the Space Manager
    commission_rate = Column(Float, default=0.15)
    opening_time    = Column(Time, default=dtime(8, 0))
    closing_time    = Column(Time, default=dtime(20, 0))
    
    manager = relationship('User', foreign_keys=[manager_id])
    rooms      = relationship('Room', backref='location', cascade="all, delete-orphan")

class Room(Base):
    __tablename__ = 'rooms'
    id            = Column(Integer, primary_key=True)
    name          = Column(String(100), nullable=False)
    capacity      = Column(Integer, nullable=False)
    location_id   = Column(Integer, ForeignKey('locations.id'), nullable=False)
    image_data    = Column(LargeBinary)
    bookings      = relationship('Booking', backref='room', cascade="all, delete-orphan")
    booking_types = relationship('BookingType', backref='room', cascade="all, delete-orphan")


class BookingType(Base):
    """Types de réservation personnalisables par salle (ex: Horaire, Demi-journée...)"""
    __tablename__ = 'booking_types'
    id               = Column(Integer, primary_key=True, autoincrement=True)
    room_id          = Column(Integer, ForeignKey('rooms.id'), nullable=False)
    name             = Column(String(100), nullable=False)   # ex: "Horaire", "Demi-journée"
    duration_minutes = Column(Integer, nullable=False)        # durée en minutes
    price            = Column(Float, nullable=False)          # prix en DA
    is_active        = Column(Boolean, default=True)          # activer/désactiver
    bookings         = relationship('Booking', backref='booking_type')


class Booking(Base):
    __tablename__ = 'bookings'
    id              = Column(Integer, primary_key=True)
    user_id         = Column(String(36), ForeignKey('users.id'), nullable=False)  # FK vers users.id (UUID)
    room_id         = Column(Integer, ForeignKey('rooms.id'), nullable=False)
    booking_type_id = Column(Integer, ForeignKey('booking_types.id'), nullable=False)  # FK vers booking_types
    start_time      = Column(DateTime, nullable=False)
    end_time        = Column(DateTime, nullable=False)
    total_price     = Column(Float, nullable=True)
    status          = Column(String(20), nullable=False, default='upcoming')  # 'upcoming' | 'confirmed' | 'cancelled'
    cancelled_at    = Column(DateTime, nullable=True)
    refund_amount   = Column(Float, nullable=True)


class Recharge(Base):
    __tablename__ = 'recharges'
    id      = Column(Integer, primary_key=True)
    user_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # FK vers users.id (UUID)
    amount  = Column(Float, nullable=False)
    date    = Column(DateTime, default=datetime.utcnow)

    
class SpaceManagerEarning(Base):
    __tablename__ = 'space_manager_earning'
    id      = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey('bookings.id'), nullable=False)  # FK vers bookings.id (UUID)
    manager_id = Column(String(36), ForeignKey('users.id'), nullable=False)  # FK vers users.id (UUID)
    gross_amount  = Column(Float, nullable=False)
    commission_amount  = Column(Float, nullable=False)
    net_amount  = Column(Float, nullable=False)
    created_at    = Column(DateTime, default=datetime.utcnow)
    settlement_id = Column(Integer, ForeignKey('settlements.id'), nullable=True)

    booking = relationship('Booking', backref='earning')


class Settlement(Base):
    __tablename__ = 'settlements'
    id          = Column(Integer, primary_key=True)
    manager_id  = Column(String(36), ForeignKey('users.id'), nullable=False)
    amount_paid = Column(Float, nullable=False) # The net amount actually paid to manager
    total_commission = Column(Float, nullable=False) # Commission "cleared" by this settlement
    notes       = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)

    manager  = relationship('User', foreign_keys=[manager_id])
    earnings = relationship('SpaceManagerEarning', backref='settlement_ref')
