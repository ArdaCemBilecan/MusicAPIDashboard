"""MusicBrainz istemcisi: sanatçının ana ülkesini bulur.

Kurallar: saniyede en fazla 1 istek ve anlamlı bir User-Agent
(https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).
"""
import logging
import re
import time

import requests

from config import MB_MIN_INTERVAL, MUSICBRAINZ_CONTACT, MUSICBRAINZ_URL

log = logging.getLogger(__name__)

_session = requests.Session()
_session.headers.update({
    "User-Agent": f"MusicDashboard/0.1 ( {MUSICBRAINZ_CONTACT} )",
    "Accept": "application/json",
})
_last_call = 0.0
_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


class MBNetworkError(Exception):
    """Bağlantı / sunucu hatası: sonra tekrar denenmeli."""


def _get(path, params, retries=3):
    global _last_call
    for attempt in range(retries + 1):
        wait = MB_MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
        try:
            resp = _session.get(MUSICBRAINZ_URL + path, params={**params, "fmt": "json"}, timeout=(5, 20))
        except requests.RequestException as exc:
            err = MBNetworkError(type(exc).__name__)
        else:
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 500, 502, 503, 504):
                err = MBNetworkError(f"HTTP {resp.status_code}")
            else:
                resp.raise_for_status()
                return resp.json()
        if attempt == retries:
            raise err
        time.sleep(min(2 ** (attempt + 1), 20))


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").casefold()).strip()


def _country_of(artist):
    code = artist.get("country")
    if code:
        return code.upper()
    codes = (artist.get("area") or {}).get("iso-3166-1-codes") or []
    return codes[0].upper() if codes else None


def _match(artist):
    return {"country_code": _country_of(artist), "mbid": artist.get("id"), "mb_name": artist.get("name")}


def lookup(name, mbid=None):
    """Sanatçıyı bulur. Döner: {'country_code', 'mbid', 'mb_name'} ya da None (bulunamadı).

    Ağ hatasında MBNetworkError fırlatır.
    """
    if mbid:
        data = _get(f"artist/{mbid}", {})
        if data:
            return _match(data)

    escaped = _LUCENE_SPECIAL.sub(r"\\\1", name)
    data = _get("artist", {"query": f'artist:"{escaped}"', "limit": 5}) or {}
    candidates = data.get("artists") or []
    wanted = _norm(name)
    # Önce adı birebir eşleşen ve ülkesi olan, sonra adı eşleşen ilk sonuç
    exact = [a for a in candidates if a.get("score", 0) >= 90 and (
        _norm(a.get("name")) == wanted
        or any(_norm(al.get("name")) == wanted for al in a.get("aliases") or []))]
    for a in exact:
        if _country_of(a):
            return _match(a)
    return _match(exact[0]) if exact else None
