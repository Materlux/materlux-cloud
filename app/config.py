"""Configuração central via variáveis de ambiente. Nenhum segredo no código."""
import os
from functools import lru_cache


class Settings:
    # Banco (string única do Postgres gerenciado, ex.: Supabase/Neon)
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")

    # Segurança / sessão
    JWT_SECRET: str = os.getenv("JWT_SECRET", "troque-este-segredo-em-producao")
    JWT_ALG: str = "HS256"
    SESSION_HOURS: int = int(os.getenv("SESSION_HOURS", "12"))
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"

    # Agente
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # WhatsApp (agnóstico de provedor)
    WA_PROVIDER: str = os.getenv("WA_PROVIDER", "zapi")  # zapi | meta | console
    WA_VERIFY_TOKEN: str = os.getenv("WA_VERIFY_TOKEN", "materlux-verify")
    ZAPI_INSTANCE: str = os.getenv("ZAPI_INSTANCE", "")
    ZAPI_TOKEN: str = os.getenv("ZAPI_TOKEN", "")
    ZAPI_CLIENT_TOKEN: str = os.getenv("ZAPI_CLIENT_TOKEN", "")
    META_TOKEN: str = os.getenv("META_TOKEN", "")
    META_PHONE_ID: str = os.getenv("META_PHONE_ID", "")

    # Agenda / regras de negócio
    SLOT_MINUTES: int = int(os.getenv("SLOT_MINUTES", "30"))
    CLINIC_TZ: str = os.getenv("CLINIC_TZ", "America/Sao_Paulo")
    # Profissionais que a atendente virtual pode agendar na Fase 1
    BOOKABLE_PROFESSIONAL_IDS = [
        int(x) for x in os.getenv("BOOKABLE_PROFESSIONAL_IDS", "1,4").split(",")
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
