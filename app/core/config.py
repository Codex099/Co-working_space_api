import os

class Settings:
    PROJECT_NAME: str = "Coworking API"
    DB_PATH: str = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'instance', 'coworking.db'))
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"
    #DATABASE_URL: str ="postgresql://postgres:18062005@localhost:8888/coworking"

settings = Settings()
