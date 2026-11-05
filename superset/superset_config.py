import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = "postgresql+psycopg2://hcm:hcm@postgres:5432/superset"

# Local build: no CSP / CSRF friction for the API-driven build script
TALISMAN_ENABLED = False
WTF_CSRF_ENABLED = False

FEATURE_FLAGS = {
    "DASHBOARD_CROSS_FILTERS": True,
    "DASHBOARD_NATIVE_FILTERS": True,
    "ENABLE_TEMPLATE_PROCESSING": True,
    "DRILL_TO_DETAIL": True,
}

# Free OpenStreetMap / CARTO tiles for deck.gl maps (no Mapbox key)
DECKGL_BASE_MAP = [
    ["tile://https://basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png", "CARTO Light"],
    ["tile://https://tile.openstreetmap.org/{z}/{x}/{y}.png", "OpenStreetMap"],
    ["tile://https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png", "CARTO Dark"],
]

CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 60,  # near-real-time
    "CACHE_KEY_PREFIX": "hcm_",
    "CACHE_REDIS_URL": "redis://redis:6379/0",
}
DATA_CACHE_CONFIG = CACHE_CONFIG

ROW_LIMIT = 50000
SQL_MAX_ROW = 200000
SUPERSET_WEBSERVER_TIMEOUT = 300
