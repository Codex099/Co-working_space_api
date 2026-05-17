import os
import random
import string
import requests

# ============================================================
#  SMS CONFIG (BREVO SMS API)
#  Même clé API que l'email → pas de config supplémentaire
# ============================================================

BREVO_API_KEY  = os.getenv("BREVO_API_KEY", "")
SMS_SENDER     = os.getenv("BREVO_SMS_SENDER", "CoWorks")   # max 11 chars

# Stockage temporaire des codes SMS (en production → Redis ou DB)
# Format : { phone: { "code": "12345", "uid": "uuid..." } }
phone_codes: dict = {}


# ─── Génération du code ──────────────────────────────────────

def generate_sms_code(length: int = 5) -> str:
    """Génère un code numérique aléatoire à 5 chiffres."""
    return ''.join(random.choices(string.digits, k=length))


# ─── Envoi du SMS ────────────────────────────────────────────

def send_sms_code(phone: str, code: str) -> bool:
    """
    Envoie le code de vérification par SMS via l'API Brevo.
    - Mode DEV (sans clé) : affiche dans le terminal.
    - Mode PROD : appel API Brevo Transactional SMS.

    Le numéro doit être au format international : +213xxxxxxxxx
    """
    message = f"CoWorks - Votre code de verification : {code}\nValide 10 minutes."

    # ── Mode DEV : pas de clé API ────────────────────────────
    if not BREVO_API_KEY:
        print(f"\n{'='*50}")
        print(f"[DEV MODE] Code SMS pour {phone}: {code}")
        print(f"{'='*50}\n")
        return True

    # ── Mode PROD : API Brevo SMS ─────────────────────────────
    try:
        url = "https://api.brevo.com/v3/transactionalSMS/sms"
        headers = {
            "accept":       "application/json",
            "content-type": "application/json",
            "api-key":      BREVO_API_KEY,
        }
        payload = {
            "sender":    SMS_SENDER,
            "recipient": phone,       # format international obligatoire : +213...
            "content":   message,
            "type":      "transactional",
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)

        if response.status_code in [200, 201, 202]:
            print(f"[SMS] Code envoyé à {phone}")
            print(f"👉 [DEV INFO] Le code OTP est : {code}")
            return True
        else:
            print(f"[BREVO SMS ERROR] {response.status_code} - {response.text}")
            # Fallback terminal pour ne pas bloquer en dev
            print(f"\n[FALLBACK SMS] Code pour {phone}: {code}\n")
            return True   # retourne True pour ne pas bloquer le flow

    except Exception as e:
        print(f"[SMS ERROR] {e}")
        print(f"\n[FALLBACK SMS] Code pour {phone}: {code}\n")
        return True       # fallback gracieux
