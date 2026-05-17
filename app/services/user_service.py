from models.domain import User
from db.database import db
from core.hashing import hash_password, verify_password
from core.jwt import create_access_token
from services.email_service import (
    generate_code, send_verification_email,
    verification_codes, pending_local_users
)
from services.sms_service import generate_sms_code, send_sms_code, phone_codes
import uuid

pending_email_updates: dict = {}
# ============================================================
#  USER SERVICE — Logique métier auth locale + SMS
#  ┌─────────────────────────────────────────────────────┐
#  │  LOCAL SIGNUP FLOW :                                │
#  │  1. local_signup_request() → génère code + envoie  │
#  │  2. confirm_local_signup() → vérifie code + crée   │
#  │  3. local_login()          → vérifie mdp → JWT     │
#  ├─────────────────────────────────────────────────────┤
#  │  PHONE VERIFICATION (Brevo SMS) :                   │
#  │  1. send_phone_code_logic() → envoie SMS            │
#  │  2. verify_phone_code_logic() → vérifie et sauve    │
#  └─────────────────────────────────────────────────────┘
# ============================================================


# ─── Helpers DB ──────────────────────────────────────────────

def get_user_by_email(email: str):
    return User.query.filter_by(email=email).first()

def search_users_by_email(email: str):
    """Recherche partielle par email."""
    return User.query.filter(User.email.like(f"%{email}%")).all()

def get_user_by_username(username: str):
    return User.query.filter_by(username=username).first()

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

    # Créer le user avec mot de passe hashé (sans téléphone — ajouté via /confirm-phone)
    user = User(
        id              = str(uuid.uuid4()),
        email           = pending["email"],
        username        = pending["username"],
        phone           = None,
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


# ─── Vérification téléphone (SMS Brevo) ────────────────────────────────

def send_phone_code_logic(uid: str, phone: str):
    """
    Étape 1 : Génère et envoie un code SMS.
    """
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404

    # Vérifier que le numéro n'est pas déjà pris
    existing = get_user_by_phone(phone)
    if existing and existing.id != uid:
        return {"error": "Ce numéro de téléphone est déjà utilisé"}, 409

    code = generate_sms_code()
    phone_codes[phone] = {"code": code, "uid": uid}

    # Envoi du SMS (ou affichage terminal en mode DEV)
    send_sms_code(phone, code)

    return {"message": "Code SMS envoyé avec succès", "phone": phone}, 200


def verify_phone_code_logic(uid: str, phone: str, code: str):
    """
    Étape 2 : Vérifie le code SMS et enregistre le numéro.
    """
    data = phone_codes.get(phone)
    if not data:
        return {"error": "Aucun code en attente pour ce numéro"}, 400

    if data["uid"] != uid:
        return {"error": "Le code n'appartient pas à cet utilisateur"}, 403

    if data["code"] != code:
        return {"error": "Code SMS invalide"}, 401

    # Code correct → on enregistre le téléphone
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404

    user.phone = phone
    db.session.commit()

    # Nettoyage
    del phone_codes[phone]

    return {"message": "Numéro de téléphone vérifié et enregistré", "phone": phone}, 200




# ─── Fonctions utilitaires (conservées) ──────────────────────────────

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
    # email et phone sont retirés pour utiliser les routes sécurisées
    save_user(user)
    return {"message": "Profil mis à jour"}, 200

def update_password_logic(uid: str, old_password: str, new_password: str):
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404
    if not user.hashed_password or not verify_password(old_password, user.hashed_password):
        return {"error": "Ancien mot de passe incorrect"}, 401
    
    user.hashed_password = hash_password(new_password)
    save_user(user)
    return {"message": "Mot de passe mis à jour avec succès"}, 200

def request_email_update_logic(uid: str, new_email: str):
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404
    
    new_email = new_email.lower().strip()
    if get_user_by_email(new_email):
        return {"error": "Cet email est déjà utilisé"}, 409
    
    code = generate_code()
    verification_codes[new_email] = code
    pending_email_updates[new_email] = uid
    
    sent = send_verification_email(new_email, code, username=user.username)
    if not sent:
        return {"error": "Erreur lors de l'envoi de l'email"}, 500
        
    return {"message": "Code de vérification envoyé au nouvel email", "email": new_email}, 200

def confirm_email_update_logic(uid: str, code: str):
    target_email = None
    for email, pending_uid in pending_email_updates.items():
        if pending_uid == uid:
            target_email = email
            break
            
    if not target_email:
        return {"error": "Aucune demande de modification d'email en cours"}, 400
        
    expected_code = verification_codes.get(target_email)
    if not expected_code or expected_code != code:
        return {"error": "Code invalide"}, 401
        
    user = get_user_by_uid(uid)
    if not user:
        return {"error": "Utilisateur introuvable"}, 404
        
    user.email = target_email
    save_user(user)
    
    if target_email in verification_codes:
        del verification_codes[target_email]
    if target_email in pending_email_updates:
        del pending_email_updates[target_email]
    
    return {"message": "Email mis à jour avec succès", "email": target_email}, 200

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

def firebase_auth_or_create(firebase_token: str, phone_fallback: str = None):
    """
    Vérifie le token Firebase ID.
    Récupère ou crée l'utilisateur en base, puis retourne un JWT local.
    """
    from firebase_admin import auth as firebase_auth
    try:
        decoded = firebase_auth.verify_id_token(firebase_token)
    except Exception as e:
        return {"error": f"Token Firebase invalide : {str(e)}"}, 401

    firebase_uid = decoded.get("uid")
    email = decoded.get("email")
    phone = phone_fallback
    name = decoded.get("name") or (email.split("@")[0] if email else "FirebaseUser")

    # 1. Chercher par firebase_uid
    user = get_user_by_firebase_uid(firebase_uid)

    # 2. Sinon, chercher par email
    if not user and email:
        user = get_user_by_email(email)
        if user:
            # Lier le compte local existant à Firebase
            user.firebase_uid = firebase_uid
            user.auth_provider = "firebase"
            if phone and not user.phone:
                user.phone = phone
            save_user(user)

    # 3. Sinon, chercher par téléphone
    if not user and phone:
        user = get_user_by_phone(phone)
        if user:
            user.firebase_uid = firebase_uid
            user.auth_provider = "firebase"
            if email and not user.email:
                user.email = email
            save_user(user)

    # 4. Si toujours introuvable, créer un nouveau compte
    if not user:
        user = User(
            id=str(uuid.uuid4()),
            firebase_uid=firebase_uid,
            username=name,
            email=email or f"{firebase_uid}@firebase.temp", # email unique temporaire si manquant
            phone=phone,
            auth_provider="firebase",
            is_verified=True,
            role="user",
            balance=0.0
        )
        db.session.add(user)
        db.session.commit()

    # Générer notre JWT local
    token = create_access_token({"sub": user.id, "email": user.email})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": _user_to_dict(user)
    }, 200

