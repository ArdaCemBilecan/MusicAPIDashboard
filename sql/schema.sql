-- Music Dashboard şeması. Consumer her başlangıçta çalıştırır (IF NOT EXISTS).
-- Her çekim bir "snapshot"tır: aynı fetched_at değerine sahip satırlar aynı çalışmadan gelir.

CREATE TABLE IF NOT EXISTS geo_top_artists (
    fetched_at   TIMESTAMPTZ NOT NULL,
    country      TEXT        NOT NULL,
    rank         INT         NOT NULL,
    artist_name  TEXT        NOT NULL,
    listeners    BIGINT,
    mbid         TEXT,
    url          TEXT,
    PRIMARY KEY (country, fetched_at, rank)
);

CREATE TABLE IF NOT EXISTS geo_top_tracks (
    fetched_at   TIMESTAMPTZ NOT NULL,
    country      TEXT        NOT NULL,
    rank         INT         NOT NULL,
    track_name   TEXT        NOT NULL,
    artist_name  TEXT        NOT NULL,
    duration_sec INT,
    listeners    BIGINT,
    mbid         TEXT,
    url          TEXT,
    PRIMARY KEY (country, fetched_at, rank)
);

CREATE TABLE IF NOT EXISTS chart_top_artists (
    fetched_at   TIMESTAMPTZ NOT NULL,
    rank         INT         NOT NULL,
    artist_name  TEXT        NOT NULL,
    playcount    BIGINT,
    listeners    BIGINT,
    mbid         TEXT,
    url          TEXT,
    PRIMARY KEY (fetched_at, rank)
);

CREATE TABLE IF NOT EXISTS chart_top_tracks (
    fetched_at   TIMESTAMPTZ NOT NULL,
    rank         INT         NOT NULL,
    track_name   TEXT        NOT NULL,
    artist_name  TEXT        NOT NULL,
    duration_sec INT,
    playcount    BIGINT,
    listeners    BIGINT,
    mbid         TEXT,
    url          TEXT,
    PRIMARY KEY (fetched_at, rank)
);

CREATE TABLE IF NOT EXISTS chart_top_tags (
    fetched_at   TIMESTAMPTZ NOT NULL,
    rank         INT         NOT NULL,
    tag_name     TEXT        NOT NULL,
    reach        BIGINT,
    taggings     BIGINT,
    url          TEXT,
    PRIMARY KEY (fetched_at, rank)
);

-- Sanatçı -> tür etiketleri (tarz analizi için). Snapshot değil, güncel durum.
CREATE TABLE IF NOT EXISTS artist_tags (
    artist_name  TEXT        NOT NULL,
    tag_name     TEXT        NOT NULL,
    tag_count    INT,
    updated_at   TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (artist_name, tag_name)
);

CREATE INDEX IF NOT EXISTS idx_geo_artists_name ON geo_top_artists (artist_name);
CREATE INDEX IF NOT EXISTS idx_geo_tracks_artist ON geo_top_tracks (artist_name);
CREATE INDEX IF NOT EXISTS idx_artist_tags_tag ON artist_tags (tag_name);

-- Son snapshot'a göre ülkelerin dinlediği türler
CREATE OR REPLACE VIEW v_country_genres AS
WITH latest AS (
    SELECT country, MAX(fetched_at) AS fetched_at
    FROM geo_top_artists
    GROUP BY country
)
SELECT g.country,
       t.tag_name,
       COUNT(*)         AS artist_count,
       SUM(g.listeners) AS listeners
FROM geo_top_artists g
JOIN latest l      ON l.country = g.country AND l.fetched_at = g.fetched_at
JOIN artist_tags t ON t.artist_name = g.artist_name
GROUP BY g.country, t.tag_name;

-- =====================================================================
-- Sanatçının ana ülkesi ve yurtdışı payı
-- =====================================================================

