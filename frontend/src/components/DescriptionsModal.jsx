import React from 'react';
import { X, CheckCircle, AlertTriangle } from 'lucide-react';

export default function DescriptionsModal({ record, onClose }) {
  if (!record) return null;
  const descs = record.descriptions;
  const sku = record.identity.mfg_part_num;

  const descList = [
    { label: 'INVOICE_DESC (<=40 Chars, ALL CAPS)', key: 'invoice_desc', text: descs.invoice_desc, len: descs.invoice_desc.length, max: 40 },
    { label: 'MOBILE_DESC (60-80 Chars)', key: 'mobile_desc', text: descs.mobile_desc, len: descs.mobile_desc.length },
    { label: 'SHORT_DESC (Standard Ecommerce)', key: 'short_desc', text: descs.short_desc, len: descs.short_desc.length },
    { label: 'LONG_DESC1 (Spec Paragraph Comma-Separated)', key: 'long_desc1', text: descs.long_desc1, len: descs.long_desc1.length },
    { label: 'RETAIL_DESC (Storefront Summary)', key: 'retail_desc', text: descs.retail_desc, len: descs.retail_desc.length },
  ];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content space-y-6" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-700 pb-4">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2">
              Generated 5-Format Descriptions — <span className="text-blue-400 font-mono">{sku}</span>
            </h3>
            <p className="text-xs text-slate-400 mt-1">Generated programmatically from single structured record without data leakage</p>
          </div>
          <button onClick={onClose} className="p-1 rounded-lg hover:bg-slate-700 text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Spec Consistency Validation Banner */}
        <div className={`p-4 rounded-xl border flex items-center gap-3 ${descs.consistency_passed ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300' : 'bg-rose-950/40 border-rose-500/40 text-rose-300'}`}>
          {descs.consistency_passed ? (
            <>
              <CheckCircle className="w-5 h-5 flex-shrink-0 text-emerald-400" />
              <span className="text-sm font-semibold">Specification Consistency Passed (Specs match 100% across all 5 formats)</span>
            </>
          ) : (
            <>
              <AlertTriangle className="w-5 h-5 flex-shrink-0 text-rose-400" />
              <span className="text-sm font-semibold">Consistency Check Errors: {descs.consistency_errors.join('; ')}</span>
            </>
          )}
        </div>

        {/* 5 Formats List */}
        <div className="space-y-4">
          {descList.map((d) => (
            <div key={d.key} className="space-y-1.5 bg-slate-900/60 border border-slate-700/80 rounded-xl p-4">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-300 uppercase tracking-wider">{d.label}</span>
                <span className={`text-xs font-mono px-2 py-0.5 rounded ${d.max && d.len > d.max ? 'bg-rose-900/50 text-rose-300' : 'bg-slate-800 text-slate-400'}`}>
                  {d.len} chars {d.max ? `/ max ${d.max}` : ''}
                </span>
              </div>
              <div className="code-block">{d.text}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
