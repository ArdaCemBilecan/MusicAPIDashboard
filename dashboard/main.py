"""Music Dashboard web uygulaması (FastAPI).

Çalıştırmak için proje klasöründe:
    uvicorn dashboard.main:app --reload
Sonra tarayıcıda: http://localhost:8000
"""
import logging
from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal, Optional

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import storage
from .builder import public_datasets, run_custom
from .db import connection, init_db, query
from .sqlrunner import run_sql, schema_info
from .variables import VAR_TYPES, resolve
from .settings import NOISE_TAGS, STATIC_DIR
from .templates import CATEGORIES, ParamError, public_templates, run_template

log = logging.getLogger("dashboard")


@asynccontextmanager
async def lifespan(app):
    init_db()
    storage.ensure_samples()
    yield


app = FastAPI(title="Music Dashboard", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Modeller
# --------------------------------------------------------------------------- #
class Source(BaseModel):
    type: Literal["template", "custom", "sql"]
    template: Optional[str] = None
    params: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] = Field(default_factory=dict)


class Widget(BaseModel):
    id: str
    x: int = 0
    y: int = 0
    w: int = 6
    h: int = 5
    title: str = ""
    chart: str = "bar"
    source: Source


class Variable(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,30}$")
    label: str = ""
    type: Literal["country", "artist", "tag"]
    multi: bool = False
    value: Any = None
    pick: bool = True        # grafikte tıklanan değerle güncellensin mi


class DashboardIn(BaseModel):
    name: Optional[str] = None
    widgets: Optional[list[Widget]] = None
    variables: Optional[list[Variable]] = None


class WidgetDataIn(BaseModel):
    source: Source
    vars: dict[str, Any] = Field(default_factory=dict)


class ArtistCountryIn(BaseModel):
    artist_name: str
    country_code: Optional[str] = None   # None = elle düzeltmeyi kaldır (otomatige dön)


