import { useState } from "react";
import { DataTable, EmptyState, ErrorMessage, Loading } from "../components/ui.jsx";
import { useAsync } from "../hooks/useAsync.js";
import { download, api } from "../services/api.js";
import { formatDate } from "../utils/format.js";

const FORMATS = [
  { label: "HTML report", path: (id) => `/datasets/${id}/report?format=html`, file: (id) => `nexusraid-report-${id}.html` },
  { label: "Results (JSON)", path: (id) => `/datasets/${id}/report?format=json`, file: (id) => `nexusraid-results-${id}.json` },
  { label: "Flagged rows (CSV)", path: (id) => `/datasets/${id}/anomalies.csv`, file: (id) => `nexusraid-anomalies-${id}.csv` },
  { label: "Findings (CSV)", path: (id) => `/datasets/${id}/findings.csv`, file: (id) => `nexusraid-findings-${id}.csv` },
];

export default function Reports() {
  const { data, error, loading, reload } = useAsync(() => api.datasets(), []);
  const [busy, setBusy] = useState(null);
  const [downloadError, setDownloadError] = useState(null);
  const get = async (dataset, format) => {
    setBusy(`${dataset.id}-${format.label}`);
    setDownloadError(null);
    try {
      await download(format.path(dataset.id), format.file(dataset.id));
    } catch (err) {
      setDownloadError(err);
    } finally {
      setBusy(null);
    }
  };
  if (loading) return <Loading />;
  if (error) return <ErrorMessage error={error} onRetry={reload} />;
  const analysed = data.filter((d) => d.latest_analysis);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Reports</h1>
          <p className="muted">Download the latest analysis of a dataset. The HTML report opens in any browser and can be printed or saved as PDF from there.</p>
        </div>
      </div>
      <ErrorMessage error={downloadError} />
      {analysed.length === 0 ? (
        <EmptyState title="No analysed datasets" action={<a className="btn primary" href="#/datasets">Go to datasets</a>}>Analyse a dataset to create a report.</EmptyState>
      ) : (
        <DataTable
          rows={analysed.map((d) => ({ ...d, analysed: d.latest_analysis.created_at }))}
          columns={[
            { key: "original_filename", label: "Dataset" },
            { key: "analysed", label: "Analysed", render: (d) => formatDate(d.analysed) },
            { key: "downloads", label: "Download", sortable: false, render: (d) => (
              <div className="row" style={{ gap: "0.35rem" }}>
                {FORMATS.map((f) => (
                  <button key={f.label} className="btn small" disabled={busy === `${d.id}-${f.label}`} onClick={() => get(d, f)}>
                    {busy === `${d.id}-${f.label}` ? "Preparing…" : f.label}
                  </button>
                ))}
              </div>
            ) },
          ]}
        />
      )}
    </div>
  );
}
