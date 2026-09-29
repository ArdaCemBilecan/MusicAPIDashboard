"""Hazır widget şablonları.

Her şablon: parametre şeması (arayüzdeki form buradan oluşur), izin verilen
grafik tipleri ve parametreleri alıp sonuç dönen bir fonksiyon.
Tüm kullanıcı değerleri SQL'e parametre olarak (%s) geçer.
"""
from .db import query
from .settings import NOISE_TAGS

TEMPLATES = {}

CATEGORIES = {
    "overview": "Genel bakış",
    "country": "Ülkeler",
    "genre": "Türler",
    "global": "Global listeler",
    "foreign": "Yurtdışı başarısı",
    "time": "Süre ve trend",
}


class ParamError(ValueError):
    pass


def template(id, title, description, category, params, charts, size=(6, 5)):
    def deco(fn):
        TEMPLATES[id] = {
            "id": id, "title": title, "description": description, "category": category,
            "params": params, "charts": charts, "default_chart": charts[0],
            "size": {"w": size[0], "h": size[1]}, "fn": fn,
        }
        return fn
    return deco


def public_templates():
    return [{k: v for k, v in t.items() if k != "fn"} for t in TEMPLATES.values()]


def run_template(template_id, params):
    t = TEMPLATES.get(template_id)
    if not t:
        raise ParamError(f"Bilinmeyen şablon: {template_id}")
    clean = {}
    for spec in t["params"]:
        clean[spec["name"]] = _coerce(spec, (params or {}).get(spec["name"], spec.get("default")))
    return t["fn"](**clean)


def _coerce(spec, value):
    kind = spec["type"]
    if kind == "int":
        try:
            value = int(value)
        except (TypeError, ValueError):
            value = spec["default"]
        return max(spec.get("min", 1), min(spec.get("max", 100), value))
    if kind == "bool":
        return value in (True, "true", "1", 1, "on")
    if kind == "select":
        allowed = [o["value"] for o in spec["options"]]
        return value if value in allowed else spec["default"]
    value = (str(value).strip() if value is not None else "") or spec.get("default") or ""
    if spec.get("required") and not value:
        raise ParamError(f"'{spec['label']}' alanı boş olamaz")
    return value


X_TYPE_BY_LABEL = {"Sanatçı": "artist", "Ülke": "country", "Tür": "tag"}


def result(columns, rows, x=None, y=None, series=None, fmt="number", y_label=None):
    return {
        "columns": columns, "rows": rows,
        "encoding": {"x": x, "y": y, "series": series, "format": fmt, "y_label": y_label,
                     # tıklanınca hangi dashboard filtresi ayarlanır (sanatçı / ülke / tür)
                     "x_type": X_TYPE_BY_LABEL.get(x)},
    }


# Parametre şeması kısayolları
COUNTRY = {"name": "country", "label": "Ülke", "type": "country", "default": "Turkey", "required": True}
GENRES_ONLY = {"name": "genres_only", "label": "Yalnızca müzik türleri (\"seen live\" gibi etiketleri gizle)",
               "type": "bool", "default": True}


def TOP_N(default=10, maximum=50):
    return {"name": "top_n", "label": "Kaç kayıt (Top N)", "type": "int",
            "default": default, "min": 1, "max": maximum}


LATEST_GEO = """
latest AS (
    SELECT country, MAX(fetched_at) AS fetched_at FROM geo_top_artists GROUP BY country
)"""


def _noise(genres_only):
    return NOISE_TAGS if genres_only else []


# --------------------------------------------------------------------------- #
# Genel bakış
# --------------------------------------------------------------------------- #
@template("overview", "Genel bakış", "Ülke, sanatçı, şarkı sayıları ve son güncelleme zamanı.",
          "overview", [], ["kpi"], size=(12, 2))
