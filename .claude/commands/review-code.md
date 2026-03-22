# /project:review-code — Delta 4C

## Descripción
Revisión dual del código: swarm-architect valida arquitectura del pipeline, infra-ops valida seguridad y deploy safety. Genera un reporte con observaciones accionables.

## Cuándo usar
Antes de mergear un branch importante. Después de implementar un feature que toca múltiples capas. Cuando querés un segundo par de ojos sobre el código.

## Pasos

### 1. Identificar qué revisar
```
→ Bash: git diff main...HEAD --name-only
→ Categorizar archivos:
  - core/, api/ → revisar con swarm-architect
  - docker-compose.yml, deploy/ → revisar con infra-ops
  - tests/ → revisar coverage
  - web/ → revisar con criterios de brand (d4c-brand skill)
```

### 2. Revisión de arquitectura (swarm-architect perspective)
```
Verificar:
□ ¿Domain layer está limpio? (no imports de Infrastructure)
□ ¿Los agentes del swarm tienen output tipado (Pydantic)?
□ ¿Hay fallback si un agente falla?
□ ¿El token budget se respeta?
□ ¿Hay logging de progreso?
□ ¿El DataQualityGate corre antes del análisis?
□ ¿El adapter pattern se respeta (no se toca Valinor v0)?
```

### 3. Revisión de infra/seguridad (infra-ops perspective)
```
Verificar:
□ ¿Ninguna credencial hardcodeada en código?
□ ¿Los puertos están correctos (5450, 6380, no 5432/6379)?
□ ¿`localhost` en vez de `host.docker.internal` para DB del cliente?
□ ¿Datos de clientes nunca se persisten?
□ ¿SSH keys nunca se logean?
□ ¿REPEATABLE READ isolation en queries de análisis?
□ ¿Cleanup automático de conexiones SSH?
```

### 4. Verificar tests
```
□ ¿El feature tiene tests?
□ ¿Hay tests de regresión para bugs corregidos?
□ ¿No hay tests duplicados (mismo caso con datos trivialmente distintos)?
```

### 5. Reporte final
```
Formato:

## Code Review — [branch name] — [fecha]

### Arquitectura
✅ OK: [qué está bien]
⚠️  Observaciones:
  - [observación 1] → Fix sugerido: [X]
  - [observación 2] → Fix sugerido: [Y]

### Seguridad / Infra
✅ OK: [qué está bien]
⚠️  Observaciones:
  - [observación]

### Tests
✅ Cobertura OK / ⚠️ Falta coverage en [módulo]

### Veredicto
✅ Listo para merge / ⚠️ Resolver antes de merge:
  - [ ] [acción requerida]
```

## Notas
- El review es sugerencia, no bloqueo — el humano decide si mergear
- Observaciones críticas (seguridad, datos de clientes) son bloqueantes
- Observaciones de estilo/mejora son opcionales
