"""Kafka -> PostgreSQL consumer.

Kullanım:
    python consumer.py        # sürekli çalışır, Ctrl+C ile durdurulur

Offset'ler yalnızca veritabanına yazma başarılı olduktan sonra commit edilir
(at-least-once). Tekrar gelen mesajlar primary key sayesinde çift kayıt oluşturmaz.
"""
import json
import logging
import time
from collections import defaultdict

import psycopg
from confluent_kafka import Consumer, KafkaError

import config
from db import connect, init_schema
from kafka_utils import ensure_topics

log = logging.getLogger("consumer")

T = config.TOPICS
# topic -> (tablo, kolonlar, ON CONFLICT ifadesi)
TABLES = {
    T["geo_top_artists"]: ("geo_top_artists",
        ["fetched_at", "country", "rank", "artist_name", "listeners", "mbid", "url"],
        "DO NOTHING"),
    T["geo_top_tracks"]: ("geo_top_tracks",
        ["fetched_at", "country", "rank", "track_name", "artist_name",
         "duration_sec", "listeners", "mbid", "url"],
        "DO NOTHING"),
    T["chart_top_artists"]: ("chart_top_artists",
        ["fetched_at", "rank", "artist_name", "playcount", "listeners", "mbid", "url"],
        "DO NOTHING"),
    T["chart_top_tracks"]: ("chart_top_tracks",
        ["fetched_at", "rank", "track_name", "artist_name", "duration_sec",
         "playcount", "listeners", "mbid", "url"],
        "DO NOTHING"),
    T["chart_top_tags"]: ("chart_top_tags",
        ["fetched_at", "rank", "tag_name", "reach", "taggings", "url"],
        "DO NOTHING"),
    T["artist_tags"]: ("artist_tags",
        ["artist_name", "tag_name", "tag_count", "updated_at"],
        "(artist_name, tag_name) DO UPDATE SET tag_count = EXCLUDED.tag_count, "
        "updated_at = EXCLUDED.updated_at"),
    T["artist_country"]: ("artist_country",
        ["artist_name", "country_code", "mbid", "mb_name", "updated_at"],
        "(artist_name) DO UPDATE SET country_code = EXCLUDED.country_code, mbid = EXCLUDED.mbid, "
        "mb_name = EXCLUDED.mb_name, updated_at = EXCLUDED.updated_at"),
}

SQL = {
    topic: (
        f"INSERT INTO {table} ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) ON CONFLICT {conflict}"
    )
    for topic, (table, cols, conflict) in TABLES.items()
}


def write_batch(conn, batches):
    with conn.cursor() as cur:
        for topic, rows in batches.items():
            cur.executemany(SQL[topic], rows)
    conn.commit()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ensure_topics()
    conn = connect()
    init_schema(conn)
    log.info("Veritabanı hazır, topic'ler dinleniyor...")

    consumer = Consumer({
        "bootstrap.servers": config.KAFKA_BOOTSTRAP_SERVERS,
        "group.id": config.CONSUMER_GROUP,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe(list(TABLES))

    total = 0
    try:
        while True:
            msgs = consumer.consume(num_messages=500, timeout=1.0)
            if not msgs:
                continue

            batches = defaultdict(list)
            processed = 0
            for msg in msgs:
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        log.error("Kafka hatası: %s", msg.error())
                    continue
                processed += 1
                try:
                    rec = json.loads(msg.value())
                except (TypeError, ValueError):
                    log.error("Bozuk mesaj atlandı (%s @ %s)", msg.topic(), msg.offset())
                    continue
                cols = TABLES[msg.topic()][1]
                batches[msg.topic()].append(tuple(rec.get(c) for c in cols))

            if not processed:
                continue

            # Veritabanı geçici olarak erişilemezse aynı batch'i tekrar dene.
            while True:
                try:
                    write_batch(conn, batches)
                    break
                except psycopg.OperationalError as exc:
                    log.error("Veritabanı hatası, 5 sn sonra tekrar: %s", exc)
                    time.sleep(5)
                    try:
                        conn.close()
                        conn = connect()
                    except psycopg.OperationalError:
                        pass

            consumer.commit(asynchronous=False)
            total += sum(len(r) for r in batches.values())
            summary = ", ".join(f"{TABLES[t][0]}={len(r)}" for t, r in batches.items())
            log.info("Yazıldı: %s (toplam %d)", summary, total)
    except KeyboardInterrupt:
        log.info("Durduruldu.")
    finally:
        consumer.close()
        conn.close()


if __name__ == "__main__":
    main()