-- Ülke kodları (ISO 3166-1 alpha-2). İlk 17 ad Last.fm'in geo adlarıyla birebir aynı.
CREATE TABLE IF NOT EXISTS countries (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
INSERT INTO countries (code, name) VALUES
    ('TR','Turkey'),('US','United States'),('GB','United Kingdom'),('DE','Germany'),
    ('FR','France'),('ES','Spain'),('IT','Italy'),('NL','Netherlands'),('SE','Sweden'),
    ('PL','Poland'),('RU','Russian Federation'),('BR','Brazil'),('MX','Mexico'),
    ('AR','Argentina'),('CA','Canada'),('JP','Japan'),('AU','Australia'),
    ('KR','South Korea'),('CO','Colombia'),('PR','Puerto Rico'),('IE','Ireland'),
    ('NO','Norway'),('DK','Denmark'),('FI','Finland'),('BE','Belgium'),('AT','Austria'),
    ('CH','Switzerland'),('PT','Portugal'),('GR','Greece'),('UA','Ukraine'),
    ('CZ','Czech Republic'),('HU','Hungary'),('RO','Romania'),('IS','Iceland'),
    ('NZ','New Zealand'),('JM','Jamaica'),('CU','Cuba'),('CL','Chile'),('PE','Peru'),
    ('VE','Venezuela'),('IN','India'),('CN','China'),('TW','Taiwan'),('IL','Israel'),
    ('EG','Egypt'),('MA','Morocco'),('NG','Nigeria'),('ZA','South Africa'),
    ('DZ','Algeria'),('TN','Tunisia'),('LB','Lebanon'),('AZ','Azerbaijan'),
    ('KZ','Kazakhstan'),('BY','Belarus'),('RS','Serbia'),('HR','Croatia'),
    ('BG','Bulgaria'),('SK','Slovakia'),('SI','Slovenia'),('EE','Estonia'),
    ('LV','Latvia'),('LT','Lithuania'),('ID','Indonesia'),('PH','Philippines'),
    ('TH','Thailand'),('VN','Vietnam'),('MY','Malaysia'),('SG','Singapore'),
    ('SA','Saudi Arabia'),('AE','United Arab Emirates'),('IR','Iran'),('PK','Pakistan'),
    ('CY','Cyprus'),('GE','Georgia'),('AM','Armenia'),('AL','Albania'),
    ('BA','Bosnia and Herzegovina'),('MK','North Macedonia'),('XK','Kosovo'),
    ('UY','Uruguay'),('DO','Dominican Republic'),('PA','Panama'),('LU','Luxembourg')
ON CONFLICT (code) DO NOTHING;

-- MusicBrainz'den gelen ülke bilgisi (country_code NULL = bulunamadı)
CREATE TABLE IF NOT EXISTS artist_country (
    artist_name  TEXT PRIMARY KEY,
    country_code TEXT,
    mbid         TEXT,
    mb_name      TEXT,
    updated_at   TIMESTAMPTZ NOT NULL
);

-- Arayüzden elle yapılan düzeltmeler (her zaman önceliklidir)
CREATE TABLE IF NOT EXISTS artist_country_override (
    artist_name  TEXT PRIMARY KEY,
    country_code TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Her ülkenin son snapshot'ı
CREATE OR REPLACE VIEW v_geo_artists_latest AS
SELECT g.*
FROM geo_top_artists g
JOIN (SELECT country, MAX(fetched_at) AS fetched_at FROM geo_top_artists GROUP BY country) l
  ON l.country = g.country AND l.fetched_at = g.fetched_at;

-- Sanatçının ana ülkesi: elle düzeltme > MusicBrainz > en çok dinlendiği ülke (Tahmini)
CREATE OR REPLACE VIEW v_artist_home AS
WITH most_listened AS (
    SELECT DISTINCT ON (artist_name) artist_name, country AS country_name
    FROM v_geo_artists_latest
    ORDER BY artist_name, listeners DESC NULLS LAST, rank
)
SELECT m.artist_name,
       COALESCE(o.country_code, ac.country_code, mc.code) AS home_code,
       CASE WHEN o.country_code IS NOT NULL THEN 'Elle girildi'
            WHEN ac.country_code IS NOT NULL THEN 'MusicBrainz'
            ELSE 'Tahmini' END AS home_source,
       ac.country_code AS musicbrainz_code,
       COALESCE(ac.country_code, mc.code) AS auto_code
FROM most_listened m
LEFT JOIN artist_country_override o ON o.artist_name = m.artist_name
LEFT JOIN artist_country ac          ON ac.artist_name = m.artist_name
LEFT JOIN countries mc               ON mc.name = m.country_name;

-- Sanatçı x ülke dinleyicileri, yurt içi / yurt dışı ayrımıyla (son snapshot)
CREATE OR REPLACE VIEW v_artist_country_listeners AS
SELECT g.fetched_at,
       g.country,
       c.code AS country_code,
       g.artist_name,
       g.rank,
       g.listeners,
       h.home_code,
       COALESCE(hc.name, h.home_code) AS home_country,
       h.home_source,
       COALESCE(c.code = h.home_code, false) AS is_home,
       CASE WHEN COALESCE(c.code = h.home_code, false) THEN 'Yurt içi' ELSE 'Yurt dışı' END AS location
FROM v_geo_artists_latest g
LEFT JOIN countries c  ON c.name = g.country
JOIN v_artist_home h   ON h.artist_name = g.artist_name
LEFT JOIN countries hc ON hc.code = h.home_code;

-- Sanatçı bazında özet: yurtdışı payı = yurtdışı / (yurt içi + yurtdışı)
CREATE OR REPLACE VIEW v_artist_foreign_share AS
SELECT artist_name,
       home_code,
       home_country,
       home_source,
       SUM(listeners) FILTER (WHERE is_home)                AS home_listeners,
       COALESCE(SUM(listeners) FILTER (WHERE NOT is_home), 0) AS foreign_listeners,
       SUM(listeners)                                        AS total_listeners,
       COUNT(*) FILTER (WHERE NOT is_home)                   AS foreign_countries,
       ROUND(100.0 * COALESCE(SUM(listeners) FILTER (WHERE NOT is_home), 0)
             / NULLIF(SUM(listeners), 0), 1)                 AS foreign_share_pct,
       ROUND(100.0 * COALESCE(SUM(listeners) FILTER (WHERE NOT is_home), 0)
             / NULLIF(SUM(listeners) FILTER (WHERE is_home), 0), 1) AS foreign_to_home_pct
FROM v_artist_country_listeners
GROUP BY artist_name, home_code, home_country, home_source;
