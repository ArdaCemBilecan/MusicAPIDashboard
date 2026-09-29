"""PostgreSQL erişimi."""
import logging
from contextlib import contextmanager

import psycopg

from .settings import PG, SCHEMA_FILE

log = logging.getLogger("dashboard.db")

READER_ROLE = "dashboard_reader"
# SQL widget'ı bu rolle çalışır; rol kurulamazsa None kalır (yine de salt okunur işlemde çalışır)
reader_role = None

DASHBOARD_DDL = """
CREATE TABLE IF NOT EXISTS dashboards (
    id          SERIAL PRIMARY KEY,
    name        TEXT        NOT NULL,
    widgets     JSONB       NOT NULL DEFAULT '[]'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE dashboards ADD COLUMN IF NOT EXISTS variables JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Uygulama bayrakları (ör. hangi örnek dashboard'lar oluşturuldu)
CREATE TABLE IF NOT EXISTS app_meta (
    key         TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ülke x sanatçı x tür: serbest sorgu oluşturucu için
CREATE OR REPLACE VIEW v_country_artist_tags AS
SELECT g.fetched_at, g.country, g.rank, g.artist_name, g.listeners, t.tag_name, t.tag_count
FROM geo_top_artists g
JOIN artist_tags t ON t.artist_name = g.artist_name;
"""

READER_DDL = f"""
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER_ROLE}') THEN
        CREATE ROLE {READER_ROLE} NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO {READER_ROLE};
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {READER_ROLE};
REVOKE SELECT ON dashboards, app_meta FROM {READER_ROLE};
"""


@contextmanager
def connection():
    with psycopg.connect(**PG) as conn:
        yield conn


def init_db() -> None:
    """Veri tablolarını (yoksa), dashboard tablolarını ve salt okunur rolü oluşturur."""
    global reader_role
    with connection() as conn:
        conn.execute(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.execute(DASHBOARD_DDL)
        conn.commit()
        try:
            conn.execute(READER_DDL)
            conn.commit()
            # Bu kullanıcı rolü gerçekten üstlenebiliyor mu?
            with conn.transaction():
                conn.execute(f"SET LOCAL ROLE {READER_ROLE}")
            reader_role = READER_ROLE
        except psycopg.Error as exc:
            conn.rollback()
            reader_role = None
            log.warning("Salt okunur rol kurulamadı (%s). SQL widget'ı yine salt okunur işlemde çalışacak.",
                        exc.__class__.__name__)


def query(sql, params=None):
    """(kolonlar, satırlar) döner."""
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return cols, [list(r) for r in cur.fetchall()]
