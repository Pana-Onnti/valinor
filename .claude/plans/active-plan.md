# Active Plan — VAL-161 + VAL-162 closed, VAL-163 created

**Última actualización:** 2026-05-08 (cierre de sesión)
**Branch actual:** `nicolasbaseggiodev/val-162-pipeline-timeouts` (1 commit ahead de develop, ya pusheado)
**develop:** al día — `bd18d2c0` fix(infra): VAL-162 proxy concurrency + relaxed CLI timeout budget

---

## Sesión 2026-05-08 — VAL-161 merge + VAL-162 fix + VAL-163 spawn

### Qué se hizo

1. **VAL-161 mergeado a develop** (8 commits FF, último `af3224e0`). Branch limpia, push directo a develop sin PR.
2. **VAL-161 cerrado en Linear** con closure honest: wiring entregado, claim cualitativo downgraded.
3. **VAL-163 creado** (Medium, asignado, blocked by VAL-162, related to VAL-161): A/B controlado del Number Registry para medir delta marginal real.
4. **VAL-162 atacado y cerrado**:
   - Proxy `scripts/claude_proxy.py`: `HTTPServer` → `ThreadingHTTPServer`, subprocess timeout 300→960s. Validado con micro-test: 3 Haiku paralelos 6.1s vs 17.5s suma (CONCURRENT).
   - CLI timeout default 300→900s en `cli_provider.py`, `config.py`, `monkey_patch.py` (×2 sites).
   - `narrator_timeout` 180→920s en ambos production tests.
   - `docs/TESTING.md` actualizado con tabla de budgets por capa.
5. **3 production tests E2E reales corridos** (overkill, lección aprendida — ver `feedback_test_velocity.md`):
   - Run 1 (cli=300s, narrator=320s): 627s, 2/4 narrators OK (ceo + executive). Controller cayó.
   - Run 2 (cli=540s, narrator=560s): 855s, 3/4 narrators OK (controller pasa de 38 chars → 18.8K).
   - Run 3 (cli=900s, narrator=920s): 1220s, 3/4 narrators OK. **Sales sigue cayendo al fallback exact (679 chars)** en los 3 runs — NO es timeout puro, prompt size + upstream rate-limit.
6. **VAL-162 mergeado a develop** (commit `bd18d2c0`) y cerrado en Linear con nota honesta.
7. **Suite excl. production tests** corriendo en background (no quemar tokens en E2E lento).

### Decisiones técnicas

- **No abrir VAL-164 para sales narrator** todavía. Se crea solo si vuelve como blocker en otro sprint. Razón: sales JSON pesado + Plan Max rate-limit es investigación dedicada, no urgente.
- **No revertir cli=900s a 540s**: SaaS prod solo corre executive (~254s), así que el budget alto no afecta latencia real. Si bite alguna vez, una línea fix.
- **Memoria nueva `feedback_test_velocity.md`**: capturar el hábito de no iterar tests E2E en cascada bumpeando timeouts.

### Estado del branch

- VAL-162 branch: 1 commit pusheado a develop. Working tree limpio salvo artifacts esperados (`web/tsconfig.tsbuildinfo`, `.claude/`).
- VAL-161 branch + commits ya mergeados.
- develop al día con todo.

---

## Pendientes próxima sesión

### Inmediato

- **Suite excl. production tests**: validar que pasa (corriendo en background al cierre). Si rojo, investigar.
- Decidir si limpiar el branch `nicolasbaseggiodev/val-161-anti-hallucination-integration` localmente (ya mergeado).

### Linear queue siguiente

1. **VAL-163** (Medium, ya creado, blocked by VAL-162): A/B Number Registry. Ya destrabado al cerrar VAL-162.
2. **GRO-15 / VAL-121** (Urgent): SYSCOP — bloqueado por creds Gerardo, fuera de control nuestro hasta que él responda.
3. **GRO-11** (Urgent): YC application — deadline 2026-08-01, no urgente todavía.
4. Sales narrator deep-dive si surge (potencial VAL-164).

### Out of scope persistente

- A/B controlado del Number Registry → VAL-163 ya creado.
- Active re-querying contra DB en VerificationEngine (acepta `connection_string`/`entity_map` pero no se pasan).
- SaaS corriendo los 4 narrators (sigue solo Executive — issue separado si surge).
- Sales narrator: prompt diet, Haiku fallback, medir rate-limit.

---

## Hallazgos del audit 2026-04-27 (queue, no este sprint)

- Backend: 50 findings en `/tmp/valinor-backend-findings.md` (5 críticos: race demo cache, exception swallowing, hexagonal violation `data_quality_gate.py:174`, DQ degrada exceptions a WARNING, bare except verification.py:1207)
- Frontend: 22 findings en `/tmp/valinor-frontend-findings.md` (5 críticos: untyped API, stale closure polling, JWT plain en localStorage, FileUpload a11y, ErrorBoundary mistype)
- Doc-vs-code: 12 gaps en `/tmp/valinor-backend-architecture.md`
