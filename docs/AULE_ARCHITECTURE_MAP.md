# Aulë Architecture Map — Excalidraw

This folder contains an editable Excalidraw architecture map for the proposed Valinor → Aulë product architecture:

- `docs/aule_architecture_map.excalidraw`

## What the diagram covers

The map shows the full product path:

```text
Aulë
  → Business Ontology
  → Business Graph
  → Reportes / Chatbot / Benchmark
  → Event Bus
  → Memory Layer
  → Business Genome
```

It also maps the surrounding application architecture:

- user channels: operator console, client portal, external systems, data sources, and LLM providers;
- product layer: Next.js, auth boundary, FastAPI gateway, API routers, job API, upload service, WebSocket/SSE progress, and Celery workers;
- domain runtime: Aulë orchestrator, compatibility layer, ontology, discovery engine, business graph, knowledge graph, report/chat/benchmark outputs, verification, data-quality gates, and business genome;
- data/event/memory fabric: Redis event bus, domain events, metadata database, artifact store, memory layer, genome store, connectors, SSH tunnel, observability, alerts, and no-raw-data-storage boundary;
- target production services: Route53/CloudFront, WAF, Cognito/Auth0, Secrets Manager, ECS Fargate API/worker, ElastiCache Redis, RDS PostgreSQL, S3, CloudWatch/Sentry, EventBridge/SQS, and VPC private networking.

## How to open it

1. Go to <https://excalidraw.com>.
2. Use **Open** / **Load from file**.
3. Select `docs/aule_architecture_map.excalidraw`.
4. Edit, export PNG/SVG, or share the scene as needed.

## Engineering intent

The diagram is designed as a migration map, not a big-bang rewrite plan:

1. Keep the existing `/api/analyze` flow working.
2. Add an Aulë artifact manifest and trace envelope behind the current pipeline.
3. Promote ontology and graph outputs into first-class versioned artifacts.
4. Route reports, chatbot, and benchmarks through the same Business Graph.
5. Emit domain events into an event bus so the Memory Layer and Business Genome become projections.
6. Move cloud infrastructure toward a production-grade AWS shape only after the product contracts are stable.
