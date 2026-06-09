import os
import random
import string
import requests

# ── EMAIL CONFIG — valeurs lues depuis .env ───────────────────
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL  = os.getenv("SMTP_USER")


# Stockage temporaire des codes (en production → Redis ou DB)
verification_codes: dict = {}   # { email: code }
pending_local_users: dict = {}  # { email: user_data }


def generate_code(length: int = 6) -> str:
    """Génère un code numérique aléatoire à 6 chiffres."""
    return ''.join(random.choices(string.digits, k=length))


def send_verification_email(to_email: str, code: str, username: str = "utilisateur", action: str = "signup") -> bool:
    """
    Envoie un email de vérification via l'API Brevo.
    Retourne True si succès ou Fallback, False sinon.
    """
    # Mode DEV : pas de clé API → affiche dans le terminal
    if not BREVO_API_KEY:
        print(f"\n{'='*50}")
        print(f"[DEV MODE] Code de vérification ({action}) pour {to_email}: {code}")
        print(f"{'='*50}\n")
        return True

    try:
        texts = {
            "signup": {
                "subject": "Vérification de votre compte CoWorking Space",
                "message": "Bienvenue ! Pour finaliser la création de votre compte et sécuriser votre accès, veuillez utiliser le code de confirmation suivant :"
            },
            "reset_password": {
                "subject": "Réinitialisation de votre mot de passe",
                "message": "Vous avez demandé la réinitialisation de votre mot de passe. Veuillez utiliser le code de vérification suivant pour procéder :"
            },
            "update_email": {
                "subject": "Confirmation de votre nouvelle adresse email",
                "message": "Vous avez demandé à changer votre adresse email. Veuillez utiliser le code de confirmation suivant pour valider cette nouvelle adresse :"
            }
        }
        
        email_data = texts.get(action, texts["signup"])
        subject = email_data["subject"]
        message = email_data["message"]

        html_content = f"""
        <!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Votre code de vérification</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f0e8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">

  <span style="display:none;font-size:1px;color:#f5f0e8;max-height:0;max-width:0;opacity:0;overflow:hidden;">
    Voici votre code de vérification pour CoWorking Space : {code}
  </span>

  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f5f0e8;padding:40px 20px;">
    <tr>
      <td align="center">

        <table width="100%" cellpadding="0" cellspacing="0" border="0"
               style="background-color:#FFFFFF;border-radius:16px;overflow:hidden;
                      box-shadow:0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);max-width:500px;">

          <!-- Header -->
          <tr>
            <td style="padding:40px 40px 20px 40px;text-align:center;">
              <div style="display:inline-block;background-color:#e8f0e0;padding:12px;border-radius:12px;margin-bottom:16px;">
                <span style="font-size:24px;">🏢</span>
              </div>
              <h1 style="margin:0;font-size:24px;font-weight:700;color:#111827;letter-spacing:-0.5px;">
                CoWorking Space
              </h1>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:10px 40px 30px 40px;">
              <p style="margin:0 0 16px;font-size:16px;color:#374151;line-height:1.6;">
                Bonjour <strong>{username}</strong>, 👋
              </p>
              <p style="margin:0 0 24px;font-size:16px;color:#4B5563;line-height:1.6;">
                {message}
              </p>

              <!-- Code block -->
              <div style="background-color:#e8f0e0;border:1px solid #c8dbb8;border-radius:12px;padding:24px;text-align:center;margin-bottom:24px;">
                <p style="margin:0 0 8px;font-size:12px;font-weight:600;color:#5c8a3c;text-transform:uppercase;letter-spacing:1px;">
                  Code de vérification
                </p>
                <div style="font-family:'Courier New',Courier,monospace;font-size:36px;font-weight:700;color:#2d5016;letter-spacing:8px;">
                  {code}
                </div>
              </div>

              <p style="margin:0 0 16px;font-size:14px;color:#6B7280;line-height:1.5;">
                ⏱ Ce code est valide pendant <strong>15 minutes</strong>.
              </p>
              
              <hr style="border:none;border-top:1px solid #E5E7EB;margin:32px 0;">
              
              <p style="margin:0 0 8px;font-size:14px;color:#9CA3AF;line-height:1.5;">
                Si vous n'avez pas demandé ce code, vous pouvez simplement ignorer cet email.
              </p>
              <p style="margin:0;font-size:14px;color:#9CA3AF;line-height:1.5;">
                À très vite,<br>L'équipe CoWorking Space
              </p>
            </td>
          </tr>

        </table>

        <!-- Footer -->
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:500px;margin-top:24px;">
          <tr>
            <td align="center" style="padding:0 20px;">
              <p style="margin:0;font-size:12px;color:#9CA3AF;line-height:1.5;">
                © 2026 CoWorking Space. Tous droits réservés.
              </p>
            </td>
          </tr>
        </table>

      </td>
    </tr>
  </table>

</body>
</html>"""

        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": BREVO_API_KEY
        }
        payload = {
            "sender": {"name": "CoWorking Space", "email": SENDER_EMAIL},
            "to": [{"email": to_email, "name": username}],
            "subject": subject,
            "htmlContent": html_content
        }

        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code in [200, 201, 202]:
            return True
        else:
            print(f"[BREVO ERROR] {response.status_code} - {response.text}")
            # Fallback logs pour ne pas bloquer l'utilisateur si l'API échoue
            print(f"\n[FALLBACK] Code pour {to_email}: {code}\n")
            return True

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        print(f"\n[FALLBACK] Code pour {to_email}: {code}\n")
        return True
