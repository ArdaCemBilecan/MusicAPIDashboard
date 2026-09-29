"""PostgreSQL bağlantısı ve şema kurulumu."""
import psycopg

from config import PG, ROOT


def connect() -> psycopg.Connection:
    return psycopg.connect(**PG)


def init_schema(conn: psycopg.Connection) -> None:
    sql = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    conn.execute(sql)
    conn.commit()
