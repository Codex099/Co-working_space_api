import firebase_admin
from firebase_admin import credentials
import os

# Initialisation de Firebase Admin
# Assurez-vous que serviceAccountKey.json est à la racine du dossier env/
cred_path = os.path.join(os.path.dirname(__file__), "..", "..", "co-working-space-2b868-firebase-adminsdk-fbsvc-9a086d521a.json")
cred = credentials.Certificate(cred_path)
firebase_admin.initialize_app(cred)
