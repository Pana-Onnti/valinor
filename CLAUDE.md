# Delta 4C — Valinor SaaS

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

## Branching (no negociable)
- `develop` es la rama de integración. TODO el código va a develop primero.
- `master` es producción. Solo recibe PRs desde develop.
- Feature branches (incluyendo worktrees de agentes): siempre PR con `--base develop`.
- Al final del sprint: un PR `develop → master` con todo integrado.
- NUNCA hacer PR de feature branch directo a master.

## Contexto on-demand
| Qué | Dónde |
|-----|-------|
| Arquitectura técnica | `docs/ARCHITECTURE.md` |
| Guía de dev, puertos, known issues | `docs/DEVELOPER_GUIDE.md` |
| Domain model (Valar, pipeline, DQ) | `docs/DOMAIN_MODEL.md` |
| Issues activos | Linear MCP: list_issues |
| Session log, decisiones | Linear Docs: "Session Log — Dev", "Decision Log" |

## Agentes
`.claude/agents/` — swarm-architect, backend-dev, test-writer, infra-ops, agent-engineer, pm-linear

## Commands
`.claude/commands/` — start-session, end-session, status, plan-task, implement-feature, fix-bug, run-tests, review-code

## Skills
`.claude/skills/d4c-linear-workflow/` · `.claude/skills/d4c-brand-skill/`
