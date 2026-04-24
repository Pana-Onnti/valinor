# Active Plan — Post Bio4 Closure

**Última actualización:** 2026-04-24
**Branch actual:** nicolasbaseggiodev/val-158-sales-v2-dynamic-demo (merged, candidato a cleanup → checkout develop)
**Foco:** sin sprint urgente activo — elegir próximo track

---

## Cerrado — Sprint Bio4 (2026-04-24)

- **VAL-120** Bio4 demo · Done · demo entregada al cliente
- **VAL-141** Sales Report v2 · Done · PR #39 merged
- **VAL-157** sales_v2 queries fix · Done · PR #40 merged a develop
- **VAL-158** Dynamic demo (period picker + PipelineProgress) · Done · PR #41 merged a develop
- **VAL-159** Treasury KO Report prototype · Done
- **VAL-160** Vercel deploy Valinor Chat · Done

---

## Suspendido — Sprint SYSCOP (2026-04-24)

Trabajo parcialmente terminado. `syscop-agent` runner, prefetcher, renderer, mailer, y `.exe` build están Done. Blocker externo (Gerardo) impide avanzar.

| Issue | Estado |
|-------|--------|
| GRO-15 (EPIC) | Backlog · Urgent · due Apr 25 (vencido) |
| VAL-121 (agente Valinor Gerardo) | Backlog · Urgent · due Apr 25 |
| GRO-17 (🚧 BLOCKER creds + OK .exe) | Backlog · Urgent |

**Reactivación:** cuando Gerardo destrabe creds SQL r/o + OK verbal. Primer run planeado era 2026-04-27 06:00 AM.

---

## Activos restantes (sin sprint)

### Paper — arXiv preprint (VAL-142 epic)

| Issue | Status | Priority | Progreso |
|-------|--------|----------|----------|
| VAL-144 | In Progress | High | §2 Related Work drafteada v0.1 en `d4c-paper/sections/02-related.tex` |
| VAL-146 | In Progress | High | §5 Swarm + §6 Output + §8 Case Studies — §5 completa, §6/§8 parcial |
| VAL-147 | In Progress | Medium | §1/§3/§9/§10 drafteadas, falta integración + external review |
| VAL-145 | Backlog | High | §4 Discovery + §7 Eval — requiere empirical eval |
| VAL-142 | Backlog (EPIC) | Medium | tracker general |

**Repo separado:** `d4c-paper/` (no en este workdir).

### Annatar (ANN-1)

- In Progress · Urgent · sin due date
- Roadmap v1.0 técnico — próxima plataforma SaaS de prospección

### Scale / YC

| Issue | Due |
|-------|-----|
| VAL-22 — Load testing + zero-downtime + alerting | Jul 31 |
| GRO-11 — Redactar YC application | Aug 1 |
| VAL-119 — Prompt catalog versioning | May 2 |
| VAL-106 — Externalizar prompts hardcoded | Apr 25 (vencido) |

---

## Housekeeping pendiente

- [ ] `git checkout develop && git pull` — salir de branch VAL-158 merged
- [ ] `git branch -d val-157` y `val-158` (opcional, branches merged)
- [ ] Decidir próximo track y updatear este plan con sprint definido

---

## Próximos tracks posibles

| Track | Por qué arrancar | Por qué esperar |
|-------|------------------|-----------------|
| **Paper (VAL-144/146/147)** | 3 issues In Progress con drafts reales, momentum lineal, sin bloqueos externos. VAL-147 solo falta integración + external review. | Medium priority. No mueve revenue. |
| **Annatar (ANN-1)** | Urgent priority. Nueva línea de producto. | Scope v1.0 grande, sin due. Requiere definir alcance MVP primero. |
| **VAL-106 prompt externalization** | Due vencido (Apr 25). Architecture hardening. | Trabajo incremental, no bloquea nada inmediato. |
| **Esperar outbound SYSCOP/Bio4** | Ambos sprints tienen siguientes pasos comerciales (Loren coordinar). | Sin acción de ingeniería este lado. |

---

## Sesión 2026-04-24 — Closure

- Cerrado VAL-120, VAL-141, VAL-157, VAL-158, VAL-159, VAL-160 (6 issues)
- Merge PR #40 → develop (merge commit `7e1649b4`)
- Merge PR #41 → develop (merge commit `99816309`)
- SYSCOP suspendido: GRO-15, VAL-121, GRO-17 → Backlog con comments explicando hold
- Plan reescrito post-closure
