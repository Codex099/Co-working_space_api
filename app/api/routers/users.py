from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from services.user_service import (
    create_user,
    get_user_by_email_logic,
    get_user_by_uid_logic,
    get_balance_history_logic,
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
    forgot_password_request_logic,
    reset_password_confirm_logic,
    verify_reset_code_logic,
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
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyResetCodeRequest,
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


@router.post('/auth/local/forgot-password', tags=["Auth Locale"])
async def forgot_password_route(data: ForgotPasswordRequest):
    """
    Demande de réinitialisation de mot de passe.
    → Envoie un code par email si le compte existe.
    """
    resp, code = forgot_password_request_logic(data.email)
    return JSONResponse(content=resp, status_code=code)


@router.post('/auth/local/verify-reset-code', tags=["Auth Locale"])
async def verify_reset_code_route(data: VerifyResetCodeRequest):
    """
    Étape 2 : Vérification du code reçu par email.
    → Retourne un token temporaire si le code est valide.
    """
    resp, code = verify_reset_code_logic(data.email, data.code)
    return JSONResponse(content=resp, status_code=code)


@router.post('/auth/local/reset-password', tags=["Auth Locale"])
async def reset_password_route(data: ResetPasswordRequest):
    """
    Étape 3 : Réinitialisation définitive du mot de passe avec le token.
    """
    resp, code = reset_password_confirm_logic(data.email, data.token, data.new_password)
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
    resp, code = firebase_auth_or_create(data.firebase_token)
    return JSONResponse(content=resp, status_code=code)



# ============================================================
#  ROUTES PROTÉGÉES (JWT requis — Firebase OU local)
# ============================================================

@router.get('/me')
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

@router.get('/me/balance-history')
def get_balance_history_route(current_user: dict = Depends(get_current_user)):
    resp, code = get_balance_history_logic(current_user["uid"])
    return JSONResponse(content=resp, status_code=code)

@router.patch('/me', tags=["update"])
def update_profile_route(data: UpdateUserRequest, current_user: dict = Depends(get_current_user)):
    """
    Met à jour les informations de profil (ex: username) de l'utilisateur connecté.
    """
    resp, code = update_user_by_uid(current_user["uid"], data.model_dump(exclude_unset=True))
    return JSONResponse(content=resp, status_code=code)


@router.get('/users/email/{email}')
def get_user_by_email_route(email: str, current_user: dict = Depends(get_current_user)):
    resp, code = get_user_by_email_logic(email)
    return JSONResponse(content=resp, status_code=code)


@router.patch('/me/password', tags=["update"])
def update_password_route(data: UpdatePasswordRequest, current_user: dict = Depends(get_current_user)):
    resp, code = update_password_logic(
        uid=current_user["uid"],
        new_password=data.new_password,
        old_password=data.old_password
        )
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
