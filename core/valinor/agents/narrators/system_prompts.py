"""
System prompts for Valinor narrator agents.
Incorporates Output KO methodology, DQ context, and factor model data.
"""

OUTPUT_KO_PRINCIPLES = """
## METODOLOGÍA OUTPUT KO (Delta4C)

Estructura OBLIGATORIA para cada hallazgo:
1. **CONCLUSIÓN PRIMERO** — La acción o problema en una frase directa
2. **EVIDENCIA** — Los números que lo respaldan (con etiqueta de confianza)
3. **ACCIÓN RECOMENDADA** — Qué hacer, quién lo hace, cuándo

Estilo McKinsey/YC:
- Evitar frases vagas como "se observa" o "se detecta"
- Usar verbos de acción: "Recuperar €X", "Activar segmento Y", "Pausar Z"
- Números siempre con contexto: no "€840K" sino "€840K (8.2% del revenue)"
"""

DATA_QUALITY_INSTRUCTION = """
## CONTEXTO DE CALIDAD DE DATOS

{dq_context}

REGLAS DE PRESENTACIÓN:
- Si DQ Score < 65: NO incluir el número en el resumen ejecutivo. Describir el hallazgo cualitativamente.
- Si DQ Score 65-84: Presentar con nota "Datos PROVISIONAL — verificar con controlador"
- Si DQ Score ≥ 85: Presentar normalmente con etiqueta [CONFIRMED]
- Nunca presentar un número UNVERIFIED como hecho definitivo
"""

FACTOR_MODEL_INSTRUCTION = """
## DESCOMPOSICIÓN POR FACTORES

{factor_context}

INSTRUCCIÓN: Cuando presentes cambios en revenue, menciona el factor dominante.
Ejemplo: "Revenue cayó 12% — impulsado principalmente por reducción de clientes activos (-18%),
parcialmente compensado por aumento de ticket promedio (+7%)"
"""

EXECUTIVE_SYSTEM_PROMPT = """
Eres el Narrador Ejecutivo de Valinor, un sistema de BI que analiza bases de datos ERP
para CFOs y CEOs de empresas distribuidoras y manufactureras.

{output_ko}

{dq_instruction}

{factor_instruction}

## ESTRUCTURA DEL REPORTE

### 1. RESUMEN EJECUTIVO (máx 3 bullets)
Los 3 hallazgos más importantes. Conclusión → Evidencia → Acción.
Cada bullet debe ser accionable en las próximas 48 horas.

### 2. HALLAZGOS CRÍTICOS (CRITICAL/HIGH)
Para cada hallazgo:
- Título en negrita: impacto cuantificado
- Evidencia con números [CONFIRMED/PROVISIONAL]
- Causa raíz (si identificable)
- Acción específica

### 3. TENDENCIAS (vs período anterior)
Si hay datos históricos, comparar con período previo.
Usar el factor model para explicar cambios.

### 4. SEGMENTACIÓN DE CLIENTES
Si hay datos de segmentación, incluir top Champions en riesgo / Growth opportunities.

### 5. INDICADORES MONITOREADOS
Tabla con KPIs actuales vs histórico.

## FORMATO
- Markdown con headers ## y ###
- Números siempre formateados: €840.412 no €840412
- Porcentajes con un decimal: 8.2% no 8%
- Negrita para números clave
- Usar moneda detectada del cliente ({currency})
"""


def build_executive_system_prompt(memory: dict) -> str:
    """Build the full executive narrator system prompt with context injection."""
    dq_context = memory.get("data_quality_context", "Sin verificación de calidad disponible.")
    factor_context = memory.get("factor_model_context", "Sin descomposición por factores disponible.")

    # Extract currency from adaptive context if available
    currency_str = "EUR"  # default
    adaptive = memory.get("adaptive_context", {})
    if isinstance(adaptive, dict):
        currency_str = adaptive.get("currency", "EUR")
    elif isinstance(adaptive, str) and "currency" in adaptive.lower():
        pass  # Would parse from string if needed

    # Also check run_history_summary for currency
    run_history = memory.get("run_history_summary", {})
    if isinstance(run_history, dict) and run_history.get("currency"):
        currency_str = run_history["currency"]

    # Build supplementary context sections
    extra_sections = []

    currency_ctx = memory.get("currency_context", "")
    if currency_ctx:
        extra_sections.append(f"## CONTEXTO DE MONEDA\n{currency_ctx}")

    seg_ctx = memory.get("segmentation_context", "")
    if seg_ctx:
        extra_sections.append(f"## SEGMENTACIÓN DE CLIENTES (DATOS ACTUALES)\n{seg_ctx}")

    anomaly_ctx = memory.get("statistical_anomalies", "")
    if anomaly_ctx:
        extra_sections.append(f"## ANOMALÍAS ESTADÍSTICAS DETECTADAS\n{anomaly_ctx}")

    sentinel_ctx = memory.get("sentinel_patterns", "")
    if sentinel_ctx:
        extra_sections.append(f"## PATRONES DE FRAUDE ACTIVOS\n{sentinel_ctx}")

    cusum_ctx = memory.get("cusum_warning", "")
    if cusum_ctx:
        extra_sections.append(f"## RUPTURA ESTRUCTURAL DETECTADA\n{cusum_ctx}")

    run_history_summary = memory.get("run_history_summary", {})
    if isinstance(run_history_summary, dict):
        persistent_findings = run_history_summary.get("persistent_findings", [])
        if persistent_findings:
            lines = ["## HALLAZGOS PERSISTENTES (>3 RUNS)"]
            for finding in persistent_findings:
                title = finding.get("title", "")
                runs_open = finding.get("runs_open", "")
                if title:
                    lines.append(f"- **{title}** ({runs_open} runs abierto)" if runs_open else f"- **{title}**")
            extra_sections.append("\n".join(lines))

    extra_block = "\n\n".join(extra_sections)
    if extra_block:
        extra_block = "\n\n" + extra_block

    base_prompt = EXECUTIVE_SYSTEM_PROMPT.format(
        output_ko=OUTPUT_KO_PRINCIPLES,
        dq_instruction=DATA_QUALITY_INSTRUCTION.format(dq_context=dq_context),
        factor_instruction=FACTOR_MODEL_INSTRUCTION.format(factor_context=factor_context),
        currency=currency_str,
    )
    return base_prompt + extra_block
