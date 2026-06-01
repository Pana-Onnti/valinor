# Delta 4C — Valinor SaaS

## Karpathy Guidelines (aplicar siempre)
1. **Think Before Coding** — No asumir. Surfacear tradeoffs. Si hay ambiguedad, preguntar antes de implementar.
2. **Simplicity First** — Minimo codigo que resuelve el problema. Nada especulativo ni abstracciones de un solo uso.
3. **Surgical Changes** — Tocar solo lo necesario. No "mejorar" codigo adyacente ni refactorizar lo que no esta roto.
4. **Goal-Driven Execution** — Definir criterios de exito verificables. Loopear hasta verificar.

Ver `.claude/skills/karpathy-guidelines/SKILL.md` para detalle completo.

## Reglas no negociables
1. Conventional commits: `tipo(scope): desc` + `Refs: VAL-XX` obligatorio (hook valida)
2. Domain nunca importa de Infrastructure (hexagonal)
3. Tests antes de commit: `pytest tests/ -v` debe pasar
4. Todo issue se trackea en Linear — no crear tareas sueltas en markdown
5. Un branch = un issue de Linear. NUNCA almacenar datos de clientes.

## Build & Run
```bash
docker compose up -d
python3 scripts/claude_proxy.py &   # OBLIGATORIO en host
pytest tests/ -v
```

## Workflow: Linear → Git → Code → Linear
```
/project:start-session → PICK issue → BRANCH (Linear name) → CODE → COMMIT → /project:end-session
```

## Branching
- `develop` es la rama de integración. Push directo a develop está OK — no hace falta PR.
- `master` es producción. Solo recibe PRs desde develop.
- Al final del sprint: un PR `develop → master` con todo integrado.
- NUNCA push directo a master ni PR de feature branch directo a master.

## Testing
```bash
# Suite RÁPIDA por defecto (~3337 tests, SIN LLM/Gloria — segundos). Los 26 tests
# reales (markers live/mandatory/mssql/discovery_benchmark) se SKIPEAN. (VAL-171)
pytest

# Tests REALES = opt-in con --run-slow (necesitan Gloria PG + claude_proxy levantados;
# sin el flag se skipean, NO se cuelgan):
pytest tests/test_pipeline_production.py --run-slow -v -s   # Gloria PG real, ~6 min
pytest tests/test_pipeline_periods.py    --run-slow -v -s   # SQLite, 3 períodos, ~5 min
pytest --run-slow -v --tb=short                             # suite rápida + los 26 reales
```
Ver `docs/TESTING.md` para guía completa. Skill: "correr test real" → `production-test`.

## Contexto on-demand
| Qué | Dónde |
|-----|-------|
| **Estado vivo verificado + agenda de la etapa nueva** | **`docs/PROJECT_STATE.md`** (empezar acá) |
| Arquitectura técnica | `docs/ARCHITECTURE.md` |
| Deploy producción (Railway + Vercel) | `docs/INFRASTRUCTURE.md` · `docs/DEPLOYMENT.md` |
| Guía de dev, puertos, known issues | `docs/DEVELOPER_GUIDE.md` |
| Domain model (Valar, pipeline, DQ) | `docs/DOMAIN_MODEL.md` |
| Testing & production tests | `docs/TESTING.md` |
| Issues activos | Linear MCP: list_issues |
| Session log, decisiones | Linear Docs: "Session Log — Dev", "Decision Log" |

## Agentes
`.claude/agents/` — swarm-architect, backend-dev, test-writer, infra-ops, agent-engineer, pm-linear

## Commands
`.claude/commands/` — start-session, end-session, status, plan-task, implement-feature, fix-bug, run-tests, review-code

## Skills
`.claude/skills/d4c-linear-workflow/` · `.claude/skills/d4c-brand-skill/` · `.claude/skills/production-test/` · `.claude/skills/karpathy-guidelines/`
