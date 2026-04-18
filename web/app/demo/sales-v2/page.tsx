'use client'

/**
 * Demo route for SalesReportV2 — renders the component with realistic
 * Gloria-derived sample data for the Bio4 demo / VAL-120.
 *
 * Refs: VAL-141
 */

import SalesReportV2, { type SalesReportV2Data } from '@/components/ko-report/SalesReportV2'
import { T } from '@/components/d4c/tokens'

const SAMPLE: SalesReportV2Data = {
  client_name: 'Gloria',
  period: '2025-07 → 2026-06',
  currency: 'EUR',
  generated_at: new Date().toISOString(),

  hero_loss_eur: 1315041,
  hero_loss_headline:
    '€1,315,041 de LTV dormido en 12 cuentas que dejaron de comprarte. Si no las llamás esta semana, las perdés definitivamente.',

  next_actions: [
    { priority: 1, title: 'Llamar al top 5 dormantes esta semana',
      rationale: 'LTV combinado €1.1M. Recuperable mínimo €16K en próximos 30 días.',
      impact_eur: 16000, impact_confidence: 'estimated', deadline: 'Esta semana' },
    { priority: 2, title: 'Segmentar Champions en tier A/B/C',
      rationale: '42 Champions concentran 71% del revenue. Caída de la cola = -33% facturación anual.',
      impact_eur: 1100000, impact_confidence: 'estimated', deadline: 'Próximas 2 semanas' },
    { priority: 3, title: 'Automatizar email para "About to Sleep"',
      rationale: '103 clientes en ventana de recuperación de 30 días antes de Hibernating.',
      impact_eur: 24000, impact_confidence: 'estimated', deadline: 'Próximos 30 días' },
  ],

  kpi_bar: [
    { label: 'Clientes activos', value: '959', confidence: 'measured' },
    { label: 'Dormantes', value: '4.620', sub: '> 60 días', confidence: 'measured' },
    { label: 'HHI', value: '1.820', sub: 'moderado', confidence: 'measured' },
    { label: 'CR5', value: '34.2%', sub: 'top 5 clientes', confidence: 'measured' },
    { label: 'Oportunidad', value: '€236K', sub: 'recuperable', confidence: 'estimated' },
  ],

  rfm_segments: [
    { segment: 'champions', count: 42, revenue_share_pct: 28.3, avg_ltv: 54200,
      recommended_action: 'Programa VIP. Contacto del gerente comercial directo.',
      confidence: 'measured' },
    { segment: 'loyal', count: 118, revenue_share_pct: 22.4, avg_ltv: 18900,
      recommended_action: 'Bundle + cross-sell. Renovar con descuentos por volumen.',
      confidence: 'measured' },
    { segment: 'potential_loyalists', count: 93, revenue_share_pct: 12.6, avg_ltv: 9800,
      recommended_action: 'Onboarding comercial. Catálogo expandido.',
      confidence: 'measured' },
    { segment: 'new_customers', count: 47, revenue_share_pct: 3.1, avg_ltv: 2100,
      recommended_action: 'Seguimiento 30 días. Segundo pedido es clave.',
      confidence: 'measured' },
    { segment: 'promising', count: 61, revenue_share_pct: 5.4, avg_ltv: 4200,
      recommended_action: 'Email personalizado + oferta de primer volumen.',
      confidence: 'measured' },
    { segment: 'need_attention', count: 82, revenue_share_pct: 6.8, avg_ltv: 6500,
      recommended_action: 'Call comercial. Verificar por qué bajó la frecuencia.',
      confidence: 'measured' },
    { segment: 'about_to_sleep', count: 103, revenue_share_pct: 4.9, avg_ltv: 3800,
      recommended_action: 'Reactivación con incentivo de reorder.',
      confidence: 'measured' },
    { segment: 'at_risk', count: 88, revenue_share_pct: 8.1, avg_ltv: 7200,
      recommended_action: 'Prioridad alta. Llamada del gerente, no del vendedor.',
      confidence: 'measured' },
    { segment: 'cannot_lose', count: 14, revenue_share_pct: 6.3, avg_ltv: 36100,
      recommended_action: 'Escalamiento C-level. Retención a cualquier costo.',
      confidence: 'measured' },
    { segment: 'hibernating', count: 186, revenue_share_pct: 1.8, avg_ltv: 890,
      recommended_action: 'Campaña email automática. Bajo costo de intento.',
      confidence: 'measured' },
    { segment: 'lost', count: 125, revenue_share_pct: 0.3, avg_ltv: 180,
      recommended_action: 'Archivar. Evaluar churn 12 meses para patrones.',
      confidence: 'measured' },
  ],

  concentration: {
    hhi: 1820.5, hhi_level: 'moderate',
    cr1_pct: 14.8, cr5_pct: 34.2, cr10_pct: 48.6,
    total_customers: 959,
    interpretation:
      'Cartera moderadamente concentrada: si el top 5 se pierde, el impacto es de un tercio del revenue.',
    confidence: 'measured',
  },

  top_customers: [
    { customer_name: 'Distribuidora Central', customer_id: 'BP-0042',
      ltv_eur: 1420000, share_pct: 14.8, last_purchase: '2026-06-25',
      risk: 'low', confidence: 'measured' },
    { customer_name: 'Comercial del Sur', customer_id: 'BP-0019',
      ltv_eur: 890000, share_pct: 9.3, last_purchase: '2026-06-25',
      risk: 'low', confidence: 'measured' },
    { customer_name: 'Mayorista Norte', customer_id: 'BP-0103',
      ltv_eur: 720000, share_pct: 7.5, last_purchase: '2026-05-18',
      risk: 'medium', confidence: 'measured' },
    { customer_name: 'Retail Plus', customer_id: 'BP-0231',
      ltv_eur: 610000, share_pct: 6.4, last_purchase: '2026-06-11',
      risk: 'low', confidence: 'measured' },
    { customer_name: 'Gran Compañía', customer_id: 'BP-0447',
      ltv_eur: 440000, share_pct: 4.6, last_purchase: '2026-04-02',
      risk: 'high', confidence: 'measured' },
    { customer_name: 'Proveeduría Loma', customer_id: 'BP-0512',
      ltv_eur: 380000, share_pct: 4.0, last_purchase: '2026-06-20',
      risk: 'low', confidence: 'measured' },
    { customer_name: 'Agro Distrib.', customer_id: 'BP-0678',
      ltv_eur: 310000, share_pct: 3.2, last_purchase: '2026-03-15',
      risk: 'high', confidence: 'measured' },
  ],

  category_performance: [
    { category: 'Juguetes',      revenue_eur: 312000, share_pct: 31.4, mom_pct: -12, trend: 'baja',    confidence: 'measured' },
    { category: 'Alimentación',  revenue_eur: 222000, share_pct: 22.4, mom_pct:   3, trend: 'estable', confidence: 'measured' },
    { category: 'Aseo personal', revenue_eur:  79000, share_pct:  7.9, mom_pct:  -5, trend: 'baja',    confidence: 'measured' },
    { category: 'Bazar',         revenue_eur:  65000, share_pct:  6.6, mom_pct:   8, trend: 'sube',    confidence: 'measured' },
    { category: 'Electro',       revenue_eur:  54000, share_pct:  5.4, mom_pct: -22, trend: 'caida',   confidence: 'measured' },
    { category: 'Otros',         revenue_eur: 260000, share_pct: 26.3, mom_pct:  -2, trend: 'estable', confidence: 'measured' },
  ],

  magic_matrix: [
    { segment: 'champions', category: 'Alimentación',  penetration_pct: 92, gap_opportunity_eur: 0,     confidence: 'measured' },
    { segment: 'champions', category: 'Juguetes',      penetration_pct: 88, gap_opportunity_eur: 0,     confidence: 'measured' },
    { segment: 'champions', category: 'Bazar',         penetration_pct: 64, gap_opportunity_eur: 14000, confidence: 'estimated' },
    { segment: 'champions', category: 'Aseo personal', penetration_pct: 58, gap_opportunity_eur: 18000, confidence: 'estimated' },
    { segment: 'champions', category: 'Electro',       penetration_pct: 21, gap_opportunity_eur: 26000, confidence: 'estimated' },
    { segment: 'loyal',     category: 'Alimentación',  penetration_pct: 81, gap_opportunity_eur: 5000,  confidence: 'measured' },
    { segment: 'loyal',     category: 'Juguetes',      penetration_pct: 54, gap_opportunity_eur: 12000, confidence: 'estimated' },
    { segment: 'loyal',     category: 'Bazar',         penetration_pct: 38, gap_opportunity_eur: 18000, confidence: 'estimated' },
    { segment: 'loyal',     category: 'Aseo personal', penetration_pct: 29, gap_opportunity_eur: 14000, confidence: 'estimated' },
    { segment: 'loyal',     category: 'Electro',       penetration_pct: 11, gap_opportunity_eur: 22000, confidence: 'estimated' },
    { segment: 'at_risk',   category: 'Alimentación',  penetration_pct: 62, gap_opportunity_eur: 14000, confidence: 'estimated' },
    { segment: 'at_risk',   category: 'Juguetes',      penetration_pct: 45, gap_opportunity_eur: 18000, confidence: 'estimated' },
    { segment: 'at_risk',   category: 'Bazar',         penetration_pct: 12, gap_opportunity_eur:  8000, confidence: 'estimated' },
    { segment: 'at_risk',   category: 'Aseo personal', penetration_pct:  8, gap_opportunity_eur:  9000, confidence: 'estimated' },
    { segment: 'at_risk',   category: 'Electro',       penetration_pct:  3, gap_opportunity_eur: 11000, confidence: 'estimated' },
    { segment: 'hibernating', category: 'Alimentación', penetration_pct: 28, gap_opportunity_eur: 4000,  confidence: 'estimated' },
    { segment: 'hibernating', category: 'Juguetes',     penetration_pct: 18, gap_opportunity_eur: 6000,  confidence: 'estimated' },
    { segment: 'hibernating', category: 'Bazar',        penetration_pct:  7, gap_opportunity_eur: 3000,  confidence: 'estimated' },
    { segment: 'hibernating', category: 'Aseo personal',penetration_pct:  4, gap_opportunity_eur: 4000,  confidence: 'estimated' },
    { segment: 'hibernating', category: 'Electro',      penetration_pct:  1, gap_opportunity_eur: 5000,  confidence: 'estimated' },
  ],

  call_list: [
    { rank: 1, customer_name: 'Gran Compañía', customer_id: 'BP-0447',
      deal_risk_score: 87.3, last_purchase: '2026-04-02', ltv_eur: 440000,
      recovery_potential_eur: 32000, recovery_confidence: 'estimated',
      reason: 'Top 10 histórico, 60+ días sin comprar, frecuencia cayó 70%',
      script_hint: '¿Cambió el responsable de compras? Tenemos el pedido base de tóner armado.' },
    { rank: 2, customer_name: 'Agro Distrib.', customer_id: 'BP-0678',
      deal_risk_score: 81.1, last_purchase: '2026-03-15', ltv_eur: 310000,
      recovery_potential_eur: 24000, recovery_confidence: 'estimated',
      reason: '94 días sin actividad, histórico estacional sugiere reorder en abril',
      script_hint: 'Abril es tu mes fuerte por la siembra — te preparamos el combo habitual.' },
    { rank: 3, customer_name: 'Mayorista Norte', customer_id: 'BP-0103',
      deal_risk_score: 74.8, last_purchase: '2026-05-18', ltv_eur: 720000,
      recovery_potential_eur: 28000, recovery_confidence: 'estimated',
      reason: 'Top 3 por LTV, primera vez >45 días sin pedido en 2 años',
      script_hint: '¿Algún tema con la última entrega? Bajamos el mínimo por única vez.' },
    { rank: 4, customer_name: 'Ferretería La Paz', customer_id: 'BP-0891',
      deal_risk_score: 68.2, last_purchase: '2026-02-28', ltv_eur: 95000,
      recovery_potential_eur: 9200, recovery_confidence: 'estimated',
      reason: 'Categoría Electro con -22% MoM, era comprador regular',
      script_hint: 'Tenemos liquidación de lo que dejaste de comprar, 15% extra.' },
    { rank: 5, customer_name: 'Comercial Andes', customer_id: 'BP-0412',
      deal_risk_score: 62.4, last_purchase: '2026-03-08', ltv_eur: 128000,
      recovery_potential_eur: 11000, recovery_confidence: 'estimated',
      reason: 'Segmento At Risk, 40 días por encima del promedio',
      script_hint: 'Nueva línea de aseo personal — especialmente pensada para retail B2B.' },
  ],

  executive_summary:
    'Cartera con concentración moderada (HHI 1.820, top 5 = 34%). ' +
    '3 clientes críticos (€1.47M LTV combinado) fuera de ciclo > 45 días — acción esta semana. ' +
    'Magic Matrix detecta €236K de gap en cross-sell dentro de los segmentos Loyal y Champions. ' +
    'Categoría Electro cae -22% MoM y arrastra el segmento At Risk.',

  data_caveats: [
    'Period covers 12 months rolling. Data freshness: última carga 2026-06-27.',
    'Magic Matrix penetration % se calcula sobre categorías compradas ≥1 vez en el período.',
  ],
}

export default function SalesV2DemoPage() {
  return (
    <div style={{ background: T.bg.primary, minHeight: '100vh' }}>
      <div style={{
        maxWidth: 1100, margin: '0 auto',
        fontFamily: T.font.display,
      }}>
        <SalesReportV2 report={SAMPLE} />
      </div>
    </div>
  )
}
