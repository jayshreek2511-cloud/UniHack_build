import React, { useState } from 'react';
import { ExternalLink, FileText, CheckCircle, AlertTriangle, Shield, Search } from 'lucide-react';
import DescriptionsModal from './DescriptionsModal';

export default function CatalogView({ records, onSelectRecord }) {
  const [selectedDescRecord, setSelectedDescRecord] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

  const filteredRecords = records.filter((r) => {
    const sku = r.identity.mfg_part_num.toLowerCase();
    const brand = (r.identity.part_manuf || '').toLowerCase();
    const term = searchTerm.toLowerCase();
    return sku.includes(term) || brand.includes(term);
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-white">Enriched Products Catalog</h2>
          <p className="text-sm text-slate-400 mt-1">Live enriched records from the full category pipeline</p>
        </div>

        <div className="relative w-full sm:w-72">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="Search SKU or Brand..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded-lg pl-9 pr-4 py-2 text-sm text-slate-200 focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      <div className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Mfg Part Num</th>
                <th>Brand / Manufacturer</th>
                <th>Category</th>
                <th>MFR Source URL</th>
                <th>Completeness Score</th>
                <th>Status</th>
                <th className="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filteredRecords.map((r) => {
                const sku = r.identity.mfg_part_num;
                const score = r.confidence_score.overall_score;
                const scorePct = (score * 100).toFixed(0);
                const status = r.review_status;
                const mfrUrl = r.manufacturer_info.mfr_url;

                return (
                  <tr key={sku}>
                    <td className="font-mono font-bold text-blue-400">{sku}</td>
                    <td>
                      <div className="font-semibold text-white">{r.manufacturer_info.real_brand || r.identity.part_manuf}</div>
                      <div className="text-xs text-slate-400">{r.manufacturer_info.real_manufacturer}</div>
                    </td>
                    <td className="text-xs text-slate-300">{r.extraction?.coarse_category || r.identity.coarse_category || 'Uncategorized'}</td>
                    <td>
                      {mfrUrl ? (
                        <a
                          href={mfrUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-cyan-400 hover:underline max-w-[180px] truncate"
                        >
                          <ExternalLink className="w-3 h-3 flex-shrink-0" />
                          <span className="truncate">{mfrUrl}</span>
                        </a>
                      ) : (
                        <span className="text-xs text-rose-400 font-mono">Not Verified (403)</span>
                      )}
                    </td>
                    <td className="w-44">
                      <div className="flex items-center gap-2">
                        <div className="progress-bar-bg flex-1">
                          <div
                            className={`progress-bar-fill ${score >= 0.75 ? 'bg-emerald-500' : 'bg-rose-500'}`}
                            style={{ width: `${scorePct}%` }}
                          />
                        </div>
                        <span className="text-xs font-bold font-mono text-slate-200">{score.toFixed(3)}</span>
                      </div>
                    </td>
                    <td>
                      {status === 'complete' && <span className="badge badge-complete">Complete</span>}
                      {status === 'approved' && <span className="badge badge-approved">Approved</span>}
                      {status === 'needs_review' && <span className="badge badge-review">Needs Review</span>}
                    </td>
                    <td className="text-right space-x-2">
                      <button
                        onClick={() => setSelectedDescRecord(r)}
                        className="btn-secondary text-xs py-1 px-2.5"
                        title="Inspect Generated Descriptions"
                      >
                        <FileText className="w-3.5 h-3.5" />
                        Descs (5)
                      </button>
                      <button
                        onClick={() => onSelectRecord(sku)}
                        className="btn-primary text-xs py-1 px-2.5"
                      >
                        Provenance &gt;
                      </button>
                    </td>
                  </tr>
                );
              })}
              {filteredRecords.length === 0 && (
                <tr><td colSpan="7" className="empty-state">No records yet — upload a CSV and run the pipeline to get started.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedDescRecord && (
        <DescriptionsModal
          record={selectedDescRecord}
          onClose={() => setSelectedDescRecord(null)}
        />
      )}
    </div>
  );
}
