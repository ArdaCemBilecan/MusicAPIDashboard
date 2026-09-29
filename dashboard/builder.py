"""Serbest sorgu oluşturucu.

Kullanıcı; veri kaynağı, X ekseni, (isteğe bağlı) seri, ölçü ve filtreleri seçer.
Ölçü tek bir toplama (ör. Toplam · Dinleyici) ya da iki ölçünün oranı olabilir
(ör. Toplam · Dinleyici [Konum = Yurt dışı] ÷ Toplam · Dinleyici). Sonuç ham değer
ya da toplamın / X grubunun / serinin yüzdesi olarak gösterilebilir.

Yalnızca aşağıdaki beyaz listedeki tablo/kolonlar kullanılabilir; tüm değerler
SQL parametresi olarak geçer.
"""
from psycopg import sql

from .db import query
from .templates import ParamError, result

DATASETS = {
    "artist_foreign_share": {
        "label": "Sanatçı yurtdışı özeti", "table": "v_artist_foreign_share", "latest": None,
        "dims": {"artist_name": "Sanatçı", "home_country": "Sanatçının ülkesi",
                 "home_source": "Ülke kaynağı"},
        "metrics": {"home_listeners": "Yurt içi dinleyici", "foreign_listeners": "Yurtdışı dinleyici",
                    "total_listeners": "Toplam dinleyici", "foreign_countries": "Yurtdışı ülke sayısı",
                    "foreign_share_pct": "Yurtdışı payı (%)",
                    "foreign_to_home_pct": "Yurtdışı / yurt içi (%)"},
        "formats": {"foreign_share_pct": "percent", "foreign_to_home_pct": "percent"},
    },
    "artist_country_listeners": {
        "label": "Sanatçı × ülke dinleyicileri (yurt içi / dışı)", "table": "v_artist_country_listeners",
        "latest": None,
        "dims": {"country": "Dinlendiği ülke", "artist_name": "Sanatçı", "home_country": "Sanatçının ülkesi",
                 "location": "Konum (yurt içi / dışı)", "home_source": "Ülke kaynağı"},
        "metrics": {"listeners": "Dinleyici", "rank": "Sıra"},
    },
    "geo_artists": {
        "label": "Ülke Top sanatçıları", "table": "geo_top_artists", "latest": "country",
        "dims": {"country": "Ülke", "artist_name": "Sanatçı", "fetched_at": "Çekim zamanı"},
        "metrics": {"listeners": "Dinleyici", "rank": "Sıra"},
    },
    "geo_tracks": {
        "label": "Ülke Top şarkıları", "table": "geo_top_tracks", "latest": "country",
        "dims": {"country": "Ülke", "artist_name": "Sanatçı", "track_name": "Şarkı",
                 "fetched_at": "Çekim zamanı"},
        "metrics": {"listeners": "Dinleyici", "duration_sec": "Süre (sn)", "rank": "Sıra"},
        "formats": {"duration_sec": "duration"},
    },
    "country_genres": {
        "label": "Ülke × sanatçı × tür", "table": "v_country_artist_tags", "latest": "country",
        "dims": {"country": "Ülke", "tag_name": "Tür", "artist_name": "Sanatçı",
                 "fetched_at": "Çekim zamanı"},
        "metrics": {"listeners": "Dinleyici", "tag_count": "Etiket ağırlığı"},
    },
    "global_artists": {
        "label": "Global Top sanatçılar", "table": "chart_top_artists", "latest": "global",
        "dims": {"artist_name": "Sanatçı", "fetched_at": "Çekim zamanı"},
        "metrics": {"playcount": "Çalınma", "listeners": "Dinleyici", "rank": "Sıra"},
    },
    "global_tracks": {
        "label": "Global Top şarkılar", "table": "chart_top_tracks", "latest": "global",
        "dims": {"track_name": "Şarkı", "artist_name": "Sanatçı", "fetched_at": "Çekim zamanı"},
        "metrics": {"playcount": "Çalınma", "listeners": "Dinleyici",
                    "duration_sec": "Süre (sn)", "listening_hours": "Dinlenme süresi (saat)"},
        "formats": {"duration_sec": "duration", "listening_hours": "hours"},
    },
    "global_tags": {
        "label": "Global Top türler", "table": "chart_top_tags", "latest": "global",
        "dims": {"tag_name": "Tür", "fetched_at": "Çekim zamanı"},
        "metrics": {"reach": "Erişim", "taggings": "Etiketlenme"},
    },
}

