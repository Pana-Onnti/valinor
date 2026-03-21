# /project:start-session — Delta 4C

## Descripción
"Git pull cognitivo" — lee el estado actual de Linear y el plan táctico local. Presenta dónde quedamos y qué sigue. SIEMPRE ejecutar al iniciar una sesión de trabajo.

## Cuándo usar
Al comenzar cualquier sesión de trabajo. Sin esto, el agente no sabe el estado actual.

## Pasos

### 1. Leer issues activos de Linear
```
→ Linear:list_issues(assignee=me, state="In Progress")
→ Linear:list_issues(assignee=me, state="Backlog", priority=1)  # Urgent
→ Linear:list_issues(assignee=me, state="Backlog", priority=2)  # High
```

### 2. Leer plan táctico local
```
→ Read .claude/plans/active-plan.md
```

### 3. Presentar estado al usuario
```
Formato del output:

🔵 En progreso:
  - VAL-XX: [título] — [estado breve]
  - VAL-YY: [título] — [estado breve]

📋 Próximo (Urgent/High):
  - VAL-ZZ: [título]

📝 Plan activo:
  [Resumen de active-plan.md — próximos pasos]

¿Retomamos [issue en progreso] o cambiamos de foco?
```

### 4. Si no hay plan activo
```
Preguntar: "No hay plan activo. ¿Qué querés trabajar hoy?"
Sugerir el issue de mayor prioridad.
```

### 5. Si hay plan activo
```
Retomar desde el último checkpoint del plan.
Proponer: "El plan dice que sigue [X]. ¿Arrancamos?"
```

## Notas
- NO modificar nada — solo leer y presentar
- Si Linear está lento, leer active-plan.md primero y mostrar eso mientras carga
- Si el usuario ya sabe qué hacer, /start-session sirve como confirmación rápida
