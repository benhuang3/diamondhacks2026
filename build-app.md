# Build App Workflow — Execution Guide
I want to build an app that reviews a digital storefront with 2 functions. It should have a website and Chrome extension.

## Scan
With an agent using Browser Use, it scans the website points out accessiblity and unintuitive UIUX elements. After scanning, using HTML injection through the Chrome extension, these elements are highlighted in the webpage. Another agent also generates a report with scores and visualizations for hwo well each part of the website flows to the app website.


## Find Competitors
With a team of agents and a custom prompt (not necessary), the app scrapes the web for similar storefronts, navigates them using Browser Use, compares prices, sales, deals, discounts, tax, shipping fees, etc between other websites. The agents should attempt to check out similar products to see prices and potentially deals. This then generates a report for biggest competitors, price differences, and potential store and pricing improvements with visualizations.

# Execution Plan


## Phase 1: Plan (uses 1 agent)
```
Agent: Plan (subagent_type=Plan)
→ Outputs: architecture diagram, file tree, API contracts, task decomposition.
→ Creates TODO list with file ownership boundaries
```

## Phase 1.5: Environment (uses 1 agent)
```
Agent: Plan (subagent_type=Plan)
Sets up an .env file, dependencies, API keys, then tests them to make sure they work.
```

### Phase 2: Build (uses 3 parallel agents)
```
Agent A: backend-architect     → src/backend/**
Agent B: frontend-design       → src/frontend/**
Agent C: python-pro            → src/config/**, src/db/**
All run in parallel via team-feature with strict file ownership
```

### Phase 3: Integrate (uses 1 agent)
```
Agent: full-stack-feature skill
→ Wires API calls, env vars, CORS, auth tokens across layers
```

### Phase 4: Test (uses 3 parallel agents)
```
Agent D: test-automator        → tests/**
Agent E: security-auditor      → scans all files
Agent F: performance-engineer  → profiles hot paths
All run in parallel, each writes findings to separate reports
```

### Phase 5: Deploy (uses 1 agent)
```
Agent: deployment-engineer + terraform-specialist
→ Outputs: Dockerfile, K8s manifests or Helm chart, CI/CD pipeline, IaC modules
```

### Phase 6: Harden (uses 2 parallel agents)
```
Agent G: python-observability  → adds logging/metrics/tracing
Agent H: security + cost       → network policies, RBAC, cost tags
```

## Total: up to 8 agents across 6 phases
## Parallelism: Phases 2, 4, and 6 run agents concurrently

## Customization

Add to your prompt to adjust:
- "Skip deploy" → stops after Phase 4
- "Frontend only" → skips backend agent, uses mock API
- "Use Django instead of FastAPI" → swaps Agent A to django-pro
- "Add Temporal workflows" → adds temporal-python-pro agent in Phase 2
- "Monorepo" → adjusts file ownership boundaries accordingly
