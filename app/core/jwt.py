from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import HTTPException, status
import os

# ============================================================
#  JWT CONFIG
#  → Change SECRET_KEY en production (variable d'environnement)
#  → ALGORITHM HS256 est standard pour les API REST
#  → ACCESS_TOKEN_EXPIRE_MINUTES : durée de vie du token (30 min)
# ============================================================
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "coworking_super_secret_change_in_prod")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 heures


def create_access_token(data: dict, expires_minutes: int = ACCESS_TOKEN_EXPIRE_MINUTES) -> str:
    """Crée un JWT signé avec les données passées."""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_minutes)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Décode et valide un JWT. Lève une HTTPException si invalide."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalide ou expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )
