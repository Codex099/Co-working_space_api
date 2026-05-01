from pydantic import BaseModel
from typing import Optional


class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    number: int
    role: Optional[str] = 'Normal user'
    balance: Optional[float] = 0.0


class LoginRequest(BaseModel):
    email: str
    password: str


class SignupRequest(BaseModel):
    name: str
    email: str
    password: str
    number: int


class ConfirmSignupRequest(BaseModel):
    email: str
    code: str


class UpdateUserRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    number: Optional[int] = None


class BookingCreate(BaseModel):
    user_id: int
    room_id: int
    date: str
    start_time: str
    slot_count: int
