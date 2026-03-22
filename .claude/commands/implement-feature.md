# /project:implement-feature [VAL-XX] — Delta 4C

## Descripción
Lee el issue de Linear, crea branch, ejecuta el trabajo siguiendo Domain → App → Infrastructure, commitea con Refs, y actualiza Linear al terminar.

## Cuándo usar
Cuando se va a implementar un issue de Linear. El issue provee toda la spec.

## Pasos

### 1. Leer el issue completo
```
→ Linear:get_issue(id="VAL-XX")
Extraer:
- Qué construir (spec funcional)
- Qué existe ya (no reconstruir)
- Acceptance criteria (Definition of Done)
- Implementation steps
```

### 2. Crear o verificar branch
```
→ Bash: git branch --show-current
→ Si no estamos en el branch correcto:
   git checkout main && git pull
   git checkout -b [gitBranchName del issue]
```

### 3. Leer contexto técnico necesario
```
→ Read docs/ARCHITECTURE.md (si el feature toca arquitectura)
→ Read docs/DEVELOPER_GUIDE.md (flujo Domain→App→Infra)
→ Read archivos relevantes del codebase
```

### 4. Para trabajo visual/UI: cargar d4c-brand skill
```
→ Read .claude/skills/d4c-brand-skill/SKILL.md
→ Read .claude/skills/d4c-brand-skill/references/components.md
→ Usar tokens T.* para todos los colores, spacing, fonts
```

### 5. Implementar siguiendo Domain → App → Infrastructure
```
Orden:
1. Domain layer (core/, shared/) — entidades, reglas de negocio
2. Application layer (api/) — use cases, adapters
3. Infrastructure layer (docker, config, deploy)
```

### 6. Commit atómico por cambio lógico
```
git commit -m "$(cat <<'EOF'
tipo(scope): descripción corta

Detalle opcional de qué y por qué.

Refs: VAL-XX
EOF
)"
```

### 7. Mover issue en Linear
```
→ Primer commit en el issue:
   Linear:save_issue(id="VAL-XX", state="In Progress")

→ Acceptance criteria cumplidos:
   Linear:save_issue(id="VAL-XX", state="Done")
   Linear:save_comment(issueId="VAL-XX", body="## Done\n[resumen de lo implementado]")
```

### 8. Si se descubre trabajo adicional
```
→ Linear:save_issue(title="...", team="Valinor", ...)
   Crear sub-issue o relacionado, NO expandir el scope del issue actual
```

## Notas
- El issue de Linear ES el prompt — no necesitás más especificación
- Si el issue tiene CHECKPOINTs, mostrar output al usuario en cada uno
- Commits atómicos son obligatorios — no "implementé todo" en un commit
- Refs: VAL-XX es OBLIGATORIO en todos los commits — el hook lo valida
