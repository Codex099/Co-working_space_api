from passlib.context import CryptContext

# ============================================================
#  HASHING MOT DE PASSE
#  → bcrypt est l'algorithme recommandé (lent = résistant brute-force)
#  → deprecated="auto" migre automatiquement les anciens hash
# ============================================================
pwd_context = CryptContext(schemes=["bcrypt"])


def _truncate_password(password: str) -> str:
    """Truncates password to 72 bytes to prevent bcrypt ValueError."""
    pwd_bytes = password.encode('utf-8')
    if len(pwd_bytes) > 72:
        return pwd_bytes[:72].decode('utf-8', 'ignore')
    return password


def hash_password(password: str) -> str:
    """Hash un mot de passe en clair → bcrypt hash."""
    return pwd_context.hash(_truncate_password(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie si le mot de passe correspond au hash stocké."""
    return pwd_context.verify(_truncate_password(plain_password), hashed_password)
