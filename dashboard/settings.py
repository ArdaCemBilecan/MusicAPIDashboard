"""Dashboard ayarları (.env dosyasından okunur)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

PG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "music_dashboard"),
    "user": os.getenv("POSTGRES_USER", "music"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}

STATIC_DIR = Path(__file__).resolve().parent / "static"
SCHEMA_FILE = ROOT / "sql" / "schema.sql"

# Tür analizlerinde gürültü sayılan (müzik türü olmayan) etiketler
NOISE_TAGS = [
    "seen live", "favorites", "favourites", "favorite", "favourite", "my favorites",
    "female vocalists", "male vocalists", "female vocalist", "male vocalist",
    "awesome", "beautiful", "love", "amazing", "all", "spotify", "cool", "best",
    "under 2000 listeners", "albums i own", "vocalists", "singer-songwriter-ish",
]
