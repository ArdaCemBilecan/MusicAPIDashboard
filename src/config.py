"""Proje ayarları. Gizli bilgiler .env dosyasından okunur."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# Last.fm
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY")
LASTFM_BASE_URL = os.getenv("LASTFM_BASE_URL", "https://ws.audioscrobbler.com/2.0/")

# Kafka
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
CONSUMER_GROUP = "music-db-writer"

# PostgreSQL
PG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "dbname": os.getenv("POSTGRES_DB", "music_dashboard"),
    "user": os.getenv("POSTGRES_USER", "music"),
    "password": os.getenv("POSTGRES_PASSWORD", ""),
}

# Veri çekme ayarları
# Ülke adları ISO 3166-1 İngilizce adlarıyla yazılmalı (Last.fm böyle bekliyor).
COUNTRIES = [
    "Turkey", "United States", "United Kingdom", "Germany", "France",
    "Spain", "Italy", "Netherlands", "Sweden", "Poland",
    "Russian Federation", "Brazil", "Mexico", "Argentina", "Canada",
    "Japan", "Australia",
]
GEO_ARTIST_LIMIT = 200  # ülke başına kaç sanatçı (yurtdışı payı için geniş tutulur)
GEO_TRACK_LIMIT = 50    # ülke başına kaç şarkı
GEO_PAGE_SIZE = 100     # Last.fm'den sayfa başına istenen kayıt
CHART_LIMIT = 100       # global listelerde kaç kayıt
TAGS_PER_ARTIST = 5     # sanatçı başına saklanacak tür etiketi
TAG_CACHE_DAYS = 7      # etiketleri kaç günde bir yenileyelim

# MusicBrainz (sanatçının ana ülkesi)
MUSICBRAINZ_URL = "https://musicbrainz.org/ws/2/"
# MusicBrainz, User-Agent'ta bir iletişim bilgisi ister: .env'de MUSICBRAINZ_CONTACT=e-posta ya da site
MUSICBRAINZ_CONTACT = os.getenv("MUSICBRAINZ_CONTACT", "local development")
MB_MIN_INTERVAL = 1.1   # MusicBrainz saniyede en fazla 1 istek kabul ediyor
MB_MAX_PER_RUN = 500    # bir çalıştırmada en fazla kaç sanatçı sorgulansın
MB_CACHE_DAYS = 90      # ülke bilgisini kaç günde bir yenileyelim

DATA_DIR = ROOT / "data"
TAG_CACHE_FILE = DATA_DIR / "artist_tag_cache.json"
COUNTRY_CACHE_FILE = DATA_DIR / "artist_country_cache.json"

# Kafka topic'leri
TOPICS = {
    "geo_top_artists": "lastfm.geo.top_artists",
    "geo_top_tracks": "lastfm.geo.top_tracks",
    "chart_top_artists": "lastfm.chart.top_artists",
    "chart_top_tracks": "lastfm.chart.top_tracks",
    "chart_top_tags": "lastfm.chart.top_tags",
    "artist_tags": "lastfm.artist.tags",
    "artist_country": "musicbrainz.artist.country",
}
