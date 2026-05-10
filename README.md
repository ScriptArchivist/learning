# Video Platform DevOps Project

Production-oriented video platform built with FastAPI microservices, asynchronous video processing, event-driven architecture, Kubernetes/Helm deployment and a full observability stack.

The project is a реально работающая distributed system supporting both web (Next.js) and mobile (Flutter) clients and is used as a demonstration of DevOps/SRE-oriented backend platform engineering.

---

## Project Overview

The goal of the project is to demonstrate a complete backend platform lifecycle:

- FastAPI microservice architecture;
- video upload and processing pipeline;
- event-driven communication through RabbitMQ;
- transactional outbox pattern;
- idempotency and retry mechanisms;
- Docker / Docker Compose local full stand;
- Kubernetes / Helm cloud deployment profile;
- Prometheus / Grafana / Loki / Alertmanager observability stack;
- GitLab CI/CD pipelines with automated validation and security scanning.

---

## Key Features

- Event-driven video processing
- Transactional outbox pattern
- Idempotent upload pipeline
- RTMP → HLS live streaming
- Distributed background workers
- Kubernetes + Helm deployment
- PostgreSQL replication
- Retry / DLQ handling
- Centralized monitoring and logging
- Production-like backend architecture

---

## Tech Stack

### Backend

- FastAPI
- SQLAlchemy
- PostgreSQL
- RabbitMQ
- Redis

### Infrastructure

- Docker
- Docker Compose
- Kubernetes
- Helm
- Minikube
- NGINX

### Streaming

- RTMP
- HLS
- FFmpeg
- nginx-rtmp

### Observability

- Prometheus
- Grafana
- Loki
- Alertmanager

### Frontend / Clients

- Next.js
- Flutter

---

# Architecture

## Full Local Kubernetes Environment

Production-like local Kubernetes stand with:

- FastAPI microservices
- event-driven processing
- RTMP → HLS live streaming
- RabbitMQ event bus
- PostgreSQL replication
- centralized observability stack

[![Local Kubernetes Architecture](docs/architecture/Complete_K8S_Stend.png)](docs/architecture/Complete_K8S_Stend.png)

Architecture source:
- `docs/architecture/Local_K8S_stend.drawio`

### Legend

- Blue — Clients & Entry Points
- Green — API Services
- Orange — Background Workers
- Purple — Streaming Services
- Yellow — Infrastructure
- Red — Monitoring & Observability

---

## Cloud-ready Design

The architecture is designed with cloud deployment and horizontal scalability in mind.

---

### Stateless Services

- API and worker services do not store state locally;
- state is externalized into PostgreSQL / RabbitMQ / Redis;
- services can be scaled independently.

---

### Storage Abstraction

The platform uses a storage provider abstraction layer.

Current implementation:
- local filesystem storage.

Planned cloud implementation:
- AWS S3;
- Yandex Object Storage;
- S3-compatible object storage;
- presigned upload/download URLs.

This allows compute and storage layers to be separated.

---

### Asynchronous Processing

- heavy workloads are processed by background workers;
- RabbitMQ acts as an event bus and load buffer;
- the system is resilient to traffic spikes and retries.

---

### Reliability Patterns

Implemented reliability patterns include:

- transactional outbox;
- at-least-once delivery;
- retry/backoff;
- dead-letter queues (DLQ);
- idempotent consumers;
- distributed locks with TTL.

---

### Observability

- Prometheus metrics;
- Grafana dashboards;
- Loki centralized logging;
- Alertmanager alerts;
- request correlation through tracing headers.

---

### Kubernetes-ready

- Helm-based deployment;
- multiple environments;
- cloud demo-profile;
- independently scalable services.

---

### Design Goals

The platform is designed to:

- be cloud portable;
- scale by components;
- tolerate duplicate message delivery;
- remain observable and diagnosable;
- demonstrate production-oriented backend engineering practices.

---

## Main Video Pipeline

```text
upload-service
  -> PostgreSQL
  -> outbox_events
  -> outbox-publisher
  -> RabbitMQ
  -> processing-worker
  -> ffmpeg
  -> local storage / HLS
  -> video status update
  -> video-api playback
```

---

## Architectural Highlights

### Transactional Outbox

- events are first persisted into PostgreSQL;
- outbox-publisher asynchronously publishes them into RabbitMQ;
- retry/backoff mechanisms prevent message loss;
- database and message broker consistency is preserved.

---

### Idempotency

- upload flow uses `client_upload_id`;
- processing uses lock tokens with TTL;
- consumers tolerate repeated message delivery;
- state transitions are atomic (`READY`, `FAILED`).

---

### Event-driven Processing

The platform uses asynchronous communication between services:

```text
upload-service
    ↓
PostgreSQL + outbox_events
    ↓
outbox-publisher
    ↓
RabbitMQ
    ↓
processing-worker
    ↓
video-events-consumer
    ↓
video-api
```

---

## Environments

### Full Local Profile

Complete local environment with all services enabled.

```bash
docker-compose \
  --env-file deploy/docker/.env.dev \
  -f deploy/docker/docker-compose.ci.yml \
  up -d --build
```

---

### Cloud Demo Profile

Cloud-oriented reduced environment:

- Kubernetes + Helm
- reduced service set
- simplified deployment profile
- optimized resource usage

---

## Kubernetes / Helm

Helm chart location:

```text
deploy/helm/video-platform
```

Local Kubernetes manifests:

```text
deploy/k8s/base
```

---

## CI/CD

GitLab pipeline configuration:

```text
.gitlab-ci.yml
```

Pipeline stages include:

- lint
- test
- build
- container image build
- security scan (Trivy)
- deployment validation

---

## Monitoring & Observability

### Monitoring Stack

- Prometheus
- Grafana
- Loki
- Alertmanager
- node-exporter
- cAdvisor
- postgres-exporter

Documentation:

```text
docs/monitoring.md
```

---

## Project Structure

```text
app/
 ├── backend/              # FastAPI microservices
 ├── frontend/             # Next.js frontend
 └── mobile/               # Flutter client

deploy/
 ├── docker/               # Docker Compose environments
 ├── helm/                 # Helm charts
 └── k8s/                  # Kubernetes manifests

monitoring/
 ├── prometheus/
 ├── grafana/
 ├── loki/
 └── alertmanager/

docs/
 ├── architecture/
 ├── services/
 └── environments/
```

---

## Documentation

- `docs/architecture.md`
- `docs/services/service-map.md`
- `docs/events.md`
- `docs/monitoring.md`

---

## Current Status

Implemented:

- full local Kubernetes stand;
- distributed FastAPI microservices;
- end-to-end video pipeline;
- RTMP → HLS live streaming;
- asynchronous event-driven processing;
- PostgreSQL replication;
- observability stack;
- Docker and Kubernetes environments.

In progress:

- cloud Helm deployment;
- S3-compatible storage backend;
- deployment automation improvements;
- production deployment hardening.

---

## Design Purpose

The project is intended to demonstrate:

- DevOps/SRE engineering practices;
- distributed backend architecture;
- asynchronous processing patterns;
- observability and diagnostics;
- Kubernetes and Helm deployment workflows;
- production-oriented system design.