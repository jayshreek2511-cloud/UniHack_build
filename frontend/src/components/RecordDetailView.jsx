import React from 'react';
import { ArrowLeft, ExternalLink, ShieldCheck, CheckCircle2, AlertTriangle, Info } from 'lucide-react';

export default function RecordDetailView({ record, onBack }) {
  if (!record) return <div className="p-8 text-center text-slate-400">Select a record to inspect detail</div>;

  const sku = record.identity.mfg_part_num;
  const prov = record.provenance.field_provenance || {};
  const attrs = record.extraction.attributes || {};
  const mfrInfo = record.manufacturer_info || {};

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button onClick={onBack} className="btn-secondary text-xs py-1.5 px-3">
          <ArrowLeft className="w-4 h-4" /> Back to Catalog
        </button>
        <span className="text-xs text-slate-400 font-mono">Record ID: {sku}</span>
      </div>

      {/* Record Identity Banner */}
      <div className="card space-y-4">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-700 pb-4">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-mono font-bold text-white">{sku}</h2>
              {record.review_status === 'complete' && <span className="badge badge-complete">Complete</span>}
              {record.review_status === 'approved' && <span className="badge badge-approved">Approved</span>}
              {record.review_status === 'needs_review' && <span className="badge badge-review">Needs Review</span>}
            </div>
            <p className="text-sm text-slate-400 mt-1">{record.identity.part_desc}</p>
          </div>

          <div className="text-right">
            <span className="text-xs font-semibold text-slate-400 block uppercase">Overall Confidence</span>
            <span className="text-3xl font-bold font-mono text-emerald-400">
              {record.confidence_score.overall_score.toFixed(3)}
            </span>
          </div>
        </div>

        {/* Identity Metadata Grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
          <div>
            <span className="text-slate-400 block">Raw Distributor Part_Manuf:</span>
            <span className="font-semibold text-slate-200">{record.identity.part_manuf || 'N/A'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Normalized Manufacturer:</span>
            <span className="font-semibold text-slate-200">{mfrInfo.real_manufacturer || 'N/A'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">Normalized Brand:</span>
            <span className="font-semibold text-slate-200">{mfrInfo.real_brand || 'N/A'}</span>
          </div>
          <div>
            <span className="text-slate-400 block">MFR Source URL:</span>
            {mfrInfo.mfr_url ? (
              <a href={mfrInfo.mfr_url} target="_blank" rel="noreferrer" className="text-cyan-400 hover:underline inline-flex items-center gap-1">
                <ExternalLink className="w-3 h-3" />
                <span className="truncate max-w-[140px]">{mfrInfo.mfr_url}</span>
              </a>
            ) : (
              <span className="text-rose-400 font-semibold">Not Verified (403)</span>
            )}
          </div>
        </div>
      </div>

      {/* Field-Level Provenance Audit Matrix */}
      <div className="card space-y-4">
        <div>
          <h3 className="text-lg font-bold text-white flex items-center gap-2">
            <ShieldCheck className="w-5 h-5 text-emerald-400" />
            Field-Level Provenance & Lineage Audit Matrix
          </h3>
          <p className="text-xs text-slate-400 mt-1">
            Complete lineage tracing where every value came from (Part_Desc text / LLM inference / manufacturer URL / not-found)
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Attribute Name</th>
                <th>Extracted Value</th>
                <th>Confidence Tag</th>
                <th>Source Lineage</th>
                <th>Source Link</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(prov).map(([fname, pentry]) => {
                let confTag = attrs[fname]?.confidence_source;
                if (!confTag) {
                  if (fname === 'Manufacturer URL') {
                    confTag = mfrInfo.verification_status;
                  } else if (fname === 'Manufacturer Name') {
                    confTag = mfrInfo.real_manufacturer && mfrInfo.real_manufacturer !== 'Unknown' ? 'source-verified' : 'not-found';
                  } else {
                    confTag = pentry.value !== null && pentry.value !== undefined && String(pentry.value).trim() !== '' ? 'source-verified' : 'not-found';
                  }
                }

                return (
                  <tr key={fname}>
                    <td className="font-semibold text-white">{fname}</td>
                    <td className="font-mono text-slate-200">
                      {pentry.value !== null && pentry.value !== undefined ? (
                        <span>{pentry.value}</span>
                      ) : (
                        <span className="text-slate-500 italic">None</span>
                      )}
                    </td>
                    <td>
                      {confTag === 'source-verified' && <span className="badge badge-source">source-verified</span>}
                      {confTag === 'inferred' && <span className="badge badge-inferred">inferred</span>}
                      {confTag === 'not-found' && <span className="badge badge-not-found">not-found</span>}
                    </td>
                    <td className="text-xs font-medium text-slate-300">
                      {pentry.source_type}
                    </td>
                    <td>
                      {pentry.source_url ? (
                        <a href={pentry.source_url} target="_blank" rel="noreferrer" className="text-xs text-cyan-400 hover:underline inline-flex items-center gap-1">
                          <ExternalLink className="w-3 h-3" /> Link
                        </a>
                      ) : (
                        <span className="text-xs text-slate-600">N/A</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
