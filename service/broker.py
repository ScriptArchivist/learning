import json
import time
import pika
from src.config import RABBIT_URL, RABBIT_QUEUE

def publish_video_process(video_id: int, path: str) -> None:
    """Публикует задачу обработки видео в Rabbit."""
    params = pika.URLParameters(RABBIT_URL)
    conn = pika.BlockingConnection(params)
    ch = conn.channel()

    # durable очередь — переживает рестарт Rabbit (сообщения тоже могут быть durable)
    ch.queue_declare(queue=RABBIT_QUEUE, durable=True)

    payload = {"video_id": video_id, "path": path}

    ch.basic_publish(
        exchange="",
        routing_key=RABBIT_QUEUE,
        body=json.dumps(payload).encode("utf-8"),
        properties=pika.BasicProperties(delivery_mode=2),  # сообщение durable
    )
    conn.close()


def consume_forever(handler):
    """Запускает consumer, который вызывает handler(payload_dict)."""
    params = pika.URLParameters(RABBIT_URL)

    while True:
      try:
        conn = pika.BlockingConnection(params)
        ch = conn.channel()
        ch.queue_declare(queue=RABBIT_QUEUE, durable=True)
        ch.basic_qos(prefetch_count=1)  # 1 сообщение на воркер за раз

        def on_message(channel, method, properties, body: bytes):
            payload = json.loads(body.decode("utf-8"))
            handler(payload)
            channel.basic_ack(delivery_tag=method.delivery_tag)

        ch.basic_consume(queue=RABBIT_QUEUE, on_message_callback=on_message)
        ch.start_consuming()

      except Exception:
        # примитивный автоперезапуск при проблемах с Rabbit
        time.sleep(2)
