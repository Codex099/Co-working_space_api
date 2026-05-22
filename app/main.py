from dotenv import load_dotenv
load_dotenv()  # ← doit être en premier, avant tout autre import

from fastapi import FastAPI, Request
from fastapi_mcp import FastApiMCP
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from db.database import Base, engine, db_session
from api.router import api_router
from core.exceptions import AppException, app_exception_handler

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(AppException, app_exception_handler)

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

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # Verify db connection
    db_session.execute(text('SELECT 1'))
    db_session.commit()

@app.on_event("shutdown")
def on_shutdown():
    db_session.remove()

mcp = FastApiMCP(app, name="Coworking")
mcp.mount_http()

if __name__ == '__main__':
    
    import uvicorn
    uvicorn.run("main:app", host="::", port=5000, reload=True)
