# /project:fix-bug [VAL-XX | descripción] — Delta 4C

## Descripción
Lee el issue de bug, reproduce el problema, diagnostica root cause, implementa fix, testea, commitea. Si no existe el issue, lo crea primero.

## Cuándo usar
Cuando hay un bug reportado, con o sin issue en Linear.

## Pasos

### 1. Crear o leer el issue
```
Si hay VAL-XX:
→ Linear:get_issue(id="VAL-XX")

Si no hay issue:
→ Linear:save_issue(
    title="Bug: [descripción]",
    team="Valinor",
    priority=2,  # High por default para bugs
    labels=["product"]
  )
```

### 2. Reproducir el bug
```
→ Leer los logs relevantes (docker compose logs -f api)
→ Identificar el input que dispara el bug
→ Confirmar que el bug es reproducible
→ Documentar: "El bug ocurre cuando [X] y el resultado es [Y] en vez de [Z]"
```

### 3. Diagnosticar root cause
```
→ Grep el codebase por el error message / función involucrada
→ Read los archivos relevantes
→ Identificar: ¿dónde exactamente falla? ¿por qué?
→ Verificar KNOWN ISSUES en CLAUDE.md — puede estar documentado ya
```

### 4. Fix
```
→ Implementar el fix mínimo necesario
→ NO aprovechar para refactorizar código no relacionado
→ Si el fix requiere cambios en múltiples capas, hacerlos en orden Domain → App → Infra
```

### 5. Testear
```
→ Bash: pytest tests/ -v -k "[test relacionado]"
→ Si no hay test para este bug: crear uno
→ Verificar que el fix no rompe otros tests
```

### 6. Commit y actualizar Linear
```
git commit -m "$(cat <<'EOF'
fix(scope): descripción del bug corregido

Root cause: [qué causaba el bug]
Fix: [qué se cambió]

Refs: VAL-XX
EOF
)"

→ Linear:save_issue(id="VAL-XX", state="Done")
→ Linear:save_comment(issueId="VAL-XX", body="## Fixed\nRoot cause: [X]\nFix: [Y]")
```

## Notas
- Si el bug está en KNOWN ISSUES de CLAUDE.md, actualizar esa sección después del fix
- Si el fix es un workaround (no solución real), documentarlo claramente en el comment de Linear
- Para bugs críticos (producción caída): priorizar fix por encima de tests