def overview():
    _, rows = query(f"""
        WITH {LATEST_GEO}
        SELECT
          (SELECT COUNT(*) FROM latest),
          (SELECT COUNT(DISTINCT g.artist_name) FROM geo_top_artists g
             JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at),
          (SELECT COUNT(DISTINCT (t.track_name, t.artist_name)) FROM geo_top_tracks t
             JOIN latest l ON l.country = t.country AND l.fetched_at = t.fetched_at),
          (SELECT COUNT(DISTINCT tag_name) FROM artist_tags),
          (SELECT COUNT(DISTINCT fetched_at) FROM chart_top_artists),
          (SELECT MAX(fetched_at) FROM chart_top_artists)
    """)
    c, a, t, g, snaps, last = rows[0]
    items = [
        ["Ülke", c, "number"], ["Farklı sanatçı", a, "number"], ["Farklı şarkı", t, "number"],
        ["Tür etiketi", g, "number"], ["Snapshot", snaps, "number"],
        ["Son güncelleme", last.isoformat() if last else None, "datetime"],
    ]
    return result(["label", "value", "format"], items)


# --------------------------------------------------------------------------- #
# Ülkeler
# --------------------------------------------------------------------------- #
@template("country_top_artists", "Ülkenin en çok dinlenen sanatçıları",
          "Seçilen ülkede son snapshot'a göre dinleyici sayısı en yüksek sanatçılar.",
          "country", [COUNTRY, TOP_N()], ["hbar", "bar", "treemap", "table"])
def country_top_artists(country, top_n):
    cols, rows = query(f"""
        WITH {LATEST_GEO}
        SELECT g.artist_name AS "Sanatçı", g.listeners AS "Dinleyici"
        FROM geo_top_artists g JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        WHERE g.country = %s ORDER BY g.rank LIMIT %s
    """, (country, top_n))
    return result(cols, rows, x="Sanatçı", y="Dinleyici", y_label="Dinleyici")


@template("country_top_tracks", "Ülkenin en çok dinlenen şarkıları",
          "Seçilen ülkede son snapshot'a göre en çok dinlenen şarkılar.",
          "country", [COUNTRY, TOP_N()], ["hbar", "table"])
def country_top_tracks(country, top_n):
    cols, rows = query(f"""
        WITH {LATEST_GEO}
        SELECT g.track_name || ' — ' || g.artist_name AS "Şarkı", g.listeners AS "Dinleyici"
        FROM geo_top_tracks g JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        WHERE g.country = %s ORDER BY g.rank LIMIT %s
    """, (country, top_n))
    return result(cols, rows, x="Şarkı", y="Dinleyici", y_label="Dinleyici")


@template("artist_reach", "En yaygın sanatçılar",
          "Kaç farklı ülkenin Top listesine girdiğine göre sanatçılar.",
          "country", [TOP_N(15)], ["hbar", "bar", "table"])
def artist_reach(top_n):
    cols, rows = query(f"""
        WITH {LATEST_GEO}
        SELECT g.artist_name AS "Sanatçı", COUNT(DISTINCT g.country) AS "Ülke sayısı"
        FROM geo_top_artists g JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        GROUP BY g.artist_name ORDER BY 2 DESC, SUM(g.listeners) DESC LIMIT %s
    """, (top_n,))
    return result(cols, rows, x="Sanatçı", y="Ülke sayısı", y_label="Ülke sayısı")


# --------------------------------------------------------------------------- #
# Türler
# --------------------------------------------------------------------------- #
@template("country_genres", "Ülkenin tür dağılımı",
          "Seçilen ülkenin Top sanatçılarında en sık görülen türler.",
          "genre",
          [COUNTRY, TOP_N(10, 30),
           {"name": "metric", "label": "Ölçü", "type": "select", "default": "artists",
            "options": [{"value": "artists", "label": "Sanatçı sayısı"},
                        {"value": "listeners", "label": "Toplam dinleyici"}]},
           GENRES_ONLY],
          ["hbar", "pie", "treemap", "bar", "table"])
