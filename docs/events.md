# Event Contract (Outbox + Rabbit)

Этот документ фиксирует единый формат событий, который:
- хранится в `outbox_events.payload`
- публикуется в RabbitMQ как body сообщения
- читается worker’ом строго через `EventEnvelope`

## Envelope: EventEnvelope (schema_version 1.x)

Все события имеют общий “конверт”:

```json
{
  "event_id": "uuid",
  "event_type": "string",
  "schema_version": "MAJOR.MINOR",
  "occurred_at": "UTC ISO8601 datetime",
  "producer": "string",
  "correlation_id": "string|null",
  "trace_id": "string|null",
  "payload": { "event-specific": "data" }
}