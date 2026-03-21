# /project:plan-task [descripción] — Delta 4C

## Descripción
Investiga el codebase, define el scope, y crea un issue bien estructurado en Linear. El issue ES la spec. No crea archivos markdown.

## Cuándo usar
Cuando hay trabajo nuevo que hacer y no existe issue en Linear. Antes de empezar a codear, siempre crear el issue primero.

## Pasos

### 1. Entender la tarea
```
Si el usuario pasó descripción corta → preguntar si hay más contexto.
Si ya hay suficiente info → continuar.
```

### 2. Investigar el codebase
```
→ Grep/Glob para encontrar código relacionado
→ Read los archivos relevantes
→ Identificar: qué existe, qué falta, qué hay que cambiar
```

### 3. Verificar que no existe issue duplicado
```
→ Linear:list_issues(query="[palabras clave de la tarea]")
→ Si existe: no crear duplicado, trabajar sobre el existente
```

### 4. Definir el issue
```
Estructura:
- Title: [tipo] + [qué se hace] en 1 línea
- Objetivo: 2-3 oraciones
- Contexto: background técnico y de negocio
- Scope: Incluido / Excluido
- Acceptance Criteria: checkboxes verificables
- Implementation Steps: Fase 1, Fase 2, CHECKPOINTs
- Git: branch name + tipo de commit
```

### 5. Crear issue en Linear
```
→ Linear:save_issue(
    title="[título]",
    team="Valinor",
    project="Valinor Core — Swarm E2E",
    priority=[1-4],
    labels=["product"|"infra"|"gtm"],
    description="[descripción completa en markdown]",
    parentId="[VAL-9 u otro epic si aplica]"
  )
```

### 6. Confirmar al usuario
```
"Issue creado: VAL-XX — [título]
URL: [url]
Prioridad: [prioridad]
¿Arrancamos ahora o lo dejamos para después?"
```

## Notas
- Labels disponibles: product, infra, gtm
- Si es un sub-issue de un epic, siempre setear parentId
- La prioridad la sugiere el agente basado en urgencia, pero el usuario puede overridear
- NO crear tareas sueltas en markdown — todo en Linear
