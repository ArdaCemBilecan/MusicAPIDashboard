"""Kafka yardımcıları."""
import logging

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from config import KAFKA_BOOTSTRAP_SERVERS, TOPICS

log = logging.getLogger(__name__)


def ensure_topics(num_partitions: int = 3) -> None:
    """Eksik topic'leri oluşturur."""
    admin = AdminClient({"bootstrap.servers": KAFKA_BOOTSTRAP_SERVERS})
    existing = set(admin.list_topics(timeout=10).topics)
    missing = [
        NewTopic(t, num_partitions=num_partitions, replication_factor=1)
        for t in TOPICS.values() if t not in existing
    ]
    if not missing:
        return
    for topic, future in admin.create_topics(missing).items():
        try:
            future.result()
            log.info("Topic oluşturuldu: %s", topic)
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:
                raise