def country_genres(country, top_n, metric, genres_only):
    value = "COUNT(DISTINCT g.artist_name)" if metric == "artists" else "SUM(g.listeners)"
    label = "Sanatçı sayısı" if metric == "artists" else "Dinleyici"
    cols, rows = query(f"""
        WITH {LATEST_GEO}
        SELECT t.tag_name AS "Tür", {value} AS "{label}"
        FROM geo_top_artists g
        JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        JOIN artist_tags t ON t.artist_name = g.artist_name
        WHERE g.country = %s AND t.tag_name <> ALL(%s)
        GROUP BY t.tag_name ORDER BY 2 DESC LIMIT %s
    """, (country, _noise(genres_only), top_n))
    return result(cols, rows, x="Tür", y=label, y_label=label)


@template("genre_heatmap", "Ülke × tür ısı haritası",
          "Her ülkenin Top sanatçılarının yüzde kaçının o türde olduğu.",
          "genre", [TOP_N(12, 25), GENRES_ONLY], ["heatmap", "table"], size=(12, 7))
def genre_heatmap(top_n, genres_only):
    cols, rows = query(f"""
        WITH {LATEST_GEO},
        base AS (
            SELECT g.country, g.artist_name FROM geo_top_artists g
            JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        ),
        totals AS (SELECT country, COUNT(DISTINCT artist_name) AS n FROM base GROUP BY country),
        tagged AS (
            SELECT b.country, t.tag_name, COUNT(DISTINCT b.artist_name) AS k
            FROM base b JOIN artist_tags t ON t.artist_name = b.artist_name
            WHERE t.tag_name <> ALL(%s)
            GROUP BY b.country, t.tag_name
        ),
        top_tags AS (
            SELECT tag_name FROM tagged GROUP BY tag_name ORDER BY SUM(k) DESC LIMIT %s
        )
        SELECT tg.tag_name AS "Tür", tg.country AS "Ülke",
               ROUND(100.0 * tg.k / tot.n, 1) AS "Sanatçı payı (%%)"
        FROM tagged tg
        JOIN top_tags USING (tag_name)
        JOIN totals tot USING (country)
        ORDER BY tg.country, tg.tag_name
    """, (_noise(genres_only), top_n))
    return result(cols, rows, x="Tür", series="Ülke", y="Sanatçı payı (%)", fmt="percent",
                  y_label="Sanatçı payı (%)")


@template("genre_by_country", "Bir türün ülkelere göre payı",
          "Seçilen tür, ülkelerin Top sanatçılarının yüzde kaçını oluşturuyor?",
          "genre",
          [{"name": "tag", "label": "Tür", "type": "tag", "default": "pop", "required": True}],
          ["hbar", "bar", "table"])
def genre_by_country(tag):
    cols, rows = query(f"""
        WITH {LATEST_GEO},
        base AS (
            SELECT g.country, g.artist_name FROM geo_top_artists g
            JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        )
        SELECT b.country AS "Ülke",
               ROUND(100.0 * COUNT(DISTINCT b.artist_name) FILTER (WHERE t.tag_name = %s)
                     / COUNT(DISTINCT b.artist_name), 1) AS "Sanatçı payı (%%)"
        FROM base b LEFT JOIN artist_tags t ON t.artist_name = b.artist_name
        GROUP BY b.country ORDER BY 2 DESC
    """, (tag.lower(),))
    return result(cols, rows, x="Ülke", y="Sanatçı payı (%)", fmt="percent",
                  y_label="Sanatçı payı (%)")


@template("global_top_tags", "Global en popüler türler",
          "Last.fm genelinde en çok kullanılan etiketler.",
          "genre",
          [TOP_N(15),
           {"name": "metric", "label": "Ölçü", "type": "select", "default": "reach",
            "options": [{"value": "reach", "label": "Erişim (kişi)"},
                        {"value": "taggings", "label": "Etiketlenme sayısı"}]}],
          ["hbar", "treemap", "pie", "table"])
def global_top_tags(top_n, metric):
    label = "Erişim" if metric == "reach" else "Etiketlenme"
    cols, rows = query(f"""
        SELECT tag_name AS "Tür", {metric} AS "{label}" FROM chart_top_tags
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM chart_top_tags)
        ORDER BY {metric} DESC LIMIT %s
    """, (top_n,))
    return result(cols, rows, x="Tür", y=label, y_label=label)


