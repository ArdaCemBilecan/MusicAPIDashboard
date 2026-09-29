"""Last.fm JSON yanıtlarını düz kayıtlara (dict) çevirir."""


def _int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value):
    # Last.fm tek kayıt dönünce liste yerine dict verebiliyor.
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _artist_name(obj):
    artist = obj.get("artist")
    if isinstance(artist, dict):
        return artist.get("name")
    return artist


def geo_top_artists(data, country, fetched_at):
    items = _as_list(data.get("topartists", {}).get("artist"))
    return [
        {
            "fetched_at": fetched_at, "country": country, "rank": i,
            "artist_name": a.get("name"), "listeners": _int(a.get("listeners")),
            "mbid": a.get("mbid") or None, "url": a.get("url"),
        }
        for i, a in enumerate(items, 1)
    ]


def geo_top_tracks(data, country, fetched_at):
    items = _as_list(data.get("tracks", {}).get("track"))
    return [
        {
            "fetched_at": fetched_at, "country": country, "rank": i,
            "track_name": t.get("name"), "artist_name": _artist_name(t),
            "duration_sec": _int(t.get("duration")), "listeners": _int(t.get("listeners")),
            "mbid": t.get("mbid") or None, "url": t.get("url"),
        }
        for i, t in enumerate(items, 1)
    ]


def chart_top_artists(data, fetched_at):
    items = _as_list(data.get("artists", {}).get("artist"))
    return [
        {
            "fetched_at": fetched_at, "rank": i, "artist_name": a.get("name"),
            "playcount": _int(a.get("playcount")), "listeners": _int(a.get("listeners")),
            "mbid": a.get("mbid") or None, "url": a.get("url"),
        }
        for i, a in enumerate(items, 1)
    ]


def chart_top_tracks(data, fetched_at):
    items = _as_list(data.get("tracks", {}).get("track"))
    return [
        {
            "fetched_at": fetched_at, "rank": i, "track_name": t.get("name"),
            "artist_name": _artist_name(t), "duration_sec": _int(t.get("duration")),
            "playcount": _int(t.get("playcount")), "listeners": _int(t.get("listeners")),
            "mbid": t.get("mbid") or None, "url": t.get("url"),
        }
        for i, t in enumerate(items, 1)
    ]


def chart_top_tags(data, fetched_at):
    items = _as_list(data.get("tags", {}).get("tag"))
    return [
        {
            "fetched_at": fetched_at, "rank": i, "tag_name": (t.get("name") or "").lower(),
            "reach": _int(t.get("reach")), "taggings": _int(t.get("taggings")),
            "url": t.get("url"),
        }
        for i, t in enumerate(items, 1)
    ]


def artist_tags(data, artist_name, fetched_at, top_n=5):
    # artist_name, geo tablolarıyla JOIN yapabilmek için istekte kullanılan ad olarak saklanır.
    items = _as_list(data.get("toptags", {}).get("tag"))[:top_n]
    return [
        {
            "artist_name": artist_name, "tag_name": (t.get("name") or "").lower(),
            "tag_count": _int(t.get("count")), "updated_at": fetched_at,
        }
        for t in items if t.get("name")
    ]


def artist_country(artist_name, match, fetched_at):
    """MusicBrainz sonucunu kayda çevirir. match None ise 'bulunamadı' olarak saklanır."""
    match = match or {}
    return {
        "artist_name": artist_name, "country_code": match.get("country_code"),
        "mbid": match.get("mbid"), "mb_name": match.get("mb_name"), "updated_at": fetched_at,
    }
