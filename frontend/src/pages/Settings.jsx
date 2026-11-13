import { useEffect, useState } from "react";
import { ErrorMessage, Loading, Panel } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { api, getAccessKey, setAccessKey } from "../services/api.js";
import { formatNumber } from "../utils/format.js";

const NUMBER_FIELDS = [
  ["zscore_threshold", "Z-score threshold", "Used only when a column is roughly bell-shaped and Z-score is selected.", 0.5],
  ["modified_zscore_threshold", "Modified Z-score threshold", "Median/MAD based; 3.5 is the textbook value.", 0.5],
  ["iqr_multiplier", "IQR multiplier", "3 = Tukey's 'far out' fence. 1.5 flags many more values in large files.", 0.5],
  ["multivariate_threshold", "Row-level threshold (robust SDs)", "Higher = fewer rows flagged by Isolation Forest/LOF.", 0.5],
  ["drift_threshold", "Drift threshold (baseline spreads)", "How far the recent level must move from the early level.", 0.5],
  ["spike_threshold", "Spike threshold", "Spike size relative to point-to-point noise.", 0.5],
  ["shift_threshold", "Level-change threshold", "Jump size relative to noise for sudden level changes.", 0.5],
];

function ThresholdPair({ label, value, onChange, unit }) {
  return (
    <div className="field">
      <label>{label}</label>
      <div className="row">
        <input type="number" step="any" aria-label={`${label} warning`} value={value?.[0] ?? ""} onChange={(e) => onChange([e.target.value === "" ? null : Number(e.target.value), value?.[1] ?? null])} style={{ width: "7rem" }} />
        <input type="number" step="any" aria-label={`${label} critical`} value={value?.[1] ?? ""} onChange={(e) => onChange([value?.[0] ?? null, e.target.value === "" ? null : Number(e.target.value)])} style={{ width: "7rem" }} />
        <span className="small muted">warning / critical {unit}</span>
      </div>
    </div>
  );
}

