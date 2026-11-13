import { useRef, useState } from "react";
import { Panel } from "../components/ui.jsx";
import { navigate } from "../hooks/useRoute.js";
import { api, uploadDataset } from "../services/api.js";
import { formatBytes, formatNumber } from "../utils/format.js";

export default function Upload({ info }) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(null);
  const [stage, setStage] = useState("idle"); // idle | uploading | analysing | done
  const [error, setError] = useState(null);
  const [dataset, setDataset] = useState(null);
  const maxBytes = info.limits.max_upload_mb * 1024 * 1024;

  const choose = (candidate) => {
    setError(null);
    setDataset(null);
    setStage("idle");
    if (!candidate) return;
    if (!candidate.name.toLowerCase().endsWith(".csv")) {
      setError("Only .csv files are supported. Export your spreadsheet as CSV first.");
      return;
    }
    if (candidate.size > maxBytes) {
      setError(`This file is ${formatBytes(candidate.size)}; the limit is ${info.limits.max_upload_mb} MB.`);
      return;
    }
    setFile(candidate);
  };

  const start = async (analyse) => {
    setError(null);
    setStage("uploading");
    setProgress(0);
    try {
      const created = await uploadDataset(file, setProgress);
      setDataset(created);
      if (analyse) {
        setStage("analysing");
        await api.analyze(created.id);
        navigate(`/datasets/${created.id}/results`);
        return;
      }
      setStage("done");
    } catch (err) {
      setError(err.message);
      setStage("idle");
    }
  };

  const reset = () => {
    setFile(null);
    setDataset(null);
    setStage("idle");
    setProgress(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Upload dataset</h1>
          <p className="muted">
            CSV files up to {info.limits.max_upload_mb} MB, {formatNumber(info.limits.max_rows)} rows and {info.limits.max_columns} columns.
            The file is checked before anything is stored.
          </p>
        </div>
      </div>
      <div
        className={`dropzone ${dragging ? "active" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files?.[0]); }}
      >
        <p><strong>Drag a CSV file here</strong> or</p>
        <p style={{ marginTop: "0.6rem" }}>
          <label className="btn" htmlFor="file-input">Choose a file</label>
          <input id="file-input" ref={inputRef} type="file" accept=".csv,text/csv" className="visually-hidden"
            onChange={(e) => choose(e.target.files?.[0])} />
        </p>
      </div>

      {error && <div className="alert error" role="alert"><strong>Cannot use this file.</strong> {error}</div>}

      {file && (
        <Panel title="Selected file" actions={stage === "idle" && <button className="btn small" onClick={reset}>Remove</button>}>
          <div className="stack-sm">
            <p><strong>{file.name}</strong> <span className="muted">{formatBytes(file.size)}</span></p>
            {stage === "idle" && !dataset && (
              <div className="row">
                <button className="btn primary" onClick={() => start(true)}>Upload and analyse</button>
                <button className="btn" onClick={() => start(false)}>Upload only</button>
              </div>
            )}
            {stage === "uploading" && (
              <div className="stack-sm" role="status">
                <div className="progress" aria-hidden="true"><div style={{ width: `${progress}%` }} /></div>
                <p className="small muted">Uploading {progress}%. The server validates and profiles the file afterwards.</p>
              </div>
            )}
            {stage === "analysing" && <p className="row" role="status"><span className="spinner" /> Analysing. Large files can take up to a minute on modest hardware.</p>}
          </div>
        </Panel>
      )}

      {dataset && stage === "done" && (
        <div className="alert success">
          <p><strong>Uploaded {dataset.original_filename}</strong>: {formatNumber(dataset.row_count)} rows, {dataset.column_count} columns.</p>
          {dataset.upload_warnings.length > 0 && <ul>{dataset.upload_warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
          <div className="row" style={{ marginTop: "0.6rem" }}>
            <a className="btn" href={`#/datasets/${dataset.id}/profile`}>View profile</a>
            <button className="btn" onClick={reset}>Upload another</button>
          </div>
        </div>
      )}

      <p className="small muted">{info.privacy_notice}</p>
    </div>
  );
}
