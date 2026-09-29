"""Dashboard kayıtları (PostgreSQL, JSONB)."""
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .db import connection

COLS = "id, name, widgets, variables, created_at, updated_at"


def list_dashboards():
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""SELECT id, name, jsonb_array_length(widgets) AS widget_count, updated_at
                       FROM dashboards ORDER BY updated_at DESC""")
        return cur.fetchall()


def get_dashboard(dashboard_id):
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {COLS} FROM dashboards WHERE id = %s", (dashboard_id,))
        return cur.fetchone()


def create_dashboard(name, widgets, variables=None):
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"INSERT INTO dashboards (name, widgets, variables) VALUES (%s, %s, %s) RETURNING {COLS}",
                    (name, Jsonb(widgets), Jsonb(variables or [])))
        return cur.fetchone()


def update_dashboard(dashboard_id, name=None, widgets=None, variables=None):
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"""
            UPDATE dashboards
            SET name = COALESCE(%s, name),
                widgets = COALESCE(%s, widgets),
                variables = COALESCE(%s, variables),
                updated_at = now()
            WHERE id = %s RETURNING {COLS}
        """, (name, Jsonb(widgets) if widgets is not None else None,
              Jsonb(variables) if variables is not None else None, dashboard_id))
        return cur.fetchone()


def delete_dashboard(dashboard_id):
    with connection() as conn:
        return conn.execute("DELETE FROM dashboards WHERE id = %s", (dashboard_id,)).rowcount > 0


def count_dashboards():
    with connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM dashboards").fetchone()[0]


def ensure_samples():
    """Örnek dashboard'ları bir kez oluşturur (kullanıcı silerse tekrar gelmez)."""
    with connection() as conn:
        done = {r[0] for r in conn.execute("SELECT key FROM app_meta").fetchall()}
        has_any = conn.execute("SELECT COUNT(*) FROM dashboards").fetchone()[0] > 0
    samples = [("sample_overview_v1", "Örnek dashboard", SAMPLE, []),
               ("sample_foreign_v1", "Yurtdışı başarısı — Türkiye", SAMPLE_FOREIGN, []),
               ("sample_foreign_v2", "Yurtdışı başarısı (filtreli)", SAMPLE_FOREIGN_DYNAMIC, SAMPLE_FOREIGN_VARS)]
    fresh = not done and not has_any
    _add_artist_summary(done)
    for key, name, widgets, variables in samples:
        if key in done:
            continue
        # İlk sürümden gelen kurulumda genel örnek zaten var: yenisini ekleme, sadece işaretle.
        # Sıfırdan kurulumda statik yurtdışı örneğine gerek yok, filtreli sürüm yeterli.
        skip = (key == "sample_overview_v1" and has_any) or (key == "sample_foreign_v1" and fresh)
        if not skip:
            create_dashboard(name, widgets, variables)
        with connection() as conn:
            conn.execute("INSERT INTO app_meta (key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))
            conn.commit()


# İlk açılışta oluşturulan örnek dashboard
SAMPLE = [
    {"id": "w1", "x": 0, "y": 0, "w": 12, "h": 2, "title": "Genel bakış", "chart": "kpi",
     "source": {"type": "template", "template": "overview", "params": {}}},
    {"id": "w2", "x": 0, "y": 2, "w": 6, "h": 5, "title": "Türkiye'nin tür dağılımı", "chart": "hbar",
     "source": {"type": "template", "template": "country_genres",
                "params": {"country": "Turkey", "top_n": 10, "metric": "artists", "genres_only": True}}},
    {"id": "w3", "x": 6, "y": 2, "w": 6, "h": 5, "title": "Türkiye'nin Top sanatçıları", "chart": "hbar",
     "source": {"type": "template", "template": "country_top_artists",
                "params": {"country": "Turkey", "top_n": 10}}},
    {"id": "w4", "x": 0, "y": 7, "w": 12, "h": 7, "title": "Ülke × tür ısı haritası", "chart": "heatmap",
     "source": {"type": "template", "template": "genre_heatmap",
                "params": {"top_n": 12, "genres_only": True}}},
    {"id": "w5", "x": 0, "y": 14, "w": 6, "h": 5, "title": "En yaygın sanatçılar", "chart": "hbar",
     "source": {"type": "template", "template": "artist_reach", "params": {"top_n": 10}}},
    {"id": "w6", "x": 6, "y": 14, "w": 6, "h": 5, "title": "Toplam dinlenme süresi (tahmini)",
     "chart": "hbar", "source": {"type": "template", "template": "listening_time", "params": {"top_n": 10}}},
]


SAMPLE_FOREIGN = [
    {"id": "f1", "x": 0, "y": 0, "w": 12, "h": 2, "title": "Türk sanatçıların yurtdışı özeti", "chart": "kpi",
     "source": {"type": "template", "template": "foreign_summary", "params": {"country": "Turkey"}}},
    {"id": "f2", "x": 0, "y": 2, "w": 7, "h": 7, "title": "Yurt içi ve yurt dışı dinleyiciler",
     "chart": "hstack",
     "source": {"type": "template", "template": "foreign_share",
                "params": {"country": "Turkey", "top_n": 15, "sort": "total", "min_total": 0}}},
    {"id": "f3", "x": 7, "y": 2, "w": 5, "h": 7, "title": "Yurtdışı payı en yüksek sanatçılar", "chart": "hbar",
     "source": {"type": "template", "template": "foreign_share",
                "params": {"country": "Turkey", "top_n": 15, "sort": "share", "min_total": 1000}}},
    {"id": "f4", "x": 0, "y": 9, "w": 6, "h": 5, "title": "Türk sanatçıların yurtdışı pazarları",
     "chart": "hbar",
     "source": {"type": "template", "template": "foreign_markets", "params": {"country": "Turkey", "top_n": 10}}},
    {"id": "f5", "x": 6, "y": 9, "w": 6, "h": 5, "title": "Tarkan: ülkelere göre dinleyici", "chart": "hbar",
     "source": {"type": "template", "template": "artist_countries", "params": {"artist": "Tarkan"}}},
    {"id": "f6", "x": 0, "y": 14, "w": 12, "h": 6,
     "title": "Özel sorgu örneği: yurt içi / yurt dışı payı (%)", "chart": "hstack",
     "source": {"type": "custom", "spec": {
         "dataset": "artist_country_listeners", "x": "artist_name", "series": "location",
         "measure": "simple", "agg": "sum", "metric": "listeners", "value_mode": "pct_x",
         "filters": [{"field": "home_country", "op": "eq", "value": "Turkey"}],
         "snapshot": "latest", "sort": "value_desc", "sort_series": "Yurt dışı", "limit": 12}}},
]


# Filtreli (dinamik) yurtdışı dashboard'u: ülke ve sanatçı üstteki filtrelerden seçilir
V = lambda name: {"$var": name}
SAMPLE_FOREIGN_VARS = [
    {"id": "country", "label": "Sanatçıların ülkesi", "type": "country", "multi": False, "value": "Turkey",
     "pick": False},
    {"id": "artist", "label": "Sanatçı", "type": "artist", "multi": False, "value": "Tarkan", "pick": True},
]
SAMPLE_FOREIGN_DYNAMIC = [
    {"id": "d1", "x": 0, "y": 0, "w": 12, "h": 2, "title": "{{country}} sanatçılarının yurtdışı özeti", "chart": "kpi",
     "source": {"type": "template", "template": "foreign_summary", "params": {"country": V("country")}}},
    {"id": "d0", "x": 0, "y": 2, "w": 12, "h": 2, "title": "{{artist}} özeti", "chart": "kpi",
     "source": {"type": "template", "template": "artist_summary", "params": {"artist": V("artist")}}},
    {"id": "d2", "x": 0, "y": 4, "w": 7, "h": 7, "title": "{{country}}: yurt içi ve yurt dışı dinleyiciler",
     "chart": "hstack",
     "source": {"type": "template", "template": "foreign_share",
                "params": {"country": V("country"), "top_n": 15, "sort": "total", "min_total": 0}}},
    {"id": "d3", "x": 7, "y": 4, "w": 5, "h": 7, "title": "Yurtdışı payı en yüksek sanatçılar", "chart": "hbar",
     "source": {"type": "template", "template": "foreign_share",
                "params": {"country": V("country"), "top_n": 15, "sort": "share", "min_total": 0}}},
    {"id": "d4", "x": 0, "y": 11, "w": 6, "h": 5, "title": "{{country}} sanatçılarının yurtdışı pazarları",
     "chart": "hbar",
     "source": {"type": "template", "template": "foreign_markets", "params": {"country": V("country"), "top_n": 10}}},
    {"id": "d5", "x": 6, "y": 11, "w": 6, "h": 5, "title": "{{artist}}: ülkelere göre dinleyici", "chart": "hbar",
     "source": {"type": "template", "template": "artist_countries", "params": {"artist": V("artist")}}},
]


def _add_artist_summary(done):
    """Önceki sürümde oluşturulmuş filtreli örneğe 'Sanatçı özeti' kartını bir kez ekler."""
    key = "sample_foreign_v2_artist_summary"
    if key in done or "sample_foreign_v2" not in done:
        return
    with connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT id, widgets, variables FROM dashboards WHERE name = %s",
                    ("Yurtdışı başarısı (filtreli)",))
        row = cur.fetchone()
        if row and any(v.get("id") == "artist" for v in row["variables"]) \
                and not any(w.get("id") == "d0" for w in row["widgets"]):
            widgets = row["widgets"]
            for w in widgets:           # altındaki widget'ları 2 satır aşağı kaydır
                if w.get("y", 0) >= 2:
                    w["y"] = w.get("y", 0) + 2
            widgets.insert(1, next(w for w in SAMPLE_FOREIGN_DYNAMIC if w["id"] == "d0"))
            cur.execute("UPDATE dashboards SET widgets = %s, updated_at = now() WHERE id = %s",
                        (Jsonb(widgets), row["id"]))
        cur.execute("INSERT INTO app_meta (key) VALUES (%s) ON CONFLICT DO NOTHING", (key,))
        conn.commit()
