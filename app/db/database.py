from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from sqlalchemy.pool import NullPool
from core.config import settings

# ============================================================
#  DATABASE ENGINE
#  → SQLite  (dev)  : StaticPool  — connexion unique partagée,
#                     évite l'épuisement du QueuePool par défaut
#  → PostgreSQL (prod): NullPool  — crée/détruit chaque connexion
#                       immédiatement, idéal avec un pooler externe
#                       (PgBouncer) ou pour éviter les fuites de sessions
# ============================================================

if settings.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 15},
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,            # Pas de pool côté app — délégué au DB ou à PgBouncer
        pool_pre_ping=True,            # Vérifie si la connexion est encore active avant de l'utiliser
    )

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()

class DummyDB:
    def __init__(self, session):
        self.session = session
        self.Model = Base

db = DummyDB(db_session)

def get_db():
    try:
        yield db_session
    finally:
        db_session.remove()  # ✅ Libère la connexion dans le pool après chaque requête
