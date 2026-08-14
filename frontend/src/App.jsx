import React, { useState, useEffect } from 'react';
import { Database, Grid, ShieldAlert, FileSearch, RefreshCw } from 'lucide-react';
import PipelineView from './components/PipelineView';
import CatalogView from './components/CatalogView';
import ReviewQueueView from './components/ReviewQueueView';
import RecordDetailView from './components/RecordDetailView';

const API_BASE = 'http://localhost:8000';

export default function App() {
  const [activeTab, setActiveTab] = useState('pipeline'); // 'pipeline' | 'catalog' | 'review' | 'detail'
  const [stats, setStats] = useState(null);
  const [records, setRecords] = useState([]);
  const [reviewQueue, setReviewQueue] = useState(null);
  const [selectedSku, setSelectedSku] = useState(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      const [resStats, resRecords, resQueue] = await Promise.all([
        fetch(`${API_BASE}/api/stats`).then((r) => r.json()),
        fetch(`${API_BASE}/api/records`).then((r) => r.json()),
        fetch(`${API_BASE}/api/review-queue`).then((r) => r.json()),
      ]);

      setStats(resStats);
      setRecords(resRecords);
      setReviewQueue(resQueue);
    } catch (err) {
      console.error('Failed to fetch API data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, []);

  const handleApproveRecord = async (sku) => {
    try {
      const res = await fetch(`${API_BASE}/api/records/${sku}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: 'Approved via Phase 5 Dashboard' }),
      });
      const data = await res.json();
      if (res.ok) {
        showToast(`SKU ${sku} approved successfully!`);
        await fetchData();
      }
    } catch (err) {
      console.error('Failed to approve record:', err);
    }
  };

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 4000);
  };

  const handleSelectRecord = (sku) => {
    setSelectedSku(sku);
    setActiveTab('detail');
  };

  const selectedRecordObj = records.find(
    (r) => r.identity.mfg_part_num.toUpperCase() === (selectedSku || '').toUpperCase()
  );

  return (
    <div className="app-container">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div className="brand-header">
          <div className="brand-icon">PI</div>
          <div>
            <div className="brand-title">Product Intelligence</div>
            <span className="text-[10px] font-mono text-cyan-400 block uppercase">Industrial Commerce</span>
          </div>
        </div>

        <ul className="nav-list">
          <li>
            <button
              onClick={() => setActiveTab('pipeline')}
              className={`nav-button ${activeTab === 'pipeline' ? 'active' : ''}`}
            >
              <Database className="w-4 h-4" /> Pipeline Flow
            </button>
          </li>
          <li>
            <button
              onClick={() => setActiveTab('catalog')}
              className={`nav-button ${activeTab === 'catalog' ? 'active' : ''}`}
            >
              <Grid className="w-4 h-4" /> Catalog ({records.length})
            </button>
          </li>
          <li>
            <button
              onClick={() => setActiveTab('review')}
              className={`nav-button ${activeTab === 'review' ? 'active' : ''}`}
            >
              <ShieldAlert className="w-4 h-4" /> Review Queue
              {stats && stats.review_count > 0 && (
                <span className="ml-auto bg-rose-900/80 text-rose-300 text-xs px-2 py-0.5 rounded-full border border-rose-700">
                  {stats.review_count}
                </span>
              )}
            </button>
          </li>
          {selectedSku && (
            <li>
              <button
                onClick={() => setActiveTab('detail')}
                className={`nav-button ${activeTab === 'detail' ? 'active' : ''}`}
              >
                <FileSearch className="w-4 h-4" /> Detail: {selectedSku}
              </button>
            </li>
          )}
        </ul>

        {/* Sidebar Footer */}
        <div className="mt-auto pt-4 border-t border-slate-800 text-xs text-slate-500 space-y-1">
          <div>Backend: <span className="text-emerald-400 font-mono">FastAPI :8000</span></div>
          <div>Frontend: <span className="text-cyan-400 font-mono">React Vite</span></div>
          <div>Status: <span className="text-slate-300 font-medium">Live Execution Data</span></div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="main-content">
        <header className="top-bar">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono text-slate-400 uppercase">Hackathon Phase 5 Dashboard</span>
            <span className="text-slate-600">/</span>
            <span className="text-xs font-semibold text-cyan-400 capitalize">{activeTab} View</span>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={fetchData} className="btn-secondary text-xs py-1.5 px-3">
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh Data
            </button>
          </div>
        </header>

        <div className="content-body">
          {toast && (
            <div className="bg-emerald-950/90 border border-emerald-500 text-emerald-200 px-4 py-3 rounded-xl text-sm font-semibold shadow-lg flex items-center justify-between">
              <span>{toast}</span>
              <button onClick={() => setToast(null)} className="text-xs text-emerald-400 hover:underline">Dismiss</button>
            </div>
          )}

          {activeTab === 'pipeline' && <PipelineView stats={stats} onNavigate={setActiveTab} onRefresh={fetchData} />}
          {activeTab === 'catalog' && <CatalogView records={records} onSelectRecord={handleSelectRecord} />}
          {activeTab === 'review' && (
            <ReviewQueueView
              reviewQueue={reviewQueue}
              onApprove={handleApproveRecord}
              onSelectRecord={handleSelectRecord}
            />
          )}
          {activeTab === 'detail' && (
            <RecordDetailView
              record={selectedRecordObj}
              onBack={() => setActiveTab('catalog')}
            />
          )}
        </div>
      </main>
    </div>
  );
}
