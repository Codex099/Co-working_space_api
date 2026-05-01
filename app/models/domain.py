from sqlalchemy import Column, Integer, String, Float, ForeignKey, Date, Time, DateTime, LargeBinary
from sqlalchemy.orm import relationship
from datetime import datetime
from db.database import Base, db, db_session

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    number = Column(Integer, unique=True, nullable=False)
    password = Column(String(100), nullable=False)
    role = Column(String(20), default='Normal user')
    balance = Column(Float, default=0.0)
    bookings = relationship('Booking', backref='user') 
    recharges = relationship('Recharge', backref='user')

class Location(Base):
    __tablename__ = 'locations'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    image_data = Column(LargeBinary, nullable=True) #largebinary -----> pour image
    rooms = relationship('Room', backref='location')

class Room(Base):
    __tablename__ = 'rooms'
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    capacity = Column(Integer, nullable=False)
    slot_price = Column(Float, nullable=False)  
    slot_duration = Column(Integer, nullable=False, default=60)  #ppar défault 1h
    location_id = Column(Integer, ForeignKey('locations.id'), nullable=False)
    bookings = relationship('Booking', backref='room')
    image_data = Column(LargeBinary)  

class Booking(Base):
    __tablename__ = 'bookings'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    room_id = Column(Integer, ForeignKey('rooms.id'), nullable=False)
    date = Column(Date, nullable=False)  
    start_time = Column(Time, nullable=False)
    slot_count = Column(Integer, nullable=False)    # nombre de slot réservé
    total_price = Column(Float, nullable=True) 

class Recharge(Base):   #ychof + ymodifier
    __tablename__ = 'recharges'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    amount = Column(Float, nullable=False)
    date = Column(DateTime, default=datetime.utcnow)
