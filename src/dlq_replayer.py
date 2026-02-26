import json
import pika
from src.config import RABBIT_URL, RABBIT_QUEUE

QUEUE_DLQ = f"{RABBIT_QUEUE}.dlq"


def main():
    connection = pika.BlockingConnection(pika.URLParameters(RABBIT_URL))
    channel = connection.channel()

    while True:
        method, properties, body = channel.basic_get(QUEUE_DLQ)

        if not method:
            print("DLQ empty")
            break

        print("Requeue message:", body)

        channel.basic_publish(
            exchange="",
            routing_key=RABBIT_QUEUE,
            body=body,
            properties=properties,
        )

        channel.basic_ack(method.delivery_tag)

    connection.close()


if __name__ == "__main__":
    main()