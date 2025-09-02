import os
from pydantic import BaseSettings

class Settings(BaseSettings):
    mongodb_uri: str

    class Config:
        env_prefix = ""
        env_file = ".env"

settings = Settings()
