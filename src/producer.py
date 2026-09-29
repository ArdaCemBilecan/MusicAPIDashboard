"""Last.fm -> Kafka producer.

Kullanım:
    python producer.py                   # bir kez çalışır
    python producer.py --loop            # her saat başı tekrar eder
    python producer.py --loop --interval 1800
    python producer.py --skip-tags       # sanatçı etiketlerini çekmez (hızlı test)
    python producer.py --skip-countries  # MusicBrainz ülke adımını atlar
"""
import argparse
import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from confluent_kafka import Producer

import config
import musicbrainz
import transforms
from kafka_utils import ensure_topics
from lastfm_client import NOT_FOUND, LastFMError, call

NETWORK_PAUSE_AFTER = 3   # art arda bu kadar bağlantı hatasında...
NETWORK_PAUSE_SEC = 60    # ...bu kadar saniye bekle

log = logging.getLogger("producer")


class Sender:
    def __init__(self):
        self.producer = Producer({
            "bootstrap.servers": config.KAFKA_BOOTSTRAP_SERVERS,
            "acks": "all",
            "enable.idempotence": True,
            "linger.ms": 50,
        })
        self.sent = Counter()
        self.failed = 0

    def _on_delivery(self, err, msg):
        if err is not None:
            self.failed += 1
            log.error("Mesaj gönderilemedi (%s): %s", msg.topic(), err)

    def send(self, dataset, records, key_field=None):
        topic = config.TOPICS[dataset]
        for rec in records:
            key = rec.get(key_field) if key_field else None
            self.producer.produce(
                topic,
                key=key.encode("utf-8") if key else None,
                value=json.dumps(rec, ensure_ascii=False).encode("utf-8"),
                on_delivery=self._on_delivery,
            )
            self.producer.poll(0)
        self.sent[dataset] += len(records)

    def flush(self):
        remaining = self.producer.flush(30)
        if remaining:
            log.error("%d mesaj gönderilemeden kaldı", remaining)


