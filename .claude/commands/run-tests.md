# /project:run-tests — Delta 4C

## Descripción
Ejecuta la suite de tests de Valinor. Soporta 3 niveles: rápido, completo, y producción.

## Cuándo usar
Antes de cualquier commit. Después de implementar un feature o fix. Para evaluar el estado del producto.

## Pasos

### 1. Elegir nivel

**Rápido (stages deterministas, <1s):**
```
→ Bash: pytest tests/test_pipeline_gloria_e2e.py::TestGloriaPipelineStages -v
```

**Suite completa (~3000 tests, varios minutos):**
```
→ Bash: source venv/bin/activate && pytest tests/ -v --tb=short 2>&1 | tail -50
```

**Producción — agentes y narrators REALES contra Gloria PostgreSQL (~6 min):**
```
→ Prerequisitos: Gloria PG en localhost:5432 + proxy/CLI Claude
→ Bash: source venv/bin/activate && pytest tests/test_pipeline_production.py -v -s
→ Output: tests/output/production/ (JSON + reportes markdown)
```

**Por período (1 mes, 1 trimestre, 1 año, ~5 min):**
```
→ Bash: source venv/bin/activate && pytest tests/test_pipeline_periods.py -v -s
```

### 2. Si hay fallos — diagnosticar
```
→ Leer el traceback completo del fallo
→ Identificar: ¿es el código o el test que está mal?
→ Bash: pytest tests/[archivo_fallido.py] -v --tb=long
```

### 3. Reportar resultado
```
Formato:

✅ Suite OK — [N] passed en [X]s
  O
❌ Suite FAIL — [N] passed, [M] failed, [K] errors

Fallos:
  tests/[archivo.py]::[test_name] — [descripción del error]

Causa probable: [diagnóstico]
Fix sugerido: [qué cambiar]
```

### 4. Para el test de producción, además reportar:
```
📊 Pipeline Production:
  DQ Score: [N]/100
  Queries: [N]/8 succeeded
  Revenue: €[N]
  Agents: [N]/3 — [N] findings
  Reports: [N]/4 generated
  Output: tests/output/production/[file].json
```

## Notas
- Suite actual: ~3000 tests
- Para pre-commit rápido: `pytest tests/ -x --tb=short`
- Test producción necesita: Gloria PG + Claude CLI/proxy
- NO mockear la DB en integration tests
- Ver `docs/TESTING.md` para guía completa
