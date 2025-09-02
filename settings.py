from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    mongodb_uri: str
    jwt_secret: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env", 
        env_prefix="",   
        extra="ignore",   
    )

settings = Settings()