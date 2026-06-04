import os

class Settings:
    PROJECT_NAME: str = "Coworking API"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

settings = Settings()