# --------------------------------------------------------------------------- #
# Global listeler
# --------------------------------------------------------------------------- #
METRIC_PLAY = {"name": "metric", "label": "Ölçü", "type": "select", "default": "playcount",
               "options": [{"value": "playcount", "label": "Çalınma sayısı"},
                           {"value": "listeners", "label": "Dinleyici sayısı"}]}


@template("global_top_artists", "Global en çok dinlenen sanatçılar",
          "Last.fm global listesi, son snapshot.",
          "global", [TOP_N(10, 100), METRIC_PLAY], ["hbar", "bar", "treemap", "table"])
def global_top_artists(top_n, metric):
    label = "Çalınma" if metric == "playcount" else "Dinleyici"
    cols, rows = query(f"""
        SELECT artist_name AS "Sanatçı", {metric} AS "{label}" FROM chart_top_artists
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM chart_top_artists)
        ORDER BY {metric} DESC LIMIT %s
    """, (top_n,))
    return result(cols, rows, x="Sanatçı", y=label, y_label=label)


@template("global_top_tracks", "Global en çok dinlenen şarkılar",
          "Last.fm global listesi, son snapshot.",
          "global", [TOP_N(10, 100), METRIC_PLAY], ["hbar", "table"])
def global_top_tracks(top_n, metric):
    label = "Çalınma" if metric == "playcount" else "Dinleyici"
    cols, rows = query(f"""
        SELECT track_name || ' — ' || artist_name AS "Şarkı", {metric} AS "{label}"
        FROM chart_top_tracks
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM chart_top_tracks)
        ORDER BY {metric} DESC LIMIT %s
    """, (top_n,))
    return result(cols, rows, x="Şarkı", y=label, y_label=label)


# --------------------------------------------------------------------------- #
# Süre ve trend
# --------------------------------------------------------------------------- #
@template("listening_time", "Toplam dinlenme süresi (tahmini)",
          "Global Top şarkılar için çalınma sayısı × şarkı süresi, saat cinsinden.",
          "time", [TOP_N(10, 100)], ["hbar", "table"])
def listening_time(top_n):
    cols, rows = query("""
        SELECT track_name || ' — ' || artist_name AS "Şarkı",
               ROUND(playcount::numeric * duration_sec / 3600, 0) AS "Saat"
        FROM chart_top_tracks
        WHERE fetched_at = (SELECT MAX(fetched_at) FROM chart_top_tracks) AND duration_sec > 0
        ORDER BY 2 DESC LIMIT %s
    """, (top_n,))
    return result(cols, rows, x="Şarkı", y="Saat", fmt="hours", y_label="Dinlenme süresi (saat)")


@template("country_avg_duration", "Ülkelere göre ortalama şarkı süresi",
          "Her ülkenin Top şarkılarının ortalama uzunluğu.",
          "time", [], ["hbar", "bar", "table"])
def country_avg_duration():
    cols, rows = query(f"""
        WITH {LATEST_GEO}
        SELECT g.country AS "Ülke", ROUND(AVG(g.duration_sec)) AS "Ortalama süre"
        FROM geo_top_tracks g JOIN latest l ON l.country = g.country AND l.fetched_at = g.fetched_at
        WHERE g.duration_sec > 0
        GROUP BY g.country ORDER BY 2 DESC
    """)
    return result(cols, rows, x="Ülke", y="Ortalama süre", fmt="duration",
                  y_label="Ortalama süre (dk:sn)")


@template("artist_trend", "Sanatçı trendi",
          "Bir sanatçının snapshot'lar boyunca dinleyici veya çalınma değişimi.",
          "time",
          [{"name": "artist", "label": "Sanatçı", "type": "artist", "default": "", "required": True},
           {"name": "scope", "label": "Kapsam", "type": "country_or_global", "default": "__global__"}],
          ["line", "table"])
