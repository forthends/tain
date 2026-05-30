# Optimization Backlog

> Generated: 2026-05-27 | Updated: 2026-05-30 | Scope: Tain Agent Framework v0.5.0

## Status Legend
- [ ] Pending
- [~] In Progress
- [x] Done

---

## 1. Architecture & Code Quality

- [x] **1.1 agent.py split** — 1045-line monolith mixes lifecycle, state, config, cognitive loop concerns
- [x] **1.2 PRAL bridge simplification** — CognitiveBridge extension pattern bypasses original cognitive_loop/improvement_loop, creating dual abstraction layers
- [x] **1.3 Message bus upgrade** — File-polling inter-agent communication has latency/reliability issues under load

## 2. Performance

- [x] **2.1 State persistence batching** — Every cycle sync-writes to disk, high I/O during intense evolution
- [x] **2.2 Chat history incremental loading** — Full history loaded each time, degrades as conversations grow
- [x] **2.3 Knowledge content caching** — Server re-renders markdown every request

## 3. Observability

- [x] **3.1 Structured logging** — Replace `print()` statements with leveled logging
- [x] **3.2 Metrics expansion** — Beyond cycle_count/tool_efficacy, add degradation/trend indicators
- [x] **3.3 Alerting mechanism** — Detect and notify when agent is stuck or degraded

## 4. Web UI

- [x] **4.1 Tailwind build step** — Migrate from CDN Play to npm build for `@apply` support and custom themes
- [x] **4.2 Dark mode** — Add theme toggle with system preference detection
- [x] **4.3 Dashboard charts** — Add evolution trend and metric visualization

## 5. Agent Capabilities

- [ ] **5.1 Knowledge vectorization** — Semantic search over agent knowledge files
- [x] **5.2 Web search tool** — Internet access capability for agents (web_search/web_fetch in primal tools)
- [ ] **5.3 MCP integration deepening** — Richer external tool ecosystem

## 6. Reliability

- [ ] **6.1 Agent state recovery** — Crash recovery with consistent state restoration
- [x] **6.2 LLM call retry** — Automatic retry with backoff for transient failures (llm_retry_call in retry.py)
- [x] **6.3 Graceful degradation** — Subsystem failures should not crash the agent (logging + narrowed exceptions)

## 7. Security

- [x] **7.1 Web UI authentication** — Basic auth or API key protection (APIKeyMiddleware)
- [x] **7.2 API rate limiting** — Per-endpoint rate limits (TokenBucket per IP, 60 req/min)

## 8. Testing

- [ ] **8.1 E2E tests** — Browser-based UI testing
- [ ] **8.2 Coverage reporting** — Measure and track test coverage

## 9. Deployment

- [x] **9.1 Containerization** — Docker multi-stage build + docker-compose
- [x] **9.2 API stability** — Version unification (single source: tain_agent.__version__)

## 10. Architecture Cleanup

- [x] **10.1 Dead code removal** — Removed external_world, trial_scheduler, SELF_DEFINE, config.py, agent_runner/context
- [x] **10.2 Circular dependency fix** — ACP → webui dependency broken via ChatEngine extraction
- [x] **10.3 God file split** — dialogue.py (553 lines) → chat.py + streaming.py + conversation_store.py
