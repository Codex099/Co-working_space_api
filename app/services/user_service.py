from models.domain import User
from db.database import db
from core.hashing import hash_password, verify_password
from core.jwt import create_access_token
from services.email_service import (
    generate_code, send_verification_email,
    verification_codes, pending_local_users
)
import uuid

# ============================================================
#  USER SERVICE — Logique métier auth hybride
#  ┌─────────────────────────────────────────────────────┐
#  │  LOCAL SIGNUP FLOW :                                │
#  │  1. local_signup_request() → génère code + envoie  │
#  │  2. confirm_local_signup() → vérifie code + crée   │
#  │  3. local_login()          → vérifie mdp → JWT     │
#  ├─────────────────────────────────────────────────────┤
#  │  FIREBASE FLOW :                                    │
#  │  1. firebase_auth_or_create() → vérifie token      │
#  │                               → crée si nouveau    │
#  │                               → retourne JWT local │
#  └─────────────────────────────────────────────────────┘
# ============================================================


# ─── Helpers DB ──────────────────────────────────────────────

def get_user_by_email(email: str):
    return User.query.filter_by(email=email).first()

def get_user_by_phone(phone: str):
    return User.query.filter_by(phone=phone).first()

def get_user_by_uid(uid: str):
    """Cherche par id (UUID interne)."""
    return User.query.get(uid)

def get_user_by_firebase_uid(firebase_uid: str):
    return User.query.filter_by(firebase_uid=firebase_uid).first()

def get_user_balance(uid: str):
    user = get_user_by_uid(uid)
    return user.balance if user else 0.0

def get_all_users():
    return User.query.all()

def save_user(user):
    db.session.commit()

def delete_user(uid: str):
    user = get_user_by_uid(uid)
    if not user:
        return False
    db.session.delete(user)
    db.session.commit()
    return True


# ─── Auth locale ─────────────────────────────────────────────

def local_signup_request(data: dict):
    """
    Étape 1 du signup local.
    Valide les données, génère un code et envoie l'email de vérification.
    """
    email = data["email"].lower().strip()

    # Vérifier si l'email est déjà utilisé
    if get_user_by_email(email):
        return {"error": "Email déjà utilisé"}, 400

    # Générer et stocker le code temporaire
    code = generate_code()
    verification_codes[email] = code
    pending_local_users[email] = {
        "username": data["username"],
        "email":    email,
        "phone":    data["phone"],
        "password": data["password"],   # sera hashé à la confirmation
    }

    # Envoyer le code par email
    sent = send_verification_email(email, code, username=data["username"])
    if not sent:
        return {"error": "Erreur lors de l'envoi de l'email"}, 500

    return {"message": "Code de vérification envoyé", "email": email}, 200


def confirm_local_signup(email: str, code: str):
    """
    Étape 2 du signup local.
    Vérifie le code et crée le user en DB.
    """
    email = email.lower().strip()
    expected = verification_codes.get(email)

    if not expected:
        return {"error": "Aucun code trouvé pour cet email"}, 400
    if code != expected:
        return {"error": "Code invalide"}, 401

    pending = pending_local_users.get(email)
    if not pending:
        return {"error": "Données utilisateur introuvables"}, 400

    # Créer le user avec mot de passe hashé
    user = User(
        id              = str(uuid.uuid4()),
        email           = pending["email"],
        username        = pending["username"],
        phone           = pending["phone"],
        hashed_password = hash_password(pending["password"]),   # hash bcrypt
        auth_provider   = "local",
        firebase_uid    = None,                                  # local → pas de firebase_uid
        is_verified     = True,                                  # code confirmé = email vérifié
    )
    db.session.add(user)
    db.session.commit()

    # Nettoyer les données temporaires
    del verification_codes[email]
    del pending_local_users[email]

    # Générer le JWT
    token = create_access_token({"sub": user.id, "email": user.email})
    return {"message": "Compte créé avec succès", "access_token": token, "user_id": user.id}, 201