export default function Settings({ info }) {
  const settings = useAsync(() => api.getSettings(), []);
  const [config, setConfig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [key, setKey] = useState(getAccessKey());
  const [keySaved, setKeySaved] = useState(false);
  useEffect(() => { if (settings.data) setConfig(settings.data.config); }, [settings.data]);

  const set = (name, value) => setConfig((c) => ({ ...c, [name]: value }));
  const setThreshold = (name, pair) => setConfig((c) => ({ ...c, risk_thresholds: { ...c.risk_thresholds, [name]: pair } }));

  const save = async (next) => {
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      const thresholds = Object.fromEntries(Object.entries(next.risk_thresholds).filter(([, pair]) => pair && pair[0] != null && pair[1] != null));
      const saved = await api.saveSettings({ ...next, risk_thresholds: thresholds });
      setConfig(saved.config);
      setMessage("Settings saved. They apply to the next analysis.");
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  const saveKey = () => {
    setAccessKey(key.trim());
    setKeySaved(true);
    settings.reload();
  };

  return (
    <div className="stack">
      <div className="page-head"><div><h1>Settings</h1><p className="muted">Analysis defaults, access and application information.</p></div></div>

      <Panel title="Appearance">
        <p>Use the theme button at the top right. Your choice is remembered in this browser.</p>
      </Panel>

      {info.access_key_required && (
        <Panel title="Access key">
          <div className="stack-sm">
            <p className="small">This server is protected. The key is stored only in this browser.</p>
            <div className="row">
              <div className="field" style={{ flex: 1, minWidth: 220 }}>
                <label htmlFor="access-key">Access key</label>
                <input id="access-key" type="password" autoComplete="off" value={key} onChange={(e) => { setKey(e.target.value); setKeySaved(false); }} />
              </div>
              <button className="btn primary" onClick={saveKey} style={{ alignSelf: "flex-end" }}>Save key</button>
            </div>
            {keySaved && <p className="small">Key saved.</p>}
          </div>
        </Panel>
      )}

      <Panel title="Analysis settings">
        {settings.loading && <Loading />}
        {settings.error && <ErrorMessage error={settings.error} onRetry={settings.reload} />}
        {config && (
          <form className="stack" onSubmit={(e) => { e.preventDefault(); save(config); }}>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="uni">Per-column method</label>
                <select id="uni" value={config.univariate_method} onChange={(e) => set("univariate_method", e.target.value)}>
                  <option value="auto">Automatic (recommended)</option>
                  <option value="modified_zscore">Modified Z-score</option>
                  <option value="zscore">Z-score</option>
                  <option value="iqr">IQR</option>
                </select>
                <span className="hint">Automatic picks per column based on its distribution.</span>
              </div>
              <div className="field">
                <label htmlFor="multi">Row-level method</label>
                <select id="multi" value={config.multivariate_method} onChange={(e) => set("multivariate_method", e.target.value)}>
                  <option value="auto">Automatic (Isolation Forest)</option>
                  <option value="isolation_forest">Isolation Forest</option>
                  <option value="lof">Local Outlier Factor (up to 20,000 rows)</option>
                  <option value="dbscan">DBSCAN (up to 10,000 rows)</option>
                  <option value="none">Off</option>
                </select>
              </div>
              {NUMBER_FIELDS.map(([name, label, hint, step]) => (
                <div className="field" key={name}>
                  <label htmlFor={name}>{label}</label>
                  <input id={name} type="number" step={step} value={config[name]} onChange={(e) => set(name, Number(e.target.value))} />
                  <span className="hint">{hint}</span>
                </div>
              ))}
            </div>
            <h3>Risk thresholds</h3>
            <p className="small muted">Utilisation levels in percent. Latency is optional: leave it empty if you have no target, and latency is then judged only relative to its own history.</p>
            <div className="grid-2">
              <ThresholdPair label="CPU" unit="%" value={config.risk_thresholds.cpu} onChange={(p) => setThreshold("cpu", p)} />
              <ThresholdPair label="Memory" unit="%" value={config.risk_thresholds.memory} onChange={(p) => setThreshold("memory", p)} />
              <ThresholdPair label="Disk" unit="%" value={config.risk_thresholds.disk} onChange={(p) => setThreshold("disk", p)} />
              <ThresholdPair label="Error rate" unit="%" value={config.risk_thresholds.error_rate_pct} onChange={(p) => setThreshold("error_rate_pct", p)} />
              <ThresholdPair label="Latency target" unit="ms" value={config.risk_thresholds.latency_ms} onChange={(p) => setThreshold("latency_ms", p)} />
            </div>
            <ErrorMessage error={error} />
            {message && <div className="alert success" role="status">{message}</div>}
            <div className="row">
              <button className="btn primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save settings"}</button>
              <button className="btn" type="button" disabled={saving} onClick={() => save(settings.data.defaults)}>Restore defaults</button>
            </div>
          </form>
        )}
      </Panel>

      <Panel title="Upload limits">
        <p>Up to {info.limits.max_upload_mb} MB, {formatNumber(info.limits.max_rows)} rows and {info.limits.max_columns} columns per file.
          Limits are set on the server (<code>NEXUSRAID_MAX_UPLOAD_MB</code> and related variables) so that a public deployment cannot be changed from the browser.</p>
      </Panel>

      <Panel title="About">
        <div className="stack-sm">
          <p>{info.app} {info.version}, {info.environment} mode. Live metric ingestion is {info.monitoring_ingestion_enabled ? "enabled" : "disabled"}.</p>
          <p className="small">{info.privacy_notice}</p>
          <p className="small muted">Supported domains: {info.domains.map((d) => d.title).join(", ")}. Anything else is analysed with general statistics.</p>
        </div>
      </Panel>
    </div>
  );
}
