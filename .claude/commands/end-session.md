# /project:end-session — Delta 4C

## Descripción
"Git push cognitivo" — guarda el progreso de la sesión en Linear (session log, comments, estados) y actualiza el plan táctico local. SIEMPRE ejecutar al terminar. Sin esto, el progreso se pierde.

## Cuándo usar
Al terminar una sesión de trabajo, antes de cerrar Claude Code.

## Pasos

### 1. Generar resumen de sesión
```
Compilar:
- Qué issues se trabajaron (VAL-XX, VAL-YY)
- Qué se hizo en cada uno (commits, features, bugs fixed)
- Decisiones técnicas importantes tomadas
- Qué quedó pendiente / próximos pasos
- Blockers encontrados (si los hay)
```

### 2. Actualizar comments en issues trabajados
```
→ Para cada issue trabajado:
   Linear:save_comment(issueId=VAL-XX, body="## Progreso [fecha]\n[resumen de lo hecho]")
```

### 3. Mover issues completados
```
→ Si se cumplieron TODOS los acceptance criteria del issue:
   Linear:save_issue(id=VAL-XX, state="Done")
→ Si se avanzó pero no está completo: dejar en "In Progress"
```

### 4. Actualizar Session Log en Linear
```
→ Linear:update_document(doc="Session Log — Dev", content=append)
   Formato de entrada:
   ## YYYY-MM-DD | [Tema principal]
   Duration: ~Xh
   Issues worked: VAL-XX, VAL-YY

   ### What happened
   - [bullet 1]
   - [bullet 2]

   ### Decisions
   - [decisión + razonamiento, si hubo]

   ### Next
   - [próximos pasos]

   ### Blockers
   - [nada | descripción del blocker]
   ---
```

### 5. Si hubo decisiones técnicas importantes
```
→ Linear:update_document(doc="Decision Log", content=append)
   Formato:
   ## YYYY-MM-DD — [Título de la decisión]
   **Decisión:** [qué se decidió]
   **Razón:** [por qué]
   **Alternativas descartadas:** [qué más se consideró]
   **Consecuencias:** [trade-offs]
   ---
```

### 6. Actualizar plan táctico local
```
→ Write .claude/plans/active-plan.md
   Actualizar:
   - ✅ lo que se completó
   - 🔄 lo que quedó en progreso
   - ⏳ lo que sigue
   - Próximos pasos concretos
```

### 7. Verificar git
```
→ Bash: git status
→ Confirmar que todos los commits tienen Refs: VAL-XX
→ Si hay commits sin push: recordar al usuario que pushee
```

## Notas
- Ser específico en los comentarios de Linear — no solo "se avanzó", sino QUÉ se hizo
- Si la sesión fue corta (< 30min), un comment breve alcanza
- El session log en Linear es para el equipo (Nico, Pedro, Lorenzo) — escribir en español o inglés según el tono habitual
