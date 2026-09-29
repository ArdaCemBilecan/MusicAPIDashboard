"""Last.fm API istemcisi: rate limit ve tekrar deneme içerir."""
import logging
import time

import requests

from config import LASTFM_API_KEY, LASTFM_BASE_URL

log = logging.getLogger(__name__)

NETWORK_ERROR = -1   # bağlantı / DNS / zaman aşımı
NOT_FOUND = 6        # sanatçı, albüm vb. bulunamadı
# 8: geçici hata, 11: servis kapalı, 16: geçici işlem hatası, 29: rate limit
RETRYABLE_CODES = {NETWORK_ERROR, 8, 11, 16, 29}
MIN_INTERVAL = 0.25  # saniyede en fazla ~4 istek
MAX_BACKOFF = 30     # iki deneme arası en fazla bekleme (sn)

_session = requests.Session()
_session.headers["User-Agent"] = "MusicDashboard/0.1"
_last_call = 0.0


class LastFMError(Exception):
    def __init__(self, code, message):
        super().__init__(f"[{code}] {message}")
        self.code = code

    @property
    def is_network(self):
        return self.code == NETWORK_ERROR


def _short(exc):
    """Uzun urllib3 hata metinlerini tek satıra indirir."""
    if isinstance(exc, requests.Timeout):
        return "zaman aşımı"
    if isinstance(exc, requests.ConnectionError):
        text = str(exc)
        if "NameResolution" in text or "getaddrinfo" in text:
            return "DNS çözümlenemedi (internet bağlantısı yok olabilir)"
        return "bağlantı hatası"
    return type(exc).__name__


def call(method: str, retries: int = 5, **params) -> dict:
    """Last.fm API'ye GET isteği atar ve JSON döner."""
    global _last_call
    if not LASTFM_API_KEY:
        raise LastFMError(-2, "LASTFM_API_KEY bulunamadı (.env dosyasını kontrol edin).")

    query = {"method": method, "api_key": LASTFM_API_KEY, "format": "json", **params}
    label = f"{method}({params.get('artist') or params.get('country') or ''})"

    for attempt in range(retries + 1):
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()

        try:
            resp = _session.get(LASTFM_BASE_URL, params=query, timeout=(5, 20))
            data = resp.json()
        except requests.RequestException as exc:
            err = LastFMError(NETWORK_ERROR, _short(exc))
        except ValueError:
            err = LastFMError(8, f"geçersiz JSON (HTTP {resp.status_code})")
        else:
            if "error" not in data:
                resp.raise_for_status()
                return data
            err = LastFMError(data["error"], data.get("message"))

        if err.code not in RETRYABLE_CODES or attempt == retries:
            raise err
        delay = min(2 ** (attempt + 1), MAX_BACKOFF)
        log.warning("%s başarısız: %s -> %ss sonra tekrar (%d/%d)",
                    label, err, delay, attempt + 1, retries)
        time.sleep(delay)
