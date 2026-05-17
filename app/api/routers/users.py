from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from services.user_service import (
    create_user,
    get_user_by_email_logic,
    get_user_by_uid_logic,
    update_user_by_uid,
    update_password_logic,
    request_email_update_logic,
    confirm_email_update_logic,
    local_signup_request,
    confirm_local_signup,
    local_login,
    send_phone_code_logic,
    verify_phone_code_logic,
    _user_to_dict,
    get_user_by_uid,
    firebase_auth_or_create,
)
from schemas import (
    UserCreate,
    LocalSignupRequest,
    LocalLoginRequest,
    ConfirmEmailRequest,
    SendPhoneCodeRequest,
    VerifyPhoneCodeRequest,
    UpdateUserRequest,
    UpdatePasswordRequest,
    UpdateEmailRequest,
    ConfirmUpdateEmailRequest,
    PhoneUpdateRequest,
    PhoneVerifyRequest,
    FirebaseAuthRequest,
)
from core.dependencies import get_current_user

router = APIRouter()

# ============================================================
#  AUTH LOCALE — Signup en 2 étapes
# ============================================================

@router.post('/auth/local/signup', tags=["Auth Locale"])
async def local_signup_route(data: LocalSignupRequest):
    """
    Étape 1 : Inscription email + mot de passe.
    → Envoie un code de vérification par email.
    → Le user n'est PAS encore créé en DB.
    """
    resp, code = local_signup_request(data.model_dump())
    return JSONResponse(content=resp, status_code=code)


@router.post('/auth/local/confirm-email', tags=["Auth Locale"])
def confirm_email_route(data: ConfirmEmailRequest):
    """
    Étape 2 : Confirmation du code reçu par email.
    → Crée le user en DB + retourne un JWT.
    """
    resp, code = confirm_local_signup(data.email, data.code)
    return JSONResponse(content=resp, status_code=code)


@router.post('/auth/local/login', tags=["Auth Locale"])
async def local_login_route(data: LocalLoginRequest):
    """
    Connexion avec email + mot de passe.
    → Retourne un JWT si les credentials sont corrects.
    """
    resp, code = local_login(data.email, data.password)
    return JSONResponse(content=resp, status_code=code)
# ============================================================
#  AUTH FIREBASE — Token Firebase → JWT local
# ============================================================

@router.post('/auth/firebase', tags=["Auth Firebase"])
async def firebase_auth_route(data: FirebaseAuthRequest):
    """
    Le client Flutter envoie le token Firebase ID.
    → Le backend vérifie avec Firebase Admin SDK.
    → Crée ou récupère le user en DB.
    → Retourne un JWT local (même format que auth locale).
    Après ce point, le client utilise UNIQUEMENT le JWT local.
    """
    resp, code = firebase_auth_or_create(data.firebase_token, data.phone)
    return JSONResponse(content=resp, status_code=code)



# ============================================================
#  ROUTES PROTÉGÉES (JWT requis — Firebase OU local)
# ============================================================

@router.get('/me', tags=["Users"])
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Retourne le profil complet de l'utilisateur connecté.
    Fonctionne avec les deux types de tokens.
    """
    user = get_user_by_uid(current_user["uid"])
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return _user_to_dict(user)


"""@router.get('/users/{uid}', tags=["Users"])
def get_user_by_uid_route(uid: str, current_user: dict = Depends(get_current_user)):
    resp, code = get_user_by_uid_logic(uid)
    return JSONResponse(content=resp, status_code=code)


@router.put('/users/{uid}', tags=["Users"])
def update_user_by_uid_route(uid: str, data: UpdateUserRequest, current_user: dict = Depends(get_current_user)):
    resp, code = update_user_by_uid(uid, data.model_dump(exclude_unset=True))
    return JSONResponse(content=resp, status_code=code)"""


@router.get('/users/email/{email}', tags=["Users"])
def get_user_by_email_route(email: str, current_user: dict = Depends(get_current_user)):
    resp, code = get_user_by_email_logic(email)
    return JSONResponse(content=resp, status_code=code)


@router.put('/me/password', tags=["update"])
def update_password_route(data: UpdatePasswordRequest, current_user: dict = Depends(get_current_user)):
    resp, code = update_password_logic(current_user["uid"], data.old_password, data.new_password)
    return JSONResponse(content=resp, status_code=code)

@router.post('/me/email/request', tags=["update"])
def request_email_update_route(data: UpdateEmailRequest, current_user: dict = Depends(get_current_user)):
    resp, code = request_email_update_logic(current_user["uid"], data.new_email)
    return JSONResponse(content=resp, status_code=code)

@router.post('/me/email/confirm', tags=["update"])
def confirm_email_update_route(data: ConfirmUpdateEmailRequest, current_user: dict = Depends(get_current_user)):
    resp, code = confirm_email_update_logic(current_user["uid"], data.code)
    return JSONResponse(content=resp, status_code=code)
@router.post('/me/phone/send-code', tags=["Téléphone"])
def update_phone_send_code_route(data: PhoneUpdateRequest, current_user: dict = Depends(get_current_user)):
    # Réutilise la logique existante mais force l'UID du token
    resp, code = send_phone_code_logic(current_user["uid"], data.phone)
    return JSONResponse(content=resp, status_code=code)

@router.post('/me/phone/verify-code', tags=["Téléphone"])
def update_phone_verify_code_route(data: PhoneVerifyRequest, current_user: dict = Depends(get_current_user)):
    # Réutilise la logique existante mais force l'UID du token
    resp, code = verify_phone_code_logic(current_user["uid"], data.phone, data.code)
    return JSONResponse(content=resp, status_code=code)
