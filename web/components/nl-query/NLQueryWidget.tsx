"use client";

import React, { useState } from "react";

interface NLQueryResult {
  sql: string | null;
  result: Record<string, unknown>[];
  explanation: string | null;
  error: string | null;
  tenant_id: string;
  rows_returned: number;
}

interface NLQueryWidgetProps {
  tenantId: string;
  apiBaseUrl?: string;
  /** Optional entity_map from Cartographer to improve SQL accuracy */
  entityMap?: Record<string, unknown>;
  /** Optional connection string — if provided, results are returned */
  connectionString?: string;
  className?: string;
}

/**
 * NLQueryWidget — VAL-32
 *
 * Ad-hoc natural language query input for Valinor dashboards.
 * Calls POST /api/v1/nl-query and shows the generated SQL + results.
 *
 * This widget is ADDITIVE — it does not replace the standard analysis pipeline.
 * Designed for power users who want to ask custom questions about their data.
 */
export function NLQueryWidget({
  tenantId,
  apiBaseUrl = "/api/v1",
  entityMap,
  connectionString,
  className = "",
}: NLQueryWidgetProps) {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<NLQueryResult | null>(null);
  const [showSql, setShowSql] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || loading) return;

    setLoading(true);
    setResult(null);

    try {
      const response = await fetch(`${apiBaseUrl}/nl-query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: question.trim(),
          tenant_id: tenantId,
          entity_map: entityMap ?? null,
          connection_string: connectionString ?? null,
          max_rows: 50,
        }),
      });

      const data: NLQueryResult = await response.json();

      if (!response.ok) {
        setResult({
          sql: null,
          result: [],
          explanation: null,
          error: (data as unknown as { detail?: string }).detail ?? "Request failed",
          tenant_id: tenantId,
          rows_returned: 0,
        });
        return;
      }

      setResult(data);
    } catch (err) {
      setResult({
        sql: null,
        result: [],
        explanation: null,
        error: err instanceof Error ? err.message : "Unknown error",
        tenant_id: tenantId,
        rows_returned: 0,
      });
    } finally {
      setLoading(false);
    }
  };

  const exampleQuestions = [
    "¿Cuáles son mis 10 clientes con mayor facturación?",
    "¿Cuánto se facturó en el último mes?",
    "¿Qué clientes no han comprado en más de 90 días?",
  ];

  return (
    <div className={`nl-query-widget ${className}`}>
      {/* Header */}
      <div className="nl-query-header">
        <h3>Pregunta en lenguaje natural</h3>
        <p className="nl-query-subtitle">
          Hace preguntas ad-hoc sobre tus datos. Generamos el SQL automáticamente.
        </p>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="nl-query-form">
        <div className="nl-query-input-row">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="¿Cuáles son mis clientes con mayor deuda?"
            className="nl-query-input"
            disabled={loading}
            maxLength={500}
          />
          <button
            type="submit"
            className="nl-query-submit"
            disabled={loading || !question.trim()}
          >
            {loading ? "Generando..." : "Consultar"}
          </button>
        </div>

        {/* Example questions */}
        <div className="nl-query-examples">
          {exampleQuestions.map((q) => (
            <button
              key={q}
              type="button"
              className="nl-query-example-chip"
              onClick={() => setQuestion(q)}
              disabled={loading}
            >
              {q}
            </button>
          ))}
        </div>
      </form>

      {/* Results */}
      {result && (
        <div className="nl-query-result">
          {result.error ? (
            <div className="nl-query-error">
              <strong>Error:</strong> {result.error}
            </div>
          ) : (
            <>
              {/* SQL toggle */}
              {result.sql && (
                <div className="nl-query-sql-section">
                  <button
                    type="button"
                    className="nl-query-sql-toggle"
                    onClick={() => setShowSql(!showSql)}
                  >
                    {showSql ? "Ocultar SQL" : "Ver SQL generado"}
                  </button>
                  {showSql && (
                    <pre className="nl-query-sql-code">{result.sql}</pre>
                  )}
                </div>
              )}

              {/* Explanation */}
              {result.explanation && (
                <p className="nl-query-explanation">{result.explanation}</p>
              )}

              {/* Data table */}
              {result.result.length > 0 && (
                <div className="nl-query-table-wrapper">
                  <p className="nl-query-row-count">
                    {result.rows_returned} filas
                  </p>
                  <div className="nl-query-table-scroll">
                    <table className="nl-query-table">
                      <thead>
                        <tr>
                          {Object.keys(result.result[0]).map((col) => (
                            <th key={col}>{col}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.result.map((row, i) => (
                          <tr key={i}>
                            {Object.values(row).map((val, j) => (
                              <td key={j}>
                                {val === null ? (
                                  <span className="nl-query-null">null</span>
                                ) : (
                                  String(val)
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* No data */}
              {result.sql && result.result.length === 0 && !result.error && (
                <p className="nl-query-no-data">
                  SQL generado correctamente. Para ver resultados, configurá una
                  conexión en el panel de ajustes.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default NLQueryWidget;
