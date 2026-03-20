# 📋 PLAN DE MIGRACIÓN VALINOR CLI → SAAS

## RESUMEN EJECUTIVO

Migración de Valinor v0 CLI a Valinor v2 SaaS en **5 semanas**, preservando 100% de la funcionalidad actual mientras añadimos capacidades SaaS.

---

## SEMANA 1: PRESERVACIÓN Y SETUP

### Día 1-2: Estructura y Preservación
```bash
# Clonar y setup inicial
cd /home/nicolas/Documents/delta4
cd valinor-saas
./scripts/dev.sh setup
```

**Checklist:**
- [ ] Crear estructura de directorios
- [ ] Copiar código Valinor v0 sin modificar
- [ ] Setup Docker environment
- [ ] Verificar que el código original funciona

### Día 3-4: Adapter Pattern
**Implementar wrapper sin tocar el core:**
- [ ] Crear `ValinorAdapter` en `api/adapters/`
- [ ] Test: adapter ejecuta pipeline original
- [ ] Verificar resultados idénticos a CLI

### Día 5-7: SSH Tunneling
**Seguridad zero-trust:**
- [ ] Implementar `SSHTunnelManager`
- [ ] Test con base de datos real via túnel
- [ ] Validación y audit logging

---

## SEMANA 2: SERVICIOS CORE

### Día 8-9: Sistema de Colas
**Celery para desarrollo, GitHub Actions para producción:**
- [ ] Setup Celery + Redis
- [ ] Crear task para ejecutar análisis
- [ ] Implementar job tracking

### Día 10-11: API Endpoints
**FastAPI básico:**
- [ ] POST /analyze - Iniciar análisis
- [ ] GET /jobs/{id}/status - Status
- [ ] GET /jobs/{id}/results - Resultados
- [ ] Autenticación JWT básica

### Día 12-14: Metadata Storage
**Supabase para metadata (NO datos de clientes):**
- [ ] Crear schemas en Supabase
- [ ] `MetadataStorage` class
- [ ] Integrar en pipeline

---

## SEMANA 3: MIGRACIÓN DE AGENTES

### Día 15-17: Test Individual de Agentes
**Cada agente por separado:**
- [ ] Test Cartographer aislado
- [ ] Test Query Builder
- [ ] Test Analysis Agents (Analyst, Sentinel, Hunter)
- [ ] Test Narrators

### Día 18-19: Fallback Mechanisms
**Resiliencia:**
- [ ] Implementar `PipelineExecutor`
- [ ] Fallback si falla un agente
- [ ] Test con failure scenarios

### Día 20-21: Integration Testing
**E2E completo:**
- [ ] Test: SSH → Pipeline → Results
- [ ] Load test con múltiples análisis
- [ ] Recovery test

---

## SEMANA 4: FRONTEND Y UX

### Día 22-24: Frontend MVP
**Next.js básico:**
- [ ] Setup form para conexión
- [ ] Progress tracking UI
- [ ] Results download

### Día 25-26: Streaming
**Real-time updates:**
- [ ] WebSocket para progreso
- [ ] Server-sent events para logs
- [ ] Integrar en frontend

### Día 27-28: Credential Management
**Upload seguro:**
- [ ] Upload SSH keys
- [ ] Encriptación at rest
- [ ] TTL y cleanup automático

---

## SEMANA 5: DEPLOYMENT

### Día 29-30: Cloudflare Workers
**Zero-cost deployment:**
- [ ] Deploy API a Workers
- [ ] GitHub Actions workflow
- [ ] Test pipeline completo

### Día 31-32: Frontend y Monitoring
**Vercel + Sentry:**
- [ ] Deploy frontend a Vercel
- [ ] Setup Sentry monitoring
- [ ] Test producción E2E

### Día 33-35: Demo y Documentación
**Preparar lanzamiento:**
- [ ] Demo environment
- [ ] Grabar video demo
- [ ] Documentación completa

---

## CHECKPOINTS DE GO/NO-GO

### ✅ Fin Semana 1
- Core preservado funcionando
- SSH tunneling testeado
- **Decisión**: ¿Funcionalidad CLI accesible via HTTP?

### ✅ Fin Semana 2
- Queue system operacional
- API respondiendo
- **Decisión**: ¿Podemos manejar 5 análisis concurrentes?

### ✅ Fin Semana 3
- Agentes migrados
- Calidad de análisis verificada
- **Decisión**: ¿Calidad igual a CLI v0?

### ✅ Fin Semana 4
- Frontend funcional
- UX completa
- **Decisión**: ¿Workflow usuario completo?

### ✅ Fin Semana 5
- Deployment exitoso
- Demo preparado
- **Decisión**: ¿Listo para primer cliente?

---

## ROLLBACK STRATEGY

Cada fase tiene rollback claro:

1. **Semana 1**: Continuar con CLI v0
2. **Semana 2**: API en "dev mode" manual
3. **Semana 3**: Híbrido CLI+API
4. **Semana 4**: API-only sin frontend
5. **Semana 5**: Docker Compose local

---

## COMANDOS ÚTILES

```bash
# Development
cd valinor-saas
./scripts/dev.sh setup          # Setup inicial
./scripts/dev.sh start -d        # Con demo services
./scripts/dev.sh logs api        # Ver logs
./scripts/dev.sh test            # Run tests

# Testing SSH Tunnel
python shared/ssh_tunnel.py test \
  --host client.com \
  --key ~/.ssh/client_key

# Deploy to production
wrangler deploy
vercel --prod
```

---

## SIGUIENTE PASO INMEDIATO

```bash
# Ejecutar ahora mismo:
cd /home/nicolas/Documents/delta4/valinor-saas
./scripts/dev.sh setup
```

Esto iniciará el setup completo del ambiente de desarrollo.

---

*Plan diseñado para preservar 100% funcionalidad mientras añadimos capacidades SaaS*