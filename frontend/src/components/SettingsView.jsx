import React, { useEffect, useState } from 'react';
import { CheckCircle2, KeyRound, Save, Webhook } from 'lucide-react';

const API_BASE = 'http://localhost:8000';

export default function SettingsView() {
  const [apiKey, setApiKey] = useState('');
  const [savedKey, setSavedKey] = useState('');
  const [webhook, setWebhook] = useState('');
  const [threshold, setThreshold] = useState('0.75');
  const [connected, setConnected] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    const savedKey = localStorage.getItem('gemini_api_key') || '';
    setSavedKey(savedKey);
    setWebhook(localStorage.getItem('pipeline_webhook_url') || '');
    setThreshold(localStorage.getItem('confidence_threshold') || '0.75');
    fetch(`${API_BASE}/health`).then((r) => setConnected(r.ok && Boolean(savedKey))).catch(() => setConnected(false));
  }, []);

  const masked = savedKey ? `••••••••${savedKey.slice(-4)}` : '';
  const save = (event) => {
    event.preventDefault();
    if (webhook && !/^https?:\/\/[^\s]+$/i.test(webhook)) return;
    const nextKey = apiKey || savedKey;
    localStorage.setItem('gemini_api_key', nextKey);
    setSavedKey(nextKey);
    setApiKey('');
    localStorage.setItem('pipeline_webhook_url', webhook);
    localStorage.setItem('confidence_threshold', String(Math.min(1, Math.max(0, Number(threshold) || 0.75))));
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  return <section className="settings-page space-y-6">
    <div><h2 className="text-2xl font-bold text-slate-900">Settings</h2><p className="text-sm text-slate-500 mt-1">Configure local dashboard preferences and pipeline connection details.</p></div>
    <form onSubmit={save} className="card settings-form space-y-6">
      <div className="setting-row"><div><label htmlFor="gemini-key" className="setting-label"><KeyRound className="w-4 h-4" /> Gemini API key</label><p className="setting-help">Saved locally and never shown in full.</p></div><div className="setting-control"><input id="gemini-key" type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} placeholder={masked || 'Paste a new key'} className="input-control"/><span className={`status-dot ${connected ? 'is-connected' : ''}`}><span /> Gemini: {connected ? 'Connected' : 'Not configured'}</span></div></div>
      <div className="setting-row"><div><label htmlFor="webhook-url" className="setting-label"><Webhook className="w-4 h-4" /> Webhook URL</label><p className="setting-help">Saved for future run-completion notifications; webhook delivery is not wired yet.</p></div><input id="webhook-url" type="url" value={webhook} onChange={(e) => setWebhook(e.target.value)} placeholder="https://example.com/pipeline-hook" className="input-control"/></div>
      <div className="setting-row"><div><label htmlFor="confidence-threshold" className="setting-label">Confidence threshold</label><p className="setting-help">Records below this value are routed to review.</p></div><div className="threshold-control"><input id="confidence-threshold" type="range" min="0" max="1" step="0.01" value={threshold} onChange={(e) => setThreshold(e.target.value)}/><output>{Number(threshold).toFixed(2)}</output></div></div>
      <div className="settings-actions"><button type="submit" className="btn-primary"><Save className="w-4 h-4"/> Save settings</button>{saved && <span className="save-confirm"><CheckCircle2 className="w-4 h-4"/> Settings saved</span>}</div>
    </form>
  </section>;
}
