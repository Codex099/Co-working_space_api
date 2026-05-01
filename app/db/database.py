from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from core.config import settings

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    # La ligne suivante est requise uniquement pour SQLite.
    engine = create_engine(settings.DATABASE_URL, connect_args={'check_same_thread': False})

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
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
        pass