def local_login(email: str, password: str):
    """
    Connexion avec email + mot de passe.
    Retourne un JWT local si les credentials sont corrects.
    """
    email = email.lower().strip()
    user = get_user_by_email(email)

    if not user:
        return {"error": "Email ou mot de passe incorrect"}, 401

    if user.auth_provider != "local":
        return {"error": f"Ce compte utilise {user.auth_provider}. Connectez-vous via Google."}, 400

    if not user.hashed_password or not verify_password(password, user.hashed_password):
        return {"error": "Email ou mot de passe incorrect"}, 401

    if not user.is_verified:
        return {"error": "Veuillez vérifier votre email avant de vous connecter"}, 403

    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user": {
            "id":       user.id,
            "email":    user.email,
            "username": user.username,
            "role":     user.role,
            "balance":  user.balance,
        }
    }, 200


# ─── Auth Firebase ────────────────────────────────────────────

def firebase_auth_or_create(firebase_token: str, phone: str = None):
    """
    Vérifie le token Firebase et crée/récupère le user en DB.
    Retourne un JWT local unifié (même flow que auth locale).
    """
    try:
        from firebase_admin import auth as firebase_auth
        decoded = firebase_auth.verify_id_token(firebase_token)
    except Exception:
        return {"error": "Token Firebase invalide"}, 401

    firebase_uid = decoded["uid"]
    email        = decoded.get("email", "")
    username     = decoded.get("name", email.split("@")[0])
    provider     = decoded.get("firebase", {}).get("sign_in_provider", "firebase")

    # Chercher le user par firebase_uid ou email
    user = get_user_by_firebase_uid(firebase_uid) or get_user_by_email(email)

    if not user:
        # Nouveau user Firebase → créer en DB
        user = User(
            id            = str(uuid.uuid4()),
            email         = email,
            username      = username,
            phone         = phone,
            auth_provider = provider,
            firebase_uid  = firebase_uid,
            hashed_password = None,      # Firebase → pas de mdp local
            is_verified   = True,        # Firebase a déjà vérifié l'email
        )
        db.session.add(user)
        db.session.commit()
    else:
        # User existant → mettre à jour le firebase_uid si manquant
        if not user.firebase_uid:
            user.firebase_uid = firebase_uid
            db.session.commit()

    # Générer notre propre JWT (même format que auth locale)
    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "user": {
            "id":       user.id,
            "email":    user.email,
            "username": user.username,
            "role":     user.role,
            "balance":  user.balance,
        }
    }, 200


# ─── Fonctions utilitaires (conservées) ──────────────────────

def create_user_db(data: dict):
    """Création directe en DB (utilisé par l'admin)."""
    user = User(
        id              = str(uuid.uuid4()),
        firebase_uid    = data.get("firebase_uid"),
        username        = data["username"],
        email           = data["email"],
        phone           = data.get("phone"),
        role            = data.get("role", "user"),
        balance         = data.get("balance", 0.0),
        auth_provider   = data.get("auth_provider", "firebase" if data.get("firebase_uid") else "local"),
        hashed_password = data.get("hashed_password"),
        is_verified     = data.get("is_verified", True),
    )
    db.session.add(user)
    db.session.commit()
    return user

def create_user(data: dict):
    if not data or not all(k in data for k in ("username", "email")):
        return {"error": "Données manquantes"}, 400
    if get_user_by_email(data["email"]):
        return {"error": "Email déjà utilisé"}, 400
    user = create_user_db(data)
    return {"message": "Utilisateur créé", "user_id": user.id}, 201

def get_user_by_email_logic(email: str):
    user = get_user_by_email(email)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404
    return _user_to_dict(user), 200

def get_user_by_uid_logic(uid: str):
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404
    return _user_to_dict(user), 200

def update_user_by_uid(uid: str, data: dict):
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404
    if "username" in data: user.username = data["username"]
    if "email"    in data: user.email    = data["email"]
    if "phone"    in data: user.phone    = data["phone"]
    save_user(user)
    return {"message": "Profil mis à jour"}, 200

def _user_to_dict(user) -> dict:
    return {
        "id":           user.id,
        "firebase_uid": user.firebase_uid,
        "username":     user.username,
        "email":        user.email,
        "phone":        user.phone,
        "role":         user.role,
        "balance":      user.balance,
        "auth_provider":user.auth_provider,
        "is_verified":  user.is_verified,
    }

