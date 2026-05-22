from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.jwt import decode_access_token

# ============================================================
#  DEPENDENCIES — get_current_user HYBRIDE
#  → Accepte DEUX types de tokens :
#      1. Token Firebase  (uid + email issus de Firebase)
#      2. Token JWT local (uid + email issus de notre propre auth)
#  → Les deux passent par le même Bearer token dans les headers
#  → Le client Flutter/front envoie toujours : Authorization: Bearer <token>
# ============================================================

security = HTTPBearer()

# Firebase optionnel (si non configuré, on skip la vérif Firebase)
try:
    from firebase_admin import auth as firebase_auth
    from core import firebase_config  # initialise Firebase
    FIREBASE_ENABLED = True
except Exception:
    FIREBASE_ENABLED = False
    print("[WARN] Firebase non configuré → seul le JWT local sera accepté")


async def get_current_user(res: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Middleware d'authentification hybride.
    Essaie d'abord Firebase, puis JWT local.
    Retourne un dict unifié : { "uid", "email", "provider" }
    """
    token = res.credentials

    # ── Étape 1 : Essayer Firebase (si activé) ──────────────────────────
    if FIREBASE_ENABLED:
        try:
            decoded = firebase_auth.verify_id_token(token)
            return {
                "uid":      decoded["uid"],
                "email":    decoded.get("email"),
                "provider": "firebase",
                "source":   "firebase"
            }
        except Exception:
            pass  # pas un token Firebase → on essaie JWT local

    # ── Étape 2 : Essayer JWT local ─────────────────────────────────────
    try:
        payload = decode_access_token(token)
        return {
            "uid":      payload.get("sub"),
            "email":    payload.get("email"),
            "provider": "local",
            "source":   "local"
        }
    except Exception:
        pass

    # ── Aucun token valide ───────────────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )


security_optional = HTTPBearer(auto_error=False)

async def get_current_user_optional(res: HTTPAuthorizationCredentials = Depends(security_optional)) -> dict:
    """
    Middleware d'authentification hybride optionnel.
    Retourne le dict utilisateur s'il est authentifié, sinon None.
    """
    if not res or not res.credentials:
        return None
    token = res.credentials

    # ── Étape 1 : Essayer Firebase (si activé) ──────────────────────────
    if FIREBASE_ENABLED:
        try:
            decoded = firebase_auth.verify_id_token(token)
            return {
                "uid":      decoded["uid"],
                "email":    decoded.get("email"),
                "provider": "firebase",
                "source":   "firebase"
            }
        except Exception:
            pass

    # ── Étape 2 : Essayer JWT local ─────────────────────────────────────
    try:
        payload = decode_access_token(token)
        return {
            "uid":      payload.get("sub"),
            "email":    payload.get("email"),
            "provider": "local",
            "source":   "local"
        }
    except Exception:
        pass

    return None


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """Dépendance pour les routes admin uniquement."""
    from services.user_service import get_user_by_uid
    user = get_user_by_uid(current_user["uid"])
    if not user or user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé")
    return current_user

async def get_admin_user_from_cookie(request: Request):
    """Dépendance pour les routes web admin (HTML) utilisant un cookie."""
    token = request.cookies.get("admin_access_token")
    if not token:
        # Redirect to login page
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
    
    try:
        payload = decode_access_token(token)
        uid = payload.get("sub")
        if not uid:
            raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
        
        from services.user_service import get_user_by_uid
        user = get_user_by_uid(uid)
        if not user or user.role not in ["admin", "space_manager"]:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé. Rôle non autorisé.")
        
        # Add user to request state so templates can use it
        request.state.admin_user = user
        return user
    except Exception:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/admin/login"})
