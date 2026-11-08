"""Event Bus cho giao tiếp bất đồng bộ (Event-driven / Publish-Subscribe).

Transport (biến EVENT_BUS):
- "rabbitmq": dùng RabbitMQ topic exchange `grocery.events` (chạy bằng Docker).
  Mỗi service có một queue bền vững `<service>.events`; message xử lý lỗi 2 lần
  sẽ được chuyển vào Dead Letter Queue `grocery.dead-letters`.
- "http": chế độ chạy local không cần RabbitMQ - publisher POST sự kiện tới
  endpoint /internal/events của các service trong EVENT_HTTP_SUBSCRIBERS.
- "none": chỉ ghi log.

Consumer là idempotent: id sự kiện đã xử lý được lưu vào bảng processed_events
để không xử lý trùng khi broker giao lại message.
"""
import json
import logging
import os
import random
import threading
import time
import uuid

import requests
from flask import request

from common.auth import internal_only
from common.config import INTERNAL_API_KEY, env_bool
from common.utils import now_str

log = logging.getLogger(__name__)

EXCHANGE = "grocery.events"
DLX_EXCHANGE = "grocery.dlx"
DLQ_QUEUE = "grocery.dead-letters"

PROCESSED_DDL = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    processed_at TEXT NOT NULL
)
"""


def topic_matches(pattern, key):
    """So khớp routing key theo luật AMQP topic: '*' = đúng 1 từ, '#' = 0..n từ."""
    p_words, k_words = pattern.split("."), key.split(".")

    def match(pi, ki):
        if pi == len(p_words):
            return ki == len(k_words)
        word = p_words[pi]
        if word == "#":
            return any(match(pi + 1, j) for j in range(ki, len(k_words) + 1))
        if ki == len(k_words):
            return False
        return (word == "*" or word == k_words[ki]) and match(pi + 1, ki + 1)

    return match(0, 0)


class EventBus:
    def __init__(self, service_name, db=None):
        self.service = service_name
        self.db = db
        self.transport = os.environ.get("EVENT_BUS", "none").strip().lower()
        self.rabbit_url = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/%2F")
        self.http_subscribers = [
            u.strip().rstrip("/") for u in os.environ.get("EVENT_HTTP_SUBSCRIBERS", "").split(",") if u.strip()
        ]
        self.handlers = []
        self._pub_lock = threading.Lock()
        self._pub_conn = None
        self._pub_channel = None
        self._started = False

    # ------------------------------------------------------------ đăng ký
    def on(self, pattern):
        def decorator(fn):
            self.handlers.append((pattern, fn))
            return fn

        return decorator

    def init_app(self, app):
        """Gắn endpoint nhận sự kiện qua HTTP và khởi động consumer."""
        if self.db is not None and self.handlers:
            self.db.init_schema(PROCESSED_DDL)

        bus = self

        @app.post("/internal/events")
        @internal_only
        def _receive_event():
            event = request.get_json(silent=True) or {}
            handled = bus.dispatch(event)
            return {"handled": handled}

        self.start_consumer()

    # ------------------------------------------------------------ publish
    def publish(self, event_type, data):
        event = {
            "id": uuid.uuid4().hex,
            "type": event_type,
            "source": self.service,
            "occurred_at": now_str(),
            "data": data,
        }
        log.info("Publish event %s (%s)", event_type, event["id"])
        if self.transport == "rabbitmq":
            self._publish_rabbit(event)
        elif self.transport == "http":
            threading.Thread(target=self._publish_http, args=(event,), daemon=True).start()
        return event

    def _publish_rabbit(self, event):
        import pika

        body = json.dumps(event, ensure_ascii=False).encode("utf-8")
        with self._pub_lock:
            for attempt in range(3):
                try:
                    if self._pub_conn is None or self._pub_conn.is_closed:
                        params = pika.URLParameters(self.rabbit_url)
                        params.heartbeat = 600
                        params.blocked_connection_timeout = 30
                        self._pub_conn = pika.BlockingConnection(params)
                        self._pub_channel = self._pub_conn.channel()
                        self._pub_channel.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
                    else:
                        self._pub_conn.process_data_events(time_limit=0)
                    self._pub_channel.basic_publish(
                        exchange=EXCHANGE,
                        routing_key=event["type"],
                        body=body,
                        properties=pika.BasicProperties(
                            content_type="application/json", delivery_mode=2, message_id=event["id"]
                        ),
                    )
                    return True
                except Exception as exc:
                    log.warning("Publish RabbitMQ lỗi (lần %s): %s", attempt + 1, exc)
                    try:
                        if self._pub_conn is not None and not self._pub_conn.is_closed:
                            self._pub_conn.close()
                    except Exception:
                        pass
                    self._pub_conn = None
                    time.sleep(0.5 * (attempt + 1))
        log.error("Không publish được sự kiện %s", event["type"])
        return False

    def _http_targets(self):
        """Mỗi service nhận sự kiện ở MỘT instance (giống competing consumers trên một queue RabbitMQ).
        Danh sách lấy từ Service Registry, dự phòng bằng EVENT_HTTP_SUBSCRIBERS."""
        if env_bool("EVENT_HTTP_DISCOVERY", True):
            from common.registry import discovery

            services = discovery.all_services()
            targets = [random.choice(urls) for urls in services.values() if urls]
            if targets:
                return targets
        return self.http_subscribers

    def _publish_http(self, event):
        headers = {"X-Internal-Token": INTERNAL_API_KEY}
        for url in self._http_targets():
            for attempt in range(3):
                try:
                    resp = requests.post(url + "/internal/events", json=event, headers=headers, timeout=10)
                    if resp.status_code < 500:
                        break
                except requests.RequestException as exc:
                    log.debug("Gửi sự kiện tới %s lỗi: %s", url, exc)
                time.sleep(0.5 * (attempt + 1))

    # ------------------------------------------------------------ consume
    def dispatch(self, event):
        """Gọi các handler khớp với loại sự kiện. Trả về số handler đã chạy."""
        event_type = event.get("type") or ""
        matched = [fn for pattern, fn in self.handlers if topic_matches(pattern, event_type)]
        if not matched:
            return 0
        event_id = event.get("id")
        if self.db is not None and event_id:
            done = self.db.query_one("SELECT event_id FROM processed_events WHERE event_id = ?", (event_id,))
            if done:
                log.info("Bỏ qua sự kiện trùng %s", event_id)
                return 0
        for fn in matched:
            fn(event.get("data") or {}, event)
        if self.db is not None and event_id:
            try:
                self.db.execute(
                    "INSERT INTO processed_events (event_id, event_type, processed_at) VALUES (?, ?, ?)",
                    (event_id, event_type, now_str()),
                )
            except Exception:
                pass
        log.info("Đã xử lý sự kiện %s (%s handler)", event_type, len(matched))
        return len(matched)

    def start_consumer(self):
        if self._started or not self.handlers or self.transport != "rabbitmq":
            return
        self._started = True
        threading.Thread(target=self._consume_forever, daemon=True, name=f"{self.service}-consumer").start()

    def _consume_forever(self):
        import pika

        queue = f"{self.service}.events"
        patterns = sorted({p for p, _ in self.handlers})
        while True:
            try:
                params = pika.URLParameters(self.rabbit_url)
                params.heartbeat = 60
                conn = pika.BlockingConnection(params)
                ch = conn.channel()
                ch.exchange_declare(exchange=EXCHANGE, exchange_type="topic", durable=True)
                ch.exchange_declare(exchange=DLX_EXCHANGE, exchange_type="fanout", durable=True)
                ch.queue_declare(queue=DLQ_QUEUE, durable=True)
                ch.queue_bind(exchange=DLX_EXCHANGE, queue=DLQ_QUEUE)
                ch.queue_declare(queue=queue, durable=True, arguments={"x-dead-letter-exchange": DLX_EXCHANGE})
                for pattern in patterns:
                    ch.queue_bind(exchange=EXCHANGE, queue=queue, routing_key=pattern)
                ch.basic_qos(prefetch_count=10)

                def on_message(channel, method, properties, body):
                    try:
                        self.dispatch(json.loads(body))
                        channel.basic_ack(delivery_tag=method.delivery_tag)
                    except Exception:
                        log.exception("Xử lý sự kiện lỗi (redelivered=%s)", method.redelivered)
                        # thử lại 1 lần, lần 2 vẫn lỗi -> Dead Letter Queue
                        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=not method.redelivered)

                ch.basic_consume(queue=queue, on_message_callback=on_message)
                log.info("Consumer %s lắng nghe: %s", queue, ", ".join(patterns))
                ch.start_consuming()
            except Exception as exc:
                log.warning("Mất kết nối RabbitMQ (%s), kết nối lại sau 5s", exc)
                time.sleep(5)
