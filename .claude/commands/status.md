# /project:status — Delta 4C

## Descripción
Dashboard del estado actual del proyecto: issues del cycle activo, % completado, blockers, y próximas prioridades. Todo desde Linear.

## Cuándo usar
Para tener una vista rápida del estado sin iniciar sesión de trabajo. Útil para reuniones, reviews, o cuando querés ver dónde está el proyecto.

## Pasos

### 1. Leer todos los issues activos
```
→ Linear:list_issues(team="Valinor", state="In Progress")
→ Linear:list_issues(team="Valinor", state="Backlog", priority=1)
→ Linear:list_issues(team="Valinor", state="Backlog", priority=2)
→ Linear:list_issues(team="Valinor", state="Done", updatedAt="-P7D")  # últimos 7 días
```

### 2. Leer proyectos activos
```
→ Linear:list_projects(team="Valinor")
```

### 3. Presentar dashboard
```
Formato del output:

═══════════════════════════════════
   VALINOR STATUS — [fecha]
═══════════════════════════════════

🔵 IN PROGRESS ([n])
  VAL-XX  [título]         [prioridad]
  VAL-YY  [título]         [prioridad]

📋 NEXT UP — URGENT/HIGH ([n])
  VAL-ZZ  [título]         [prioridad]
  ...

✅ DONE ESTA SEMANA ([n])
  VAL-AA  [título]

⚠️  BLOCKERS
  [ninguno | descripción]

📊 PROYECTOS
  Valinor Core — Swarm E2E: [status]
  Knowledge Base: [status]
  Gloria — Proving Ground: [status]
═══════════════════════════════════
```

## Notas
- No modifica nada, solo lee
- Si el usuario pide más detalle sobre un issue específico, leer ese issue con Linear:get_issue
