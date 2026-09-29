"""SQL widget'ı: kullanıcının yazdığı SELECT sorgusunu güvenli şekilde çalıştırır.

Güvenlik katmanları:
  1. Yalnızca SELECT / WITH ile başlayan tek bir sorgu kabul edilir
     (sorgu parametreli çalıştırıldığı için PostgreSQL birden fazla komutu reddeder).
  2. Sunucu dosyası okuma, ayar değiştirme gibi tehlikeli fonksiyonlar engellenir.
  3. Sorgu READ ONLY bir işlemde, yalnızca SELECT yetkisi olan bir rolle çalışır.
  4. Zaman aşımı (5 sn) ve satır sınırı (1000) uygulanır.
"""
import re

import psycopg
from psycopg import sql

from . import db
from .templates import ParamError, result

MAX_ROWS = 1000
TIMEOUT_MS = 5000

_FORBIDDEN = re.compile(
    r"\b(set_config|current_setting|pg_read_file|pg_read_binary_file|pg_ls_\w+|pg_stat_file|"
    r"lo_\w+|dblink\w*|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|"
    r"pg_promote|pg_switch_wal|pg_file_\w+|pg_logdir_ls|query_to_xml\w*|table_to_xml\w*|"
    r"cursor_to_xml\w*|database_to_xml\w*|schema_to_xml\w*|pg_advisory\w*|pg_sleep\w*)\s*\(",
    re.IGNORECASE,
)
_LEADING_COMMENTS = re.compile(r"^\s*(--[^\n]*\n|/\*.*?\*/)*\s*", re.DOTALL)

_VAR = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

NUMERIC_OIDS = {20, 21, 23, 700, 701, 790, 1700}
DATETIME_OIDS = {1082, 1114, 1184}


def _clean(text):
    text = (text or "").strip()
    while text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def run_sql(spec):
    spec = spec or {}
    text = _clean(spec.get("sql"))
    if not text:
        raise ParamError("Bir SQL sorgusu yazın")
    body = _LEADING_COMMENTS.sub("", text, count=1)
    if not re.match(r"(select|with)\b", body, re.IGNORECASE):
        raise ParamError("Yalnızca SELECT veya WITH ile başlayan sorgular çalıştırılabilir")
    bad = _FORBIDDEN.search(text)
    if bad:
        raise ParamError(f"Bu fonksiyona izin verilmiyor: {bad.group(1)}")

    # Kullanıcının yazdığı '%' işaretleri parametre sanılmasın; {{değişken}} -> güvenli parametre
    values = spec.get("vars") or {}
    var_params = []

    def _bind(m):
        name = m.group(1)
        if name not in values:
            raise ParamError(f"Bu dashboard'da '{name}' adında bir filtre yok")
        v = values[name]
        if isinstance(v, list):
            var_params.append([str(x) for x in v if x not in (None, "")])
            return "%s::text[]"
        var_params.append(None if v in (None, "") else str(v))
        return "%s::text"

    body_sql = _VAR.sub(_bind, text.replace("%", "%%"))
    wrapped = sql.SQL("SELECT * FROM ({}\n) AS q LIMIT %s").format(sql.SQL(body_sql))
    try:
        with db.connection() as conn:
            with conn.transaction(), conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
                if db.reader_role:
                    cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(db.reader_role)))
                cur.execute(wrapped, (*var_params, MAX_ROWS + 1))
                desc = cur.description
                rows = [list(r) for r in cur.fetchall()]
    except psycopg.errors.QueryCanceled:
        raise ParamError(f"Sorgu {TIMEOUT_MS // 1000} saniyede tamamlanamadı; daha dar bir sorgu deneyin")
    except psycopg.errors.InsufficientPrivilege:
        raise ParamError("Bu tabloya ya da işleme erişim izni yok (SQL widget'ı yalnızca okuma yapabilir)")
    except psycopg.Error as exc:
        msg = (exc.diag.message_primary or str(exc)).strip()
        hint = exc.diag.message_hint
        raise ParamError(f"SQL hatası: {msg}" + (f" — {hint}" if hint else ""))

    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    columns = [d.name for d in desc]
    types = ["number" if d.type_code in NUMERIC_OIDS else "datetime" if d.type_code in DATETIME_OIDS
             else "text" for d in desc]

    numeric = [c for c, t in zip(columns, types) if t == "number"]
    others = [c for c, t in zip(columns, types) if t != "number"]
    x = spec.get("x") if spec.get("x") in columns else (others[0] if others else columns[0])
    ys = [y for y in (spec.get("ys") or []) if y in numeric] or numeric[:1]
    series = spec.get("series") if spec.get("series") in columns and spec.get("series") != x else None
    fmt = spec.get("format") if spec.get("format") in ("number", "percent", "hours", "duration") else "number"

    res = result(columns, rows, x=x, y=ys[0] if ys else None, series=series, fmt=fmt,
                 y_label=ys[0] if ys else None)
    if len(ys) > 1 and not series:
        res["encoding"]["y_cols"] = ys
    res["meta"] = {"types": types, "truncated": truncated, "row_count": len(rows)}
    lx = (x or "").lower()
    res["encoding"]["x_type"] = ("artist" if "artist" in lx or "sanat" in lx else
                                 "country" if "country" in lx or "ulke" in lx or "ülke" in lx else
                                 "tag" if "tag" in lx or "tur" == lx or "tür" in lx else None)
    return res


def schema_info():
    """SQL editöründe gösterilecek tablo ve kolon listesi."""
    _, rows = db.query("""
        SELECT c.table_name, t.table_type, c.column_name, c.data_type
        FROM information_schema.columns c
        JOIN information_schema.tables t
          ON t.table_schema = c.table_schema AND t.table_name = c.table_name
        WHERE c.table_schema = 'public' AND c.table_name NOT IN ('dashboards', 'app_meta')
        ORDER BY (t.table_type = 'VIEW') DESC, c.table_name, c.ordinal_position
    """)
    tables = {}
    for name, kind, col, dtype in rows:
        t = tables.setdefault(name, {"name": name, "kind": "view" if kind == "VIEW" else "table", "columns": []})
        t["columns"].append({"name": col, "type": dtype})
    return list(tables.values())
