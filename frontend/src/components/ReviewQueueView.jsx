import React, { useState } from 'react';
import { AlertOctagon, CheckCircle2, ExternalLink, ShieldAlert, ArrowRight } from 'lucide-react';

export default function ReviewQueueView({ reviewQueue, onApprove, onSelectRecord }) {
  const [approvingSku, setApprovingSku] = useState(null);

  if (!reviewQueue) return <div className="p-8 text-center text-slate-400">Loading review queue...</div>;

  const items = reviewQueue.review_queue || [];

  const handleApproveClick = async (sku) => {
    setApprovingSku(sku);
    await onApprove(sku);
    setApprovingSku(null);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-rose-400" />
            Human-in-the-Loop Review Queue
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Records requiring manual verification before export to production catalog
          </p>
        </div>
        <span className="badge badge-review text-sm px-3 py-1">
          {items.length} Records Pending Audit
        </span>
      </div>

      {items.length === 0 ? (
        <div className="card p-12 text-center space-y-3">
          <CheckCircle2 className="w-12 h-12 text-emerald-400 mx-auto" />
          <h3 className="text-lg font-bold text-white">Review Queue Clear!</h3>
          <p className="text-sm text-slate-400">All product records pass completeness & source-verification thresholds.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => {
            const sku = item.mfg_part_num;
            const isApproving = approvingSku === sku;

            return (
              <div key={sku} className="card border-l-4 border-l-rose-500 space-y-4">
                <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-700 pb-3">
                  <div>
                    <div className="flex items-center gap-3">
                      <span className="text-lg font-mono font-bold text-rose-400">{sku}</span>
                      <span className="text-xs text-slate-400 font-mono">Row {item.row_index} in Source Dataset</span>
                    </div>
                    <span className="text-xs text-slate-400">Overall Score: <strong className="text-white font-mono">{item.overall_score.toFixed(3)}</strong></span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => onSelectRecord(sku)}
                      className="btn-secondary text-xs py-1.5 px-3"
                    >
                      Audit Provenance
                    </button>
                    <button
                      onClick={() => handleApproveClick(sku)}
                      disabled={isApproving}
                      className="btn-primary text-xs py-1.5 px-3 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500"
                    >
                      {isApproving ? 'Approving...' : '✓ Approve & Resolve'}
                    </button>
                  </div>
                </div>

                {/* Flagged Fields & Reasons Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="bg-rose-950/30 border border-rose-800/40 rounded-xl p-4 space-y-2">
                    <span className="text-xs font-bold text-rose-400 uppercase tracking-wider block flex items-center gap-1.5">
                      <AlertOctagon className="w-4 h-4" />
                      Specific Flag Reasons:
                    </span>
                    <ul className="list-disc list-inside space-y-1 text-xs text-rose-200">
                      {item.flag_reasons.map((reason, idx) => (
                        <li key={idx}>{reason}</li>
                      ))}
                    </ul>
                  </div>

                  <div className="bg-slate-900/60 border border-slate-700/80 rounded-xl p-4 space-y-2">
                    <span className="text-xs font-bold text-slate-300 uppercase tracking-wider block">
                      Flagged Field Names:
                    </span>
                    <div className="flex flex-wrap gap-1.5">
                      {item.flagged_fields.length > 0 ? (
                        item.flagged_fields.map((f) => (
                          <span key={f} className="badge badge-not-found text-xs">
                            {f}
                          </span>
                        ))
                      ) : (
                        <span className="text-xs text-slate-400 italic">None (Flagged due to overall score threshold)</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
