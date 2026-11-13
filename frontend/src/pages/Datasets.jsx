import { useState } from "react";
import { DataTable, EmptyState, ErrorMessage, Loading, Pill } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { navigate } from "../hooks/useRoute.js";
import { api } from "../services/api.js";
import { DOMAIN_TITLES, formatBytes, formatDate } from "../utils/format.js";

export default function Datasets() {
  const { data, error, loading, reload } = useAsync(() => api.datasets(), []);
  const [busy, setBusy] = useState(null);
  const [actionError, setActionError] = useState(null);

  const analyse = async (id) => {
    setBusy(id);
    setActionError(null);
    try {
      await api.analyze(id);
      navigate(`/datasets/${id}/results`);
    } catch (err) {
      setActionError(err);
      setBusy(null);
    }
  };
  const remove = async (row) => {
    if (!window.confirm(`Delete "${row.original_filename}" and all its analyses? This cannot be undone.`)) return;
    setBusy(row.id);
    try {
      await api.deleteDataset(row.id);
      reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setBusy(null);
    }
  };

  if (loading) return <Loading />;
  if (error) return <ErrorMessage error={error} onRetry={reload} />;
  const rows = data.map((d) => ({ ...d, domain: d.latest_analysis?.domain, risk: d.latest_analysis?.risk_level, created: d.created_at }));
  return (
    <div className="stack">
      <div className="page-head">
        <div><h1>Datasets</h1><p className="muted">Uploaded files and their latest analysis.</p></div>
        <a className="btn primary" href="#/upload">Upload a dataset</a>
      </div>
      <ErrorMessage error={actionError} />
      {rows.length === 0 ? (
        <EmptyState title="No datasets" action={<a className="btn primary" href="#/upload">Upload a CSV</a>}>Uploaded datasets appear here.</EmptyState>
      ) : (
        <DataTable
          caption="Datasets"
          initialSort={{ key: "created", dir: "desc" }}
          rows={rows}
          columns={[
            { key: "original_filename", label: "File", render: (r) => <a href={`#/datasets/${r.id}/profile`}>{r.original_filename}</a> },
            { key: "row_count", label: "Rows", numeric: true },
            { key: "size_bytes", label: "Size", numeric: true, render: (r) => formatBytes(r.size_bytes) },
            { key: "domain", label: "Domain", render: (r) => (r.domain ? DOMAIN_TITLES[r.domain] : <span className="muted">Not analysed</span>) },
            { key: "risk", label: "Risk", render: (r) => (r.risk ? <Pill kind={r.risk}>{r.risk}</Pill> : <span className="muted small">–</span>) },
            { key: "created", label: "Uploaded", render: (r) => formatDate(r.created_at) },
            { key: "actions", label: "Actions", sortable: false, render: (r) => (
              <div className="row" style={{ gap: "0.35rem" }}>
                {r.latest_analysis && <a className="btn small" href={`#/datasets/${r.id}/results`}>Results</a>}
                <button className="btn small" disabled={busy === r.id} onClick={() => analyse(r.id)}>
                  {busy === r.id ? "Working…" : r.latest_analysis ? "Re-analyse" : "Analyse"}
                </button>
                <button className="btn small danger" disabled={busy === r.id} onClick={() => remove(r)}>Delete</button>
              </div>
            ) },
          ]}
        />
      )}
    </div>
  );
}
