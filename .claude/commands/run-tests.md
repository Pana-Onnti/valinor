# /project:run-tests — Delta 4C

## Descripción
Ejecuta la suite de tests de Valinor. Reporta resultados. Si hay fallos, diagnostica y sugiere fix.

## Cuándo usar
Antes de cualquier commit importante. Después de implementar un feature o fix. En cualquier momento que se quiera verificar el estado de la suite.

## Pasos

### 1. Ejecutar suite completa
```
→ Bash: cd /home/nicolas/Documents/delta4/valinor-saas && source venv/bin/activate && pytest tests/ -v --tb=short 2>&1 | tail -50
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
  ...

Causa probable: [diagnóstico]
Fix sugerido: [qué cambiar]
```

### 4. Si hay muchos fallos similares
```
Verificar si hay:
- Import errors (dependencia faltante)
- DB no disponible (docker compose ps)
- Fixtures rotas (conftest.py)
```

### 5. Para correr tests específicos
```
→ Por módulo: pytest tests/test_[módulo].py -v
→ Por keyword: pytest tests/ -k "[keyword]" -v
→ Con cobertura: pytest tests/ --cov=[módulo] --cov-report=term-missing
```

## Notas
- Suite actual: ~2481 tests (puede tardar varios minutos)
- Para pre-commit rápido: `pytest tests/ -x --tb=short` (para en el primer fallo)
- Si la suite tiene >100 fallos: probablemente hay un import error o la DB está caída
- Recordar: NO mockear la DB en integration tests
