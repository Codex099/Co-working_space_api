from pydantic import BaseModel, EmailStr, field_validator, model_validator
from typing import Optional, List, Union
import re

# ============================================================
#  SCHEMAS PYDANTIC — Validation des données entrantes
#  → EmailStr valide automatiquement le format email
#  → Les validators custom ajoutent des règles métier
# ============================================================

# ─── Auth locale ────────────────────────────────────────────

class LocalSignupRequest(BaseModel):
    """Inscription avec email + mot de passe (auth locale). Sans téléphone."""
    username: str
    email: EmailStr          # valide le format email automatiquement
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        """Mot de passe : min 8 chars."""
        if len(v) < 8:
            raise ValueError("Le mot de passe doit faire au moins 8 caractères")
        return v


class ConfirmEmailRequest(BaseModel):
    """Confirmation du code email reçu."""
    email: EmailStr
    code: str


class LocalLoginRequest(BaseModel):
    """Connexion avec email + mot de passe."""
    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    """Demande de réinitialisation de mot de passe."""
    email: EmailStr


class VerifyResetCodeRequest(BaseModel):
    """Vérification du code de réinitialisation."""
    email: EmailStr
    code: str


class ResetPasswordRequest(BaseModel):
    """Confirmation de réinitialisation de mot de passe."""
    email: EmailStr
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v):
        """Mot de passe : min 8 chars."""
        if len(v) < 8:
            raise ValueError("Le mot de passe doit faire au moins 8 caractères")
        return v


# ─── Vérification téléphone (SMS Brevo) ──────────────────────

class SendPhoneCodeRequest(BaseModel):
    """Demande d'envoi d'un code SMS."""
    uid:   str
    phone: str

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v):
        """Téléphone : chiffres uniquement, 9–15 caractères."""
        cleaned = re.sub(r"[\s\-\+\(\)]", "", v)
        if not cleaned.isdigit() or not (9 <= len(cleaned) <= 15):
            raise ValueError("Numéro de téléphone invalide (9–15 chiffres)")
        return v

class VerifyPhoneCodeRequest(BaseModel):
    """Vérification du code SMS reçu."""
    uid:   str
    phone: str
    code:  str


# ─── User général ────────────────────────────────────────────

class UserCreate(BaseModel):
    """Création manuelle (admin)."""
    firebase_uid: Optional[str] = None
    username: str
    email: EmailStr
    phone: Optional[str] = None
    role: Optional[str] = 'user'
    balance: Optional[float] = 0.0


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    # email et phone retirés car gérés par des routes dédiées sécurisées

class UpdatePasswordRequest(BaseModel):
    old_password: Optional[str] = None
    new_password: str

class UpdateEmailRequest(BaseModel):
    new_email: EmailStr

class ConfirmUpdateEmailRequest(BaseModel):
    code: str

class PhoneUpdateRequest(BaseModel):
    phone: str

class PhoneVerifyRequest(BaseModel):
    phone: str
    code: str

class FirebaseAuthRequest(BaseModel):
    firebase_token: str
    



# ─── Booking ─────────────────────────────────────────────────

class BookingCreate(BaseModel):
    """Création d'une réservation via booking_type_id."""
    booking_type_id: int   # FK vers booking_types (contient room_id, duration, price)
    date:            str   # format YYYY-MM-DD
    start_time:      str   # format HH:MM
    end_time:        str   # format HH:MM


# ─── Booking Types (gestion par l'admin) ─────────────────────

class BookingTypeCreate(BaseModel):
    """Création d'un type de réservation pour une salle."""
    room_id:          int
    name:             str          # ex: "Horaire", "Demi-journée", "Semaine"
    duration_minutes: int          # durée en minutes (ex: 60, 300, 720)
    price:            float        # prix en DA
    is_active:        Optional[bool] = True


class BookingTypeUpdate(BaseModel):
    """Mise à jour partielle d'un type de réservation."""
    name:             Optional[str]   = None
    duration_minutes: Optional[int]   = None
    price:            Optional[float] = None
    is_active:        Optional[bool]  = None
