# config/dependencies.py
from src.config import settings

DATABASE_URL = settings.database_write_url
DATABASE_WRITE_URL = settings.database_write_url
DATABASE_READ_URL = settings.database_read_url

SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = settings.access_token_expire_minutes

STORAGE_TYPE = settings.storage_type
STORAGE_PATH = settings.storage_path