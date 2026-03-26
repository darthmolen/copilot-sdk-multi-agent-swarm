# Deployment: Container Image + Azure Container Apps

## Context

The system runs locally via VS Code tasks. For team/production use, it needs to be containerized and deployed to Azure Container Apps (ACA). This includes building a Docker image, configuring ACA with environment variables, and handling the Copilot CLI dependency.

## Phase 1: Dockerfile

### Multi-stage build

```dockerfile
# Stage 1: Build frontend
FROM node:20-slim AS frontend-build
WORKDIR /app/src/frontend
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

# Stage 2: Python backend + static frontend
FROM python:3.12-slim
WORKDIR /app

# Install Copilot CLI
# TODO: Copilot CLI binary needs to be available in the container.
# Options:
#   1. Pre-install via npm: RUN npm install -g @github/copilot
#   2. Mount as volume at runtime
#   3. Download binary in entrypoint script
# This is the key dependency question — Copilot CLI requires authentication
# and may need a persistent session token.

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY src/backend/ src/backend/
COPY src/templates/ src/templates/
COPY --from=frontend-build /app/src/frontend/dist/ src/frontend/dist/

# Serve frontend static files from FastAPI (or nginx sidecar)
EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "src"]
```

### Open questions for Phase 1

- **Copilot CLI auth in container**: The CLI needs `copilot auth login` or a token. How does this work in a headless container? Options:
  - Mount a pre-authenticated token via volume/secret
  - Use a service account token via environment variable
  - Run `copilot auth login --token $COPILOT_TOKEN` in entrypoint
- **Frontend serving**: Options:
  - Serve built static files from FastAPI via `StaticFiles` middleware
  - Use nginx sidecar container in ACA
  - Separate frontend container behind Azure Front Door

## Phase 2: Azure Container Apps Deployment

### Infrastructure

```
Azure Container Apps Environment
├── Container App: swarm-api
│   ├── Image: ghcr.io/<org>/copilot-swarm:latest
│   ├── Ingress: external, port 8000
│   ├── Min replicas: 1 (WS connections require persistent instances)
│   ├── Max replicas: 3
│   └── Secrets:
│       ├── SWARM_API_KEY
│       ├── COPILOT_TOKEN (Copilot CLI auth)
│       └── ENVIRONMENT=production
└── (Optional) Container App: swarm-frontend
    ├── Image: nginx with built frontend
    └── Ingress: external, port 80
```

### ACA Configuration

```yaml
# aca-deploy.yaml (Bicep or ARM template)
resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: 'copilot-swarm'
  properties:
    configuration:
      ingress:
        external: true
        targetPort: 8000
        transport: 'http'  # ACA handles TLS termination
      secrets:
        - name: 'swarm-api-key'
          value: '<from-keyvault>'
        - name: 'copilot-token'
          value: '<from-keyvault>'
    template:
      containers:
        - name: 'swarm'
          image: 'ghcr.io/<org>/copilot-swarm:latest'
          env:
            - name: 'ENVIRONMENT'
              value: 'production'
            - name: 'SWARM_API_KEY'
              secretRef: 'swarm-api-key'
            - name: 'COPILOT_TOKEN'
              secretRef: 'copilot-token'
          resources:
            cpu: 2.0
            memory: '4Gi'
}
```

### Key considerations

- **WebSocket support**: ACA supports WebSockets natively. Session affinity may be needed if scaling beyond 1 replica (WS connections are stateful).
- **Min replicas = 1**: Scale-to-zero breaks WS connections. Keep at least 1 warm instance.
- **Copilot CLI subprocess**: Each swarm spawns Copilot CLI processes. Container needs enough CPU/memory for concurrent agent sessions (each ~200MB).
- **Work directory persistence**: `workdir/` is ephemeral in containers. Options:
  - Azure Files mounted volume for persistent output
  - Write to Azure Blob Storage instead of local filesystem
  - Accept ephemeral (output lives only during swarm run + report)
- **Logging**: structlog JSON goes to stdout → ACA captures in Log Analytics automatically.

## Phase 3: CI/CD

### GitHub Actions workflow

```yaml
on:
  push:
    branches: [main]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:${{ github.sha }}
      - name: Deploy to ACA
        uses: azure/container-apps-deploy-action@v1
        with:
          containerAppName: copilot-swarm
          imageToDeploy: ghcr.io/${{ github.repository }}:${{ github.sha }}
```

## Implementation Order

1. **Dockerfile** — Get the image building and running locally via `docker compose`
2. **Static frontend serving** — Add `StaticFiles` middleware to FastAPI for the built frontend
3. **ACA deployment** — Bicep template + GitHub Actions
4. **Copilot CLI auth** — Solve the headless auth problem (may require GitHub collaboration)
5. **Work directory persistence** — Azure Files or Blob Storage integration

## Risks

- **Copilot CLI headless auth** is the biggest unknown. The CLI may not support non-interactive auth in a container. This could block the entire deployment unless GitHub provides a service token mechanism.
- **WebSocket scaling**: Multiple replicas need sticky sessions or a shared state layer (Redis) for WS connection management. Start with 1 replica.
- **Cost**: Each swarm spawns 4-6 Copilot CLI processes that consume tokens. No guardrails yet (see `planning/backlog/guardrails.md`). ACA compute cost is secondary to Copilot API cost.