def _jsonable(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _clean(res):
    res["rows"] = [[_jsonable(v) for v in row] for row in res["rows"]]
    return res


def _dump(widgets):
    return [w.model_dump() for w in widgets] if widgets is not None else None


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/meta")
def meta():
    _, countries = query("SELECT DISTINCT country FROM geo_top_artists ORDER BY 1")
    _, tags = query("""
        SELECT tag_name FROM artist_tags WHERE tag_name <> ALL(%s)
        GROUP BY tag_name ORDER BY COUNT(*) DESC LIMIT 80
    """, (NOISE_TAGS,))
    _, artists = query("""
        SELECT artist_name FROM (
            SELECT artist_name, MAX(listeners) AS l FROM geo_top_artists GROUP BY artist_name
            UNION ALL
            SELECT artist_name, MAX(listeners) FROM chart_top_artists GROUP BY artist_name
        ) a GROUP BY artist_name ORDER BY MAX(l) DESC NULLS LAST LIMIT 400
    """)
    _, last = query("SELECT MAX(fetched_at) FROM chart_top_artists")
    _, all_countries = query("SELECT code, name FROM countries ORDER BY name")
    return {
        "templates": public_templates(),
        "categories": CATEGORIES,
        "builder": public_datasets(),
        "options": {
            "countries": [r[0] for r in countries],
            "tags": [r[0] for r in tags],
            "artists": [r[0] for r in artists],
            "all_countries": [{"code": c, "name": n} for c, n in all_countries],
            "locations": ["Yurt içi", "Yurt dışı"],
            "home_sources": ["MusicBrainz", "Elle girildi", "Tahmini"],
        },
        "schema": schema_info(),
        "var_types": VAR_TYPES,
        "last_update": _jsonable(last[0][0]),
    }


@app.post("/api/widget-data")
def widget_data(body: WidgetDataIn):
    try:
        src = resolve(body.source.model_dump(), body.vars)
        if src["type"] == "template":
            res = run_template(src["template"], src["params"])
        elif src["type"] == "sql":
            res = run_sql(src["spec"])
        else:
            res = run_custom(src["spec"])
    except ParamError as exc:
        raise HTTPException(400, str(exc))
    except psycopg.Error as exc:
        log.exception("Sorgu hatası")
        raise HTTPException(500, f"Veritabanı hatası: {exc.__class__.__name__}")
    return _clean(res)


@app.get("/api/dashboards")
def list_dashboards():
    return storage.list_dashboards()


@app.post("/api/dashboards", status_code=201)
def create_dashboard(body: DashboardIn):
    name = (body.name or "").strip() or "Yeni dashboard"
    return storage.create_dashboard(name, _dump(body.widgets) or [], _dump(body.variables) or [])


@app.get("/api/dashboards/{dashboard_id}")
def get_dashboard(dashboard_id: int):
    d = storage.get_dashboard(dashboard_id)
    if not d:
        raise HTTPException(404, "Dashboard bulunamadı")
    return d


@app.put("/api/dashboards/{dashboard_id}")
def update_dashboard(dashboard_id: int, body: DashboardIn):
    name = body.name.strip() if body.name and body.name.strip() else None
    d = storage.update_dashboard(dashboard_id, name, _dump(body.widgets), _dump(body.variables))
    if not d:
        raise HTTPException(404, "Dashboard bulunamadı")
    return d


@app.delete("/api/dashboards/{dashboard_id}", status_code=204)
def delete_dashboard(dashboard_id: int):
    if not storage.delete_dashboard(dashboard_id):
        raise HTTPException(404, "Dashboard bulunamadı")


# --------------------------------------------------------------------------- #
# Sanatçı ülkeleri (yurtdışı payı hesabı için ana ülke)
# --------------------------------------------------------------------------- #
@app.get("/api/artist-countries")
def artist_countries(q: str = "", home: str = "", source: str = "", limit: int = 100):
    limit = max(1, min(500, limit))
    cols, rows = query("""
        SELECT h.artist_name, h.home_code, COALESCE(hc.name, h.home_code) AS home_country,
               h.home_source, h.auto_code, COALESCE(ac.name, h.auto_code) AS auto_country,
               o.country_code AS override_code, tot.total_listeners, tot.countries
        FROM v_artist_home h
        LEFT JOIN countries hc ON hc.code = h.home_code
        LEFT JOIN countries ac ON ac.code = h.auto_code
        LEFT JOIN artist_country_override o ON o.artist_name = h.artist_name
        LEFT JOIN (SELECT artist_name, SUM(listeners) AS total_listeners, COUNT(*) AS countries
                   FROM v_geo_artists_latest GROUP BY artist_name) tot ON tot.artist_name = h.artist_name
        WHERE (%(q)s = '' OR h.artist_name ILIKE %(like)s)
          AND (%(home)s = '' OR h.home_code = %(home)s)
          AND (%(source)s = '' OR h.home_source = %(source)s)
        ORDER BY tot.total_listeners DESC NULLS LAST, h.artist_name
        LIMIT %(limit)s
    """, {"q": q.strip(), "like": f"%{q.strip()}%", "home": home, "source": source, "limit": limit})
    _, counts = query("SELECT home_source, COUNT(*) FROM v_artist_home GROUP BY 1")
    return {"rows": [dict(zip(cols, [_jsonable(v) for v in r])) for r in rows],
            "counts": {k: v for k, v in counts}}


@app.put("/api/artist-countries")
def set_artist_country(body: ArtistCountryIn):
    name = body.artist_name.strip()
    if not name:
        raise HTTPException(400, "Sanatçı adı boş olamaz")
    with connection() as conn:
        if body.country_code:
            code = body.country_code.strip().upper()
            if not conn.execute("SELECT 1 FROM countries WHERE code = %s", (code,)).fetchone():
                raise HTTPException(400, f"Bilinmeyen ülke kodu: {code}")
            conn.execute("""
                INSERT INTO artist_country_override (artist_name, country_code, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (artist_name) DO UPDATE SET country_code = EXCLUDED.country_code, updated_at = now()
            """, (name, code))
        else:
            conn.execute("DELETE FROM artist_country_override WHERE artist_name = %s", (name,))
        conn.commit()
        row = conn.execute("""
            SELECT h.home_code, COALESCE(c.name, h.home_code), h.home_source
            FROM v_artist_home h LEFT JOIN countries c ON c.code = h.home_code
            WHERE h.artist_name = %s
        """, (name,)).fetchone()
    return {"artist_name": name, "home_code": row[0] if row else None,
            "home_country": row[1] if row else None, "home_source": row[2] if row else None}


# --------------------------------------------------------------------------- #
# Arayüz
# --------------------------------------------------------------------------- #
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