# Kolon olmayan hesaplanmış ölçüler (sabit, güvenli ifadeler)
EXPRESSIONS = {
    "listening_hours": "(t.playcount::numeric * t.duration_sec / 3600.0)",
}

AGGS = {
    "sum": ("Toplam", "SUM({})"),
    "avg": ("Ortalama", "AVG({})"),
    "max": ("En yüksek", "MAX({})"),
    "min": ("En düşük", "MIN({})"),
    "count": ("Kayıt sayısı", "COUNT(*)"),
    "count_distinct": ("Farklı değer sayısı", "COUNT(DISTINCT {})"),
}

OPS = {
    "eq": ("=", "eşittir"), "neq": ("<>", "eşit değildir"), "in": ("IN", "şunlardan biri"),
    "contains": ("ILIKE", "içerir"), "gte": (">=", "büyük/eşit"), "lte": ("<=", "küçük/eşit"),
}

SORTS = {"value_desc": "Değer (azalan)", "value_asc": "Değer (artan)", "label": "Etiket (A→Z)"}

# Grafikte bir değere tıklayınca hangi dashboard filtresinin ayarlanacağı
X_TYPES = {"artist_name": "artist", "country": "country", "home_country": "country", "tag_name": "tag"}

VALUE_MODES = {
    "raw": "Ham değer",
    "pct_total": "Toplamın yüzdesi",
    "pct_x": "X grubu içindeki pay (%)",
    "pct_series": "Seri içindeki pay (%)",
}


def public_datasets():
    return {
        "datasets": {k: {"label": v["label"], "dims": v["dims"], "metrics": v["metrics"],
                         "snapshots": v["latest"] is not None}
                     for k, v in DATASETS.items()},
        "aggs": {k: v[0] for k, v in AGGS.items()},
        "ops": {k: v[1] for k, v in OPS.items()},
        "sorts": SORTS,
        "value_modes": VALUE_MODES,
    }


def _col(ds, name):
    if name in EXPRESSIONS and name in ds["metrics"]:
        return sql.SQL(EXPRESSIONS[name])
    if name in ds["dims"] or name in ds["metrics"]:
        return sql.SQL("t.") + sql.Identifier(name)
    raise ParamError(f"Geçersiz alan: {name}")


def _condition(ds, f, params):
    """Tek bir filtre koşulu -> SQL parçası (params listesine değer ekler) ya da None."""
    f = f or {}
    field, op, value = f.get("field"), f.get("op"), f.get("value")
    if not field or op not in OPS or value in (None, "", []):
        return None
    col = _col(ds, field)
    if isinstance(value, list):             # çoklu seçimli dashboard filtresinden gelen değerler
        values = [str(v) for v in value]
        if op == "neq":
            params.append(values)
            return sql.SQL("NOT ({}::text = ANY(%s))").format(col)
        if op == "contains":
            params.append([f"%{v}%" for v in values])
            return sql.SQL("{}::text ILIKE ANY(%s)").format(col)
        if op in ("eq", "in") or field not in ds["metrics"]:
            params.append(values)
            return sql.SQL("{}::text = ANY(%s)").format(col)
        value = values[0]
    if op == "in":
        params.append([v.strip() for v in str(value).split(",") if v.strip()])
        return sql.SQL("{}::text = ANY(%s)").format(col)
    if op == "contains":
        params.append(f"%{value}%")
        return sql.SQL("{}::text ILIKE %s").format(col)
    if field in ds["metrics"]:
        try:
            params.append(float(value))
        except ValueError:
            raise ParamError(f"'{ds['metrics'][field]}' için sayısal bir değer girin")
        return sql.SQL("{} " + OPS[op][0] + " %s").format(col)
    params.append(str(value))
    return sql.SQL("{}::text " + OPS[op][0] + " %s").format(col)


