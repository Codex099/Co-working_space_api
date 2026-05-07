from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
import re

# ============================================================
#  SCHEMAS PYDANTIC — Validation des données entrantes
#  → EmailStr valide automatiquement le format email
#  → Les validators custom ajoutent des règles métier
# ============================================================

# ─── Auth locale ────────────────────────────────────────────

class LocalSignupRequest(BaseModel):
    """Inscription avec email + mot de passe (auth locale)."""
    username: str
    email: EmailStr          # valide le format email automatiquement
    phone: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v):
        """Mot de passe : min 8 chars, 1 majuscule, 1 chiffre."""
        if len(v) < 8:
            raise ValueError("Le mot de passe doit faire au moins 8 caractères")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Le mot de passe doit contenir au moins une majuscule")
        if not re.search(r"\d", v):
            raise ValueError("Le mot de passe doit contenir au moins un chiffre")
        return v

    @field_validator("phone")
    @classmethod
    def phone_format(cls, v):
        """Téléphone : chiffres uniquement, 9–15 caractères."""
        cleaned = re.sub(r"[\s\-\+\(\)]", "", v)
        if not cleaned.isdigit() or not (9 <= len(cleaned) <= 15):
            raise ValueError("Numéro de téléphone invalide")
        return v


class ConfirmEmailRequest(BaseModel):
    """Confirmation du code email reçu."""
    email: EmailStr
    code: str


class LocalLoginRequest(BaseModel):
    """Connexion avec email + mot de passe."""
    email: EmailStr
    password: str


# ─── Auth Firebase ───────────────────────────────────────────

class FirebaseAuthRequest(BaseModel):
    """
    Token Firebase envoyé depuis le client Flutter.
    Le backend le vérifie et crée/récupère le user en DB.
    """
    firebase_token: str
    email:    EmailStr       
    username: str 
    phone:    str    
       
    


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
    email:    Optional[EmailStr] = None
    phone:    Optional[str] = None




# ─── Booking ─────────────────────────────────────────────────

class BookingCreate(BaseModel):
    user_id:    str
    room_id:    int
    date:       str
    start_time: str
    slot_count: int