def artist_trend(artist, scope):
    if scope == "__global__":
        cols, rows = query("""
            SELECT fetched_at AS "Zaman", playcount AS "Çalınma"
            FROM chart_top_artists WHERE lower(artist_name) = lower(%s) ORDER BY fetched_at
        """, (artist,))
        return result(cols, rows, x="Zaman", y="Çalınma", fmt="number", y_label="Çalınma")
    cols, rows = query("""
        SELECT fetched_at AS "Zaman", listeners AS "Dinleyici"
        FROM geo_top_artists WHERE lower(artist_name) = lower(%s) AND country = %s
        ORDER BY fetched_at
    """, (artist, scope))
    return result(cols, rows, x="Zaman", y="Dinleyici", y_label="Dinleyici")


# --------------------------------------------------------------------------- #
# Yurtdışı başarısı (sanatçının ana ülkesine göre)
# --------------------------------------------------------------------------- #
HOME = {"name": "country", "label": "Sanatçıların ülkesi", "type": "country", "default": "Turkey",
        "required": True}


@template("foreign_summary", "Yurtdışı özeti",
          "Seçilen ülkenin sanatçılarının yurtdışında ne kadar dinlendiğine dair özet.",
          "foreign", [HOME], ["kpi"], size=(12, 2))
def foreign_summary(country):
    _, rows = query("""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE foreign_listeners > 0),
               ROUND(100.0 * SUM(foreign_listeners) / NULLIF(SUM(total_listeners), 0), 1),
               SUM(foreign_listeners),
               (SELECT l.country FROM v_artist_country_listeners l
                 WHERE l.home_country = %s AND NOT l.is_home
                 GROUP BY l.country ORDER BY SUM(l.listeners) DESC LIMIT 1),
               ROUND(100.0 * COUNT(*) FILTER (WHERE home_source <> 'Tahmini') / NULLIF(COUNT(*), 0))
        FROM v_artist_foreign_share
        WHERE home_country = %s AND home_listeners IS NOT NULL
    """, (country, country))
    n, abroad, share, foreign, market, verified = rows[0]
    items = [
        ["Sanatçı", n, "number"], ["Yurtdışında dinlenen", abroad, "number"],
        ["Genel yurtdışı payı", share, "percent"], ["Yurtdışı dinleyici", foreign, "number"],
        ["En büyük yabancı pazar", market, "text"], ["Ülkesi doğrulanan", verified, "percent"],
    ]
    return result(["label", "value", "format"], items)


@template("foreign_share", "Ülke sanatçılarının yurtdışı payı",
          "Seçilen ülkenin sanatçılarının dinleyicilerinin yüzde kaçı yurtdışından geliyor? "
          "Yurtdışı payı = yurtdışı ÷ (yurt içi + yurtdışı).",
          "foreign",
          [HOME, TOP_N(15, 50),
           {"name": "sort", "label": "Sıralama", "type": "select", "default": "share",
            "options": [{"value": "share", "label": "Yurtdışı payı"},
                        {"value": "foreign", "label": "Yurtdışı dinleyici"},
                        {"value": "total", "label": "Toplam dinleyici"}]},
           {"name": "min_total", "label": "En az toplam dinleyici", "type": "int",
            "default": 0, "min": 0, "max": 100000000}],
          ["hbar", "hstack", "table"], size=(12, 6))
