import React from 'react';
import { AlertTriangle, CheckCircle2, Database, ListChecks, PackageCheck } from 'lucide-react';

const chartColors = ['#2563eb', '#0f766e', '#d97706', '#7c3aed', '#db2777', '#475569'];

export default function OverviewView({ stats, records, onNavigate }) {
  if (!stats) return <div className="empty-state">Loading overview data…</div>;
  const total = stats.total_ingested || 0;
  const categorized = stats.dishwasher_classified || 0;
  const resolved = records.filter((r) => {
    const value = r.manufacturer_info?.real_manufacturer || r.extraction?.real_manufacturer;
    return value && !String(value).toUpperCase().includes('UNRESOLVED');
  }).length;
  const resolvedPct = total ? ((resolved / total) * 100).toFixed(1) : '0.0';
  const categories = Object.entries(stats.category_breakdown || {}).sort((a, b) => b[1] - a[1]);
  const categoryTotal = categories.reduce((sum, [, count]) => sum + count, 0) || 1;
  let cursor = 0;
  const stops = categories.map(([, count], i) => { const start = cursor; cursor += (count / categoryTotal) * 360; return `${chartColors[i % chartColors.length]} ${start}deg ${cursor}deg`; }).join(', ');

  return <section className="overview-page space-y-6">
    <div><h1 className="text-2xl font-bold text-slate-900">Overview</h1><p className="text-sm text-slate-500 mt-1">A live view of the current catalog enrichment run.</p></div>
    <div className="overview-kpis">
      <Kpi icon={Database} label="Total input rows" value={total.toLocaleString()} note="Loaded from the current CSV" />
      <Kpi icon={ListChecks} label="Categorized rows" value={categorized.toLocaleString()} note={`${total ? ((categorized / total) * 100).toFixed(1) : '0.0'}% of input`} />
      <Kpi icon={PackageCheck} label="Manufacturer resolved" value={resolved.toLocaleString()} note={`${resolvedPct}% of input · field-level count, not overall record completeness`} tone="success" />
      <Kpi icon={AlertTriangle} label="Review queue" value={(stats.review_count || 0).toLocaleString()} note="Requires human attention" tone="warning" />
    </div>
    <div className="overview-grid">
      <div className="card category-card"><div className="section-heading"><div><h2>Category breakdown</h2><p>Real classification counts from the current run</p></div></div><div className="category-chart"><div className="donut" style={{ background: `conic-gradient(${stops || '#d0d5dd 0 360deg'})` }}><div className="donut-hole"><strong>{total.toLocaleString()}</strong><span>rows</span></div></div><div className="legend">{categories.slice(0, 8).map(([name, count], i) => <div className="legend-item" key={name}><span className="legend-swatch" style={{ background: chartColors[i % chartColors.length] }} /><span className="legend-name" title={name}>{name}</span><strong>{count}</strong></div>)}</div></div></div>
      <div className="card run-card"><div className="section-heading"><div><h2>Current run</h2><p>Run history is not exposed by the backend yet.</p></div></div><div className="run-empty"><CheckCircle2 className="w-8 h-8"/><strong>Live data only</strong><span>Recent historical runs are intentionally omitted until the API records them.</span><button className="btn-secondary" onClick={() => onNavigate('pipeline')}>Open Pipeline Flow</button></div></div>
    </div>
  </section>;
}

function Kpi({ icon: Icon, label, value, note, tone }) { return <div className={`card kpi-card ${tone || ''}`}><div className="kpi-icon"><Icon className="w-4 h-4"/></div><span className="kpi-label">{label}</span><strong className="kpi-value">{value}</strong><span className="kpi-note">{note}</span></div>; }
