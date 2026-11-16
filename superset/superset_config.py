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

# ---------------------------------------------------------------------------
# Themes: HCM-branded light (default) and dark. With both defined, Superset
# shows a light/dark/system switcher in the top bar and follows the user's
# device setting until they pick one. Replace whole dicts - Superset does not
# merge these with its built-in defaults.
_HCM_TOKENS = {
    "brandAppName": "HCM Dashboards",
    "brandLogoAlt": "HCM",
    "brandLogoUrl": "/static/assets/images/superset-logo-horiz.png",
    "brandLogoMargin": "18px 0",
    "brandLogoHref": "/",
    "brandLogoHeight": "24px",
    "brandSpinnerUrl": None,
    "brandSpinnerSvg": None,
    "colorPrimary": "#F47738",   # HCM orange (tabs, buttons, active states)
    "colorLink": "#0B4B66",      # HCM teal
    "colorError": "#D03B3B",
    "colorWarning": "#FAB219",
    "colorSuccess": "#0CA30C",
    "colorInfo": "#2A78D6",
    "fontUrls": [],
    "fontFamily": "Inter, Roboto, Helvetica, Arial, sans-serif",
    "fontFamilyCode": "'IBM Plex Mono', 'Courier New', monospace",
    "transitionTiming": 0.3,
    "brandIconMaxWidth": 37,
    "fontSizeXS": "8",
    "fontSizeXXL": "28",
    "fontWeightNormal": "400",
    "fontWeightLight": "300",
    "fontWeightStrong": "500",
    "fontWeightBold": "700",
    "colorEditorSelection": "#fff5cf",
}
THEME_DEFAULT = {"token": dict(_HCM_TOKENS), "algorithm": "default"}
THEME_DARK = {
    "token": {**_HCM_TOKENS, "colorLink": "#8CC7E3", "colorEditorSelection": "#5c4d1a"},
    "algorithm": "dark",
}

ROW_LIMIT = 50000
SQL_MAX_ROW = 200000
SUPERSET_WEBSERVER_TIMEOUT = 300
