import { useEffect, useRef } from "react";
import { formatNumber } from "../utils/format.js";
import { Pill } from "./ui.jsx";

// Accessible dialog for one flagged row: Esc closes it, focus moves into it.
export default function RowDialog({ record, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    if (record && dialog && !dialog.open) dialog.showModal();
    if (!record && dialog?.open) dialog.close();
  }, [record]);
  return (
    <dialog ref={ref} className="sheet" onClose={onClose} aria-labelledby="row-title">
      {record && (
        <>
          <div className="sheet-head">
            <h2 id="row-title">Row {record.row_number}</h2>
            <button className="btn small" onClick={() => ref.current.close()} autoFocus>Close</button>
          </div>
          <div className="sheet-body stack">
            <div className="row">
              <span>Deviation <strong className="num">{record.deviation}</strong> robust SDs</span>
              {record.methods.map((m) => <Pill key={m} kind="info">{m}</Pill>)}
            </div>
            <div>
              <h3>Why it was flagged</h3>
              <ul>{record.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul>
            </div>
            <div>
              <h3>All values in this row</h3>
              <div className="table-wrap" style={{ marginTop: "0.5rem" }}>
                <table>
                  <tbody>
                    {Object.entries(record.values).map(([column, value]) => (
                      <tr key={column} style={record.columns.includes(column) ? { background: "var(--warn-soft)" } : undefined}>
                        <th scope="row">{column}{record.columns.includes(column) ? " (flagged)" : ""}</th>
                        <td className={typeof value === "number" ? "numeric" : ""}>{typeof value === "number" ? formatNumber(value, 4) : String(value ?? "–")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </dialog>
  );
}
