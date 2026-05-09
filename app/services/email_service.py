import smtplib
import os
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============================================================
#  EMAIL CONFIG (variables d'environnement)
#  → Utilise Gmail SMTP par défaut
#  → Configure SMTP_USER et SMTP_PASSWORD dans ton .env
#  → Pour Gmail : activer "App Password" dans les paramètres Google
# ============================================================
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))
SMTP_USER     = os.getenv("SMTP_USER", "")       # ton email Gmail
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")   # app password Gmail
FRONTEND_URL  = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Stockage temporaire des codes (en production → Redis ou DB)
verification_codes: dict = {}   # { email: code }
pending_local_users: dict = {}  # { email: user_data }


def generate_code(length: int = 6) -> str:
    """Génère un code numérique aléatoire à 6 chiffres."""
    return ''.join(random.choices(string.digits, k=length))


def send_verification_email(to_email: str, code: str, username: str = "utilisateur") -> bool:
    """
    Envoie un email de vérification avec le code.
    Retourne True si succès, False sinon.
    En mode développement (pas de SMTP configuré) → affiche le code en console.
    """
    # Mode DEV : pas de SMTP configuré → affiche dans le terminal
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"\n{'='*50}")
        print(f"[DEV MODE] Code de vérification pour {to_email}: {code}")
        print(f"{'='*50}\n")
        return True

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Vérification de votre compte Co Working Space"
        msg["From"]    = SMTP_USER
        msg["To"]      = to_email



        html = f"""
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
                Bienvenue ! Pour finaliser la création de votre compte et sécuriser votre accès, veuillez utiliser le code de confirmation suivant :
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
        msg.attach(MIMEText(html, "html"))

        import socket
        try:
            # Force la résolution en IPv4 pour éviter l'erreur "Network is unreachable" sur Render (lié à l'IPv6)
            host_ipv4 = socket.gethostbyname(SMTP_HOST)
        except Exception:
            host_ipv4 = SMTP_HOST

        with smtplib.SMTP(host_ipv4, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to_email, msg.as_string())
        return True

    except Exception as e:
        print(f"[EMAIL ERROR] {e}")
        # FALLBACK : En cas d'erreur SMTP sur le serveur (ex: Render bloque le port), on affiche le code dans les logs
        print(f"\n{'='*50}")
        print(f"[FALLBACK MODE] Code de vérification pour {to_email}: {code}")
        print(f"{'='*50}\n")
        # On retourne False pour indiquer l'erreur, mais le code est au moins dans les logs
        # Si vous voulez que l'inscription ne bloque pas du tout, changez en 'return True'
        return False