def _cond_label(ds, cond):
    if not cond or not cond.get("field") or cond.get("value") in (None, ""):
        return ""
    fields = {**ds["dims"], **ds["metrics"]}
    op = {"eq": "=", "neq": "≠", "in": "∈", "contains": "~", "gte": "≥", "lte": "≤"}.get(cond.get("op"), "")
    return f" [{fields.get(cond['field'], cond['field'])} {op} {cond['value']}]"


def _aggregate(ds, agg, metric, cond=None):
    """Tek toplama ifadesi -> (sql, params, etiket)."""
    if agg not in AGGS:
        raise ParamError(f"Geçersiz toplama türü: {agg}")
    fields = {**ds["dims"], **ds["metrics"]}
    if agg == "count":
        expr, label = sql.SQL("COUNT(*)"), "Kayıt sayısı"
    else:
        if not metric:
            raise ParamError("Bir ölçü alanı seçin")
        if agg == "count_distinct":
            if metric not in fields:
                raise ParamError(f"Geçersiz alan: {metric}")
        elif metric not in ds["metrics"]:
            raise ParamError(f"'{AGGS[agg][0]}' için sayısal bir alan seçin")
        expr = sql.SQL(AGGS[agg][1]).format(_col(ds, metric))
        label = f"{AGGS[agg][0]} · {fields[metric]}"
    params = []
    c = _condition(ds, cond, params)
    if c is not None:
        expr = expr + sql.SQL(" FILTER (WHERE {})").format(c)
    return expr, params, label + _cond_label(ds, cond)


def _measure(ds, spec):
    """Ölçü ifadesi -> (sql, params, etiket, biçim)."""
    if spec.get("measure") == "ratio":
        num, den = spec.get("num") or {}, spec.get("den") or {}
        n_sql, n_params, n_label = _aggregate(ds, num.get("agg") or "sum", num.get("metric"), num.get("cond"))
        d_sql, d_params, d_label = _aggregate(ds, den.get("agg") or "sum", den.get("metric"), den.get("cond"))
        expr = sql.SQL("(100.0 * {} / NULLIF({}, 0))").format(n_sql, d_sql)
        return expr, n_params + d_params, f"{n_label} ÷ {d_label} (%)", "percent"

    agg = spec.get("agg") or "sum"
    expr, params, label = _aggregate(ds, agg, spec.get("metric"))
    fmt = "number" if agg in ("count", "count_distinct") else ds.get("formats", {}).get(spec.get("metric"), "number")
    return expr, params, label, fmt


def _limit(spec):
    try:
        return max(1, min(500, int(spec.get("limit") or 20)))
    except (TypeError, ValueError):
        return 20


