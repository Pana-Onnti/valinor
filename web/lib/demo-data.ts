/**
 * demo-data.ts — Datos curados de hallazgos Gloria para el demo público.
 * Basado en patrones reales de PyMEs argentinas.
 * No contiene datos de clientes reales.
 */

export interface DemoFinding {
  id: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
  category: string
  headline: string
  description: string
  eurValue: number
  action: string
  icon: string // unicode symbol
}

export interface DemoStats {
  entitiesFound: number
  patternsDetected: number
  riskValue: number
  analysisTime: string
}

export const DEMO_STATS: DemoStats = {
  entitiesFound: 253,
  patternsDetected: 18,
  riskValue: 847_320,
  analysisTime: '14 min 32 seg',
}

export const DEMO_FINDINGS: DemoFinding[] = [
  {
    id: 'f1',
    severity: 'CRITICAL',
    category: 'Concentracion de ingresos',
    headline: '3 clientes generan el 61% de la facturacion',
    description:
      'Los clientes DISTRIBUIDORA NORTE SRL, GRUPO ANDINO SA y COMERCIAL DEL SUR concentran EUR 512.400 del total facturado. La perdida de cualquiera de ellos impactaria mas del 20% del revenue anual.',
    eurValue: 512_400,
    action: 'Diversificar cartera: plan de captacion para reducir dependencia bajo 40%',
    icon: '\u26A0',
  },
  {
    id: 'f2',
    severity: 'HIGH',
    category: 'Clientes dormidos',
    headline: '47 clientes sin actividad en los ultimos 6 meses',
    description:
      'Facturacion historica acumulada de EUR 189.700 en clientes que dejaron de comprar. Patron comun: ultima compra coincide con aumento de precios de Q3 2025.',
    eurValue: 189_700,
    action: 'Campana de reactivacion segmentada por ultimo monto de compra',
    icon: '\u23F8',
  },
  {
    id: 'f3',
    severity: 'HIGH',
    category: 'Envejecimiento de cartera',
    headline: 'EUR 134.200 en facturas vencidas a mas de 90 dias',
    description:
      '22 facturas de 14 clientes distintos superan los 90 dias de mora. 3 de ellas (EUR 47.800) corresponden a un unico cliente con patron de pago deteriorado desde octubre 2025.',
    eurValue: 134_200,
    action: 'Escalar cobranza: gestion prejudicial para facturas >90 dias',
    icon: '\u23F1',
  },
  {
    id: 'f4',
    severity: 'MEDIUM',
    category: 'Erosion de margen',
    headline: 'Descuentos promedio subieron de 8% a 14% en 6 meses',
    description:
      'Se detecta un incremento sostenido de descuentos otorgados. El impacto estimado es EUR 67.500 en margen perdido. Los vendedores con mayor crecimiento de descuentos: Rodriguez (18%), Gomez (16%).',
    eurValue: 67_500,
    action: 'Revisar politica de descuentos y establecer topes por vendedor',
    icon: '\u2193',
  },
  {
    id: 'f5',
    severity: 'MEDIUM',
    category: 'Oportunidad de cross-sell',
    headline: '38 clientes compran solo 1 linea de producto',
    description:
      'Clientes con ticket promedio >EUR 2.000/mes que solo compran una categoria. Potencial de cross-sell estimado en EUR 94.800 anuales basado en patron de clientes similares.',
    eurValue: 94_800,
    action: 'Programa de cross-sell con recomendaciones por perfil de cliente',
    icon: '\u2197',
  },
  {
    id: 'f6',
    severity: 'LOW',
    category: 'Estacionalidad',
    headline: 'Caida predecible del 23% en facturacion entre enero y marzo',
    description:
      'Patron estacional consistente en los ultimos 3 anos. Los clientes del segmento retail reducen pedidos un 23% en Q1. Oportunidad de aplanar con promociones anticipadas.',
    eurValue: 38_400,
    action: 'Plan comercial Q1 con incentivos de volumen para clientes retail',
    icon: '\u223F',
  },
]

/** Loading sequence steps */
export const LOADING_STEPS = [
  { text: 'Conectando agentes de analisis...', duration: 800 },
  { text: 'Cartografo analizando estructura de datos...', duration: 1000 },
  { text: '253 entidades encontradas', duration: 600 },
  { text: 'Analizando patrones de riesgo...', duration: 900 },
  { text: 'Generando hallazgos ejecutivos...', duration: 700 },
]
