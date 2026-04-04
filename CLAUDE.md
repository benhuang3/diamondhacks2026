# App Builder - Agentic Workflow

### Phase 1: Plan & Architect (Sequential)
- Use **Plan agent** to decompose the app into backend, frontend, database, and infra layers
- Use **backend-development:architecture-patterns** skill for system design decisions
- Use **backend-development:api-design-principles** skill for API contract design
- Output: implementation plan with file ownership boundaries per agent

### Phase 2: Scaffold & Build (Parallel Agents)
Launch a **team-feature** with these parallel agents:

**Agent A — Backend** (`backend-architect` or `fastapi-pro` / `django-pro`):
- Scaffold API routes, models, and services
- Apply `backend-development:feature-development` skill
- Apply `python-development:python-project-structure` skill
- Apply `python-development:python-error-handling` and `python-development:python-type-safety` skills

**Agent B — Frontend** (`frontend-design:frontend-design` skill):
- Build UI components, pages, and layouts
- Use `javascript-typescript:modern-javascript-patterns` or `typescript-pro` agent
- Generate polished, production-grade interfaces

**Agent C — Database & Config**:
- Schema migrations, seed data
- Use `python-development:python-configuration` skill for env/secrets
- Use `python-development:python-resource-management` skill for connection handling

### Phase 3: Wire & Integrate (Sequential)
- Use `full-stack-orchestration:full-stack-feature` skill to connect frontend ↔ backend ↔ database
- Resolve cross-layer dependencies and API contracts

### Phase 4: Test (Parallel Agents)
Launch parallel review/test agents:

**Agent D — Unit & Integration Tests** (`test-automator`):
- `python-development:python-testing-patterns` or `javascript-typescript:javascript-testing-patterns`
- `backend-development:temporal-python-testing` if workflows exist

**Agent E — Security Audit** (`security-auditor`):
- `full-stack-orchestration:security-auditor` agent
- OWASP Top 10, auth review, input validation

**Agent F — Performance Review** (`performance-engineer`):
- `python-development:python-performance-optimization` skill
- `full-stack-orchestration:performance-engineer` agent

### Phase 5: Deploy (Sequential)
- Use `cloud-infrastructure:terraform-module-library` for infra provisioning
- Use `kubernetes-operations:k8s-manifest-generator` or `kubernetes-operations:helm-chart-scaffolding`
- Use `cloud-infrastructure:deployment-engineer` for CI/CD pipelines
- Use `kubernetes-operations:gitops-workflow` for ArgoCD/Flux setup

### Phase 6: Observe & Harden (Parallel)
- `python-development:python-observability` — logging, metrics, tracing
- `cloud-infrastructure:cost-optimization` — right-size resources
- `kubernetes-operations:k8s-security-policies` — network policies, RBAC