def foreign_share(country, top_n, sort, min_total):
    order = {"share": "s.foreign_share_pct", "foreign": "s.foreign_listeners",
             "total": "s.total_listeners"}[sort]
    cols, rows = query(f"""
        SELECT s.artist_name       AS "Sanatçı",
               s.home_listeners    AS "Yurt içi",
               s.foreign_listeners AS "Yurt dışı",
               s.total_listeners   AS "Toplam",
               s.foreign_share_pct AS "Yurtdışı payı (%%)",
               s.foreign_to_home_pct AS "Yurtdışı / yurt içi (%%)",
               s.foreign_countries AS "Yurtdışı ülke sayısı",
               s.home_source       AS "Ülke kaynağı"
        FROM v_artist_foreign_share s
        WHERE s.home_country = %s AND s.home_listeners IS NOT NULL AND s.total_listeners >= %s
        ORDER BY {order} DESC NULLS LAST, s.total_listeners DESC
        LIMIT %s
    """, (country, min_total, top_n))
    y, fmt = {"share": ("Yurtdışı payı (%)", "percent"), "foreign": ("Yurt dışı", "number"),
              "total": ("Toplam", "number")}[sort]
    res = result(cols, rows, x="Sanatçı", y=y, fmt=fmt, y_label=y)
    res["encoding"]["stack_cols"] = ["Yurt içi", "Yurt dışı"]
    return res


@template("foreign_markets", "Ülke sanatçılarının yurtdışı pazarları",
          "Seçilen ülkenin sanatçıları hangi ülkelerde ne kadar dinleniyor?",
          "foreign", [HOME, TOP_N(10, 30)], ["hbar", "pie", "treemap", "table"])
def foreign_markets(country, top_n):
    cols, rows = query("""
        SELECT l.country AS "Ülke", SUM(l.listeners) AS "Dinleyici",
               COUNT(DISTINCT l.artist_name) AS "Sanatçı sayısı"
        FROM v_artist_country_listeners l
        WHERE l.home_country = %s AND NOT l.is_home
        GROUP BY l.country ORDER BY 2 DESC LIMIT %s
    """, (country, top_n))
    return result(cols, rows, x="Ülke", y="Dinleyici", y_label="Dinleyici")


@template("artist_countries", "Sanatçının ülkelere göre dinleyicisi",
          "Bir sanatçının her ülkedeki dinleyici sayısı; yurt içi ve yurt dışı ayrı renkte.",
          "foreign",
          [{"name": "artist", "label": "Sanatçı", "type": "artist", "default": "Tarkan", "required": True}],
          ["hbar", "pie", "table"])
def artist_countries(artist):
    cols, rows = query("""
        SELECT country AS "Ülke", location AS "Konum", listeners AS "Dinleyici", rank AS "Sıra",
               home_country AS "Sanatçının ülkesi"
        FROM v_artist_country_listeners
        WHERE lower(artist_name) = lower(%s)
        ORDER BY listeners DESC NULLS LAST
    """, (artist,))
    res = result(cols, rows, x="Ülke", y="Dinleyici", series="Konum", y_label="Dinleyici")
    res["encoding"]["stacked"] = True   # seriler yan yana değil, aynı çubukta renklenir
    return res


@template("artist_summary", "Sanatçı özeti",
          "Seçilen sanatçının ana ülkesi, yurt içi / yurtdışı dinleyicisi ve yurtdışı payı.",
          "foreign",
          [{"name": "artist", "label": "Sanatçı", "type": "artist", "default": "Tarkan", "required": True}],
          ["kpi", "table"], size=(12, 2))
def artist_summary(artist):
    _, rows = query("""
        SELECT s.home_country, s.home_source, s.home_listeners, s.foreign_listeners,
               s.foreign_share_pct, s.foreign_countries,
               (SELECT l.country FROM v_artist_country_listeners l
                 WHERE lower(l.artist_name) = lower(%s) AND NOT l.is_home
                 ORDER BY l.listeners DESC NULLS LAST LIMIT 1)
        FROM v_artist_foreign_share s
        WHERE lower(s.artist_name) = lower(%s)
    """, (artist, artist))
    if not rows:
        return result(["label", "value", "format"], [])
    home, source, home_l, foreign_l, share, n_foreign, market = rows[0]
    items = [
        [f"Ana ülke ({source})", home, "text"], ["Yurt içi dinleyici", home_l, "number"],
        ["Yurtdışı dinleyici", foreign_l, "number"], ["Yurtdışı payı", share, "percent"],
        ["Dinlendiği yabancı ülke", n_foreign, "number"], ["En büyük yabancı pazar", market, "text"],
    ]
    return result(["label", "value", "format"], items)
