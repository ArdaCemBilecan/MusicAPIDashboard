#!/usr/bin/env bash
# Music Dashboard: günlük veri çekimi (Linux / macOS)
#
# Last.fm ve MusicBrainz'den verileri çekip Kafka'ya gönderir (src/producer.py).
# Cron tarafından günde bir kez çağrılır; kurulum için deploy/crontab dosyasına bakın.
#
# Not: Verinin veritabanına yazılması için consumer'ın (src/consumer.py) ve
# docker compose servislerinin sürekli çalışıyor olması gerekir.
#
# Ortam değişkenleriyle ayarlanabilir:
#   PYTHON         kullanılacak Python (varsayılan: proje içindeki .venv, yoksa python3)
#   PRODUCER_ARGS  producer'a ek argümanlar (ör. "--skip-tags")
#   LOG_KEEP_DAYS  kaç günlük log saklansın (varsayılan: 30)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
LOCK_FILE="$LOG_DIR/daily_fetch.lock"
LOG_FILE="$LOG_DIR/fetch_$(date +%Y-%m-%d).log"
LOG_KEEP_DAYS="${LOG_KEEP_DAYS:-30}"

if [[ -z "${PYTHON:-}" ]]; then
    if [[ -x "$PROJECT_DIR/.venv/bin/python" ]]; then
        PYTHON="$PROJECT_DIR/.venv/bin/python"
    else
        PYTHON="python3"
    fi
fi

mkdir -p "$LOG_DIR"

# Önceki çalışma hâlâ sürüyorsa (ör. uzun MusicBrainz adımı) yenisini başlatma
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "$(date '+%F %T') Önceki çekim hâlâ çalışıyor, bu çalıştırma atlandı." >> "$LOG_FILE"
    exit 0
fi

{
    echo "===== $(date '+%F %T') günlük çekim başladı ====="
    cd "$PROJECT_DIR/src"
    # shellcheck disable=SC2086  # PRODUCER_ARGS bilerek kelimelere bölünüyor
    if "$PYTHON" producer.py ${PRODUCER_ARGS:-}; then
        echo "===== $(date '+%F %T') günlük çekim bitti ====="
        status=0
    else
        status=$?
        echo "===== $(date '+%F %T') günlük çekim HATA ile bitti (çıkış kodu $status) ====="
    fi
} >> "$LOG_FILE" 2>&1

# Eski logları temizle
find "$LOG_DIR" -name 'fetch_*.log' -type f -mtime +"$LOG_KEEP_DAYS" -delete 2>/dev/null || true

exit "${status:-0}"