def load_tag_cache():
    try:
        return json.loads(config.TAG_CACHE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_tag_cache(cache):
    config.DATA_DIR.mkdir(exist_ok=True)
    config.TAG_CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def fetch_charts(sender, fetched_at, artists):
    jobs = [
        ("chart_top_artists", "chart.gettopartists", transforms.chart_top_artists),
        ("chart_top_tracks", "chart.gettoptracks", transforms.chart_top_tracks),
        ("chart_top_tags", "chart.gettoptags", transforms.chart_top_tags),
    ]
    for dataset, method, fn in jobs:
        try:
            records = fn(call(method, limit=config.CHART_LIMIT), fetched_at)
        except LastFMError as exc:
            log.warning("%s atlandı: %s", method, exc)
            continue
        sender.send(dataset, records)
        artists.update(r["artist_name"] for r in records if r.get("artist_name"))


def fetch_paged(method, wrapper, item_key, total, **params):
    """Sayfalı Last.fm listesini çeker; tekrar eden kayıtları ayıklar."""
    size = min(config.GEO_PAGE_SIZE, total)
    items, seen, page = [], set(), 1
    while len(items) < total:
        data = call(method, limit=size, page=page, **params)
        block = data.get(wrapper, {})
        batch = block.get(item_key) or []
        if isinstance(batch, dict):
            batch = [batch]
        for it in batch:
            artist = it.get("artist")
            key = (it.get("name"), artist.get("name") if isinstance(artist, dict) else artist)
            if key not in seen:
                seen.add(key)
                items.append(it)
        total_pages = int((block.get("@attr") or {}).get("totalPages") or page)
        if not batch or page >= total_pages:
            break
        page += 1
    return {wrapper: {item_key: items[:total]}}


def fetch_countries(sender, fetched_at, artists, geo_artists):
    for country in config.COUNTRIES:
        try:
            a = transforms.geo_top_artists(
                fetch_paged("geo.gettopartists", "topartists", "artist",
                            config.GEO_ARTIST_LIMIT, country=country),
                country, fetched_at)
            t = transforms.geo_top_tracks(
                fetch_paged("geo.gettoptracks", "tracks", "track",
                            config.GEO_TRACK_LIMIT, country=country),
                country, fetched_at)
        except LastFMError as exc:
            log.warning("%s atlandı: %s", country, exc)
            continue
        sender.send("geo_top_artists", a, key_field="country")
        sender.send("geo_top_tracks", t, key_field="country")
        artists.update(r["artist_name"] for r in a + t if r.get("artist_name"))
        for r in a:
            info = geo_artists.setdefault(r["artist_name"], {"listeners": 0, "mbid": None, "rank": 10**6})
            info["listeners"] = max(info["listeners"], r.get("listeners") or 0)
            info["rank"] = min(info["rank"], r["rank"])   # herhangi bir ülkedeki en iyi sırası
            info["mbid"] = info["mbid"] or r.get("mbid")
        log.info("%-20s %3d sanatçı, %3d şarkı", country, len(a), len(t))


def fetch_artist_tags(sender, fetched_at, artists):
    cache = load_tag_cache()
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.TAG_CACHE_DAYS)
    todo = sorted(
        name for name in artists
        if name not in cache or datetime.fromisoformat(cache[name]) < cutoff
    )
    log.info("Etiket çekilecek sanatçı: %d (önbellekte güncel: %d)",
             len(todo), len(artists) - len(todo))

    failed = []
    consecutive_network = 0

    def fetch(name):
        """True: başarılı / kalıcı olarak atlandı, False: tekrar denenmeli."""
        nonlocal consecutive_network
        try:
            data = call("artist.gettoptags", artist=name, autocorrect=1)
        except LastFMError as exc:
            if exc.is_network:
                consecutive_network += 1
                if consecutive_network >= NETWORK_PAUSE_AFTER:
                    log.warning("Bağlantı yok gibi görünüyor, %ds bekleniyor...", NETWORK_PAUSE_SEC)
                    time.sleep(NETWORK_PAUSE_SEC)
                    consecutive_network = 0
                return False
            consecutive_network = 0
            if exc.code == NOT_FOUND:
                # Last.fm'de bulunamayan sanatçıyı her çalışmada tekrar sormayalım.
                cache[name] = fetched_at
                return True
            log.warning("Etiket alınamadı (%s): %s", name, exc)
            return False
        consecutive_network = 0
        sender.send("artist_tags",
                    transforms.artist_tags(data, name, fetched_at, config.TAGS_PER_ARTIST),
                    key_field="artist_name")
        cache[name] = fetched_at
        return True

    try:
        for i, name in enumerate(todo, 1):
            if not fetch(name):
                failed.append(name)
            if i % 50 == 0:
                log.info("  etiketler: %d/%d (başarısız: %d)", i, len(todo), len(failed))
                save_tag_cache(cache)

        if failed:
            log.info("Başarısız %d sanatçı için son bir deneme yapılıyor...", len(failed))
            failed = [name for name in failed if not fetch(name)]
        if failed:
            log.warning("%d sanatçının etiketi alınamadı, bir sonraki çalışmada tekrar denenecek: %s",
                        len(failed), ", ".join(failed[:10]) + (" ..." if len(failed) > 10 else ""))
    finally:
        save_tag_cache(cache)


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def save_json(path, data):
    config.DATA_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def fetch_artist_countries(sender, fetched_at, geo_artists):
    """Ülke listelerindeki sanatçıların ana ülkesini MusicBrainz'den bulur.

    Her ülkenin listesinde üst sıralardaki sanatçılardan başlar; her çalıştırmada en fazla MB_MAX_PER_RUN
    sanatçı sorgulanır, kalanlar sonraki çalıştırmalara kalır. O zamana kadar
    dashboard, sanatçının en çok dinlendiği ülkeyi kullanır.
    """
    cache = load_json(config.COUNTRY_CACHE_FILE)
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MB_CACHE_DAYS)
    pending = [n for n in geo_artists
               if n not in cache or datetime.fromisoformat(cache[n]["ts"]) < cutoff]
    # Her ülkenin kendi listesindeki sıraya göre: böylece her çalıştırmada her ülkenin önde gelen
    # sanatçıları sorgulanır (yalnızca global olarak en çok dinlenenler değil)
    pending.sort(key=lambda n: (geo_artists[n].get("rank", 10**6), -geo_artists[n]["listeners"]))
    todo = pending[:config.MB_MAX_PER_RUN]
    log.info("Ülkesi aranacak sanatçı: %d (bu çalıştırmada %d, önbellekte güncel: %d)",
             len(pending), len(todo), len(geo_artists) - len(pending))

    found = consecutive_network = 0
    try:
        for i, name in enumerate(todo, 1):
            try:
                match = musicbrainz.lookup(name, geo_artists[name].get("mbid"))
            except musicbrainz.MBNetworkError as exc:
                consecutive_network += 1
                log.warning("MusicBrainz hatası (%s): %s", name, exc)
                if consecutive_network >= NETWORK_PAUSE_AFTER:
                    log.warning("MusicBrainz'e ulaşılamıyor; ülke adımı bir sonraki çalıştırmaya bırakıldı.")
                    break
                continue
            except Exception as exc:  # beklenmeyen yanıt: bu sanatçıyı atla
                log.warning("MusicBrainz yanıtı işlenemedi (%s): %s", name, exc)
                continue
            consecutive_network = 0
            record = transforms.artist_country(name, match, fetched_at)
            sender.send("artist_country", [record], key_field="artist_name")
            cache[name] = {"ts": fetched_at, "code": record["country_code"]}
            found += bool(record["country_code"])
            if i % 50 == 0:
                log.info("  ülkeler: %d/%d (bulunan: %d)", i, len(todo), found)
                save_json(config.COUNTRY_CACHE_FILE, cache)
    finally:
        save_json(config.COUNTRY_CACHE_FILE, cache)
    log.info("Ülke adımı bitti: %d sanatçının ülkesi bulundu.", found)


def run_once(skip_tags=False, skip_countries=False):
    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    log.info("Çekim başladı: %s", fetched_at)
    started = time.monotonic()
    sender = Sender()
    artists = set()
    geo_artists = {}
    try:
        fetch_charts(sender, fetched_at, artists)
        fetch_countries(sender, fetched_at, artists, geo_artists)
        if not skip_tags:
            fetch_artist_tags(sender, fetched_at, artists)
        if not skip_countries:
            fetch_artist_countries(sender, fetched_at, geo_artists)
    finally:
        sender.flush()
    log.info("Bitti (%.0fs). Gönderilen: %s, hatalı: %d",
             time.monotonic() - started, dict(sender.sent), sender.failed)


def main():
    parser = argparse.ArgumentParser(description="Last.fm verilerini Kafka'ya gönderir")
    parser.add_argument("--loop", action="store_true", help="sürekli çalış")
    parser.add_argument("--interval", type=int, default=3600, help="saniye (varsayılan 3600)")
    parser.add_argument("--skip-tags", action="store_true", help="sanatçı etiketlerini atla")
    parser.add_argument("--skip-countries", action="store_true", help="MusicBrainz ülke adımını atla")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ensure_topics()
    while True:
        run_once(skip_tags=args.skip_tags, skip_countries=args.skip_countries)
        if not args.loop:
            break
        log.info("%d saniye sonra tekrar çalışacak (durdurmak için Ctrl+C)", args.interval)
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Durduruldu.")
