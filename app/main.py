from dotenv import load_dotenv
load_dotenv()  # ← doit être en premier, avant tout autre import

import os
from fastapi import FastAPI, Request
from fastapi_mcp import FastApiMCP
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from db.database import Base, engine, db_session
from api.router import api_router
import asyncio
from services.booking_service import update_expired_bookings

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

@app.middleware("http")
async def db_session_middleware(request: Request, call_next):
    """
    Libère la session DB après chaque requête HTTP.
    Évite l'épuisement du pool de connexions SQLAlchemy.
    """
    try:
        response = await call_next(request)
        return response
    finally:
        db_session.remove()  #libérer la connexion

async def booking_status_monitor():
    """Tâche d'arrière-plan qui met à jour les statuts de réservation toutes les 10 minutes."""
    while True:
        try:
            update_expired_bookings()
        except Exception as e:
            print(f"Error in booking_status_monitor: {e}")
        finally:
            db_session.remove() # S'assurer de libérer la connexion
        await asyncio.sleep(600) # Attendre 10 minutes (600 secondes)

@app.on_event("startup")
async def on_startup():
    Base.metadata.create_all(bind=engine)
    # Verify db connection
    db_session.execute(text('SELECT 1'))
    db_session.commit()
    # Lancer la tâche d'arrière-plan
    asyncio.create_task(booking_status_monitor())

@app.on_event("shutdown")
def on_shutdown():
    db_session.remove()

mcp = FastApiMCP(app, name="Coworking")
mcp.mount_http()

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(
        "main:app",
        host=os.getenv("APP_HOST"),
        port=int(os.getenv("APP_PORT")),
        reload=True
    )
