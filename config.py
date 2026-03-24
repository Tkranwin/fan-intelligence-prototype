import os


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "")
    CLAUDE_MODEL = "claude-sonnet-4-20250514"
    CACHE_TIMEOUT = 3600  # 1 hour default cache for generated briefings