def run_custom(spec):
    spec = spec or {}
    ds = DATASETS.get(spec.get("dataset"))
    if not ds:
        raise ParamError("Bir veri kaynağı seçin")

    x = spec.get("x") or None
    series = spec.get("series") or None
    for dim in (x, series):
        if dim and dim not in ds["dims"]:
            raise ParamError(f"Geçersiz boyut: {dim}")
    if series and not x:
        raise ParamError("Seri kullanmak için önce X ekseni seçin")
    if series == x:
        series = None

    value_expr, value_params, value_label, fmt = _measure(ds, spec)
    mode = spec.get("value_mode") if spec.get("value_mode") in VALUE_MODES else "raw"
    if mode in ("pct_x", "pct_series") and not series:
        mode = "pct_total"
    if mode != "raw":
        fmt = "percent"
        value_label = f"{value_label} — {VALUE_MODES[mode]}"
    if (spec.get("value_label") or "").strip():
        value_label = spec["value_label"].strip()[:60]
    elif len(value_label) > 48:   # uzun otomatik etiketleri kısalt (ayrıntı alt başlıkta görünür)
        value_label = "Oran (%)" if spec.get("measure") == "ratio" else "Pay (%)" if mode != "raw" else value_label[:48]

    # WHERE
    where, where_params = [], []
    table = sql.Identifier(ds["table"])
    if spec.get("snapshot", "latest") == "latest" and ds["latest"]:
        if ds["latest"] == "country":
            where.append(sql.SQL(
                "(t.country, t.fetched_at) IN (SELECT country, MAX(fetched_at) FROM {} GROUP BY country)"
            ).format(table))
        else:
            where.append(sql.SQL("t.fetched_at = (SELECT MAX(fetched_at) FROM {})").format(table))
    for f in spec.get("filters") or []:
        c = _condition(ds, f, where_params)
        if c is not None:
            where.append(c)
    where_sql = sql.SQL(" WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL("")
    base_params = value_params + where_params

    limit = _limit(spec)
    sort = spec.get("sort") if spec.get("sort") in SORTS else "value_desc"
    x_label = ds["dims"].get(x) if x else None
    s_label = ds["dims"].get(series) if series else None

    # 1) Tek değer (KPI)
    if not x:
        q = sql.SQL("SELECT {} AS value FROM {} t").format(value_expr, table) + where_sql
        _, rows = query(q, base_params)
        value = rows[0][0]
        if mode != "raw" and value is not None:
            value = 100.0
        return result(["label", "value", "format"], [[value_label, value, fmt]])

    x_col = _col(ds, x)
    if x == "fetched_at":          # zaman ekseni her zaman kronolojik
        sort = "label"

    # 2) Tek seri
    if not series:
        final = {"raw": "value",
                 "pct_total": "100.0 * value / NULLIF(SUM(value) OVER (), 0)"}[mode]
        order = {"value_desc": "value DESC NULLS LAST", "value_asc": "value ASC NULLS LAST",
                 "label": "x ASC"}[sort]
        q = sql.SQL("""
            WITH base AS (SELECT {x} AS x, {v} AS value FROM {t} t {w} GROUP BY 1)
            SELECT x, {final} AS value FROM base ORDER BY {order} LIMIT %s
        """).format(x=x_col, v=value_expr, t=table, w=where_sql,
                    final=sql.SQL(final), order=sql.SQL(order))
        _, rows = query(q, base_params + [limit])
        res = result([x_label, value_label], rows, x=x_label, y=value_label, fmt=fmt,
                     y_label=value_label)
        res["encoding"]["x_type"] = X_TYPES.get(x)
        return res

    # 3) Çok seri: en büyük `limit` X değeri ve en büyük 8 seri
    s_col = _col(ds, series)
    final = {"raw": "value",
             "pct_total": "100.0 * value / NULLIF(SUM(value) OVER (), 0)",
             "pct_x": "100.0 * value / NULLIF(SUM(value) OVER (PARTITION BY x), 0)",
             "pct_series": "100.0 * value / NULLIF(SUM(value) OVER (PARTITION BY s), 0)"}[mode]
    # X sıralaması: toplam değere ya da seçilen bir serinin değerine göre
    sort_series = (spec.get("sort_series") or "").strip()
    order_params = []
    if sort == "label":
        x_order = sql.SQL("x ASC")
    else:
        direction = "DESC" if sort == "value_desc" else "ASC"
        if sort_series:
            x_order = sql.SQL("COALESCE(MAX(value) FILTER (WHERE s::text = %s), 0) " + direction)
            order_params.append(sort_series)
        else:
            x_order = sql.SQL("SUM(raw) " + direction + " NULLS LAST")

    q = sql.SQL("""
        WITH base AS (
            SELECT {x} AS x, {s} AS s, {v} AS value FROM {t} t {w} GROUP BY 1, 2
        ),
        shaped AS (SELECT x, s, value AS raw, {final} AS value FROM base),
        top_x AS (
            SELECT x, ROW_NUMBER() OVER (ORDER BY {x_order}, x) AS pos
            FROM shaped GROUP BY x ORDER BY pos LIMIT %s
        ),
        top_s AS (SELECT s FROM shaped GROUP BY s ORDER BY SUM(raw) DESC NULLS LAST LIMIT 8)
        SELECT sh.x, sh.s, sh.value FROM shaped sh
        JOIN top_x USING (x) JOIN top_s USING (s)
        ORDER BY top_x.pos, sh.s
    """).format(x=x_col, s=s_col, v=value_expr, t=table, w=where_sql,
                final=sql.SQL(final), x_order=x_order)
    _, rows = query(q, base_params + order_params + [limit])
    res = result([x_label, s_label, value_label], rows, x=x_label, series=s_label,
                 y=value_label, fmt=fmt, y_label=value_label)
    if mode == "pct_x":
        res["encoding"]["stacked"] = True   # her X'in payları %100'e tamamlanır
    res["encoding"]["x_type"] = X_TYPES.get(x)
    return res
