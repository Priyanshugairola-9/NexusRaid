import { useMemo, useState } from "react";
import { formatNumber } from "../utils/format.js";

export function Panel({ title, actions, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header>
          {title && <h2>{title}</h2>}
          {actions && <div className="row">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Tile({ label, value, hint }) {
  return (
    <div className="tile">
      <div className="value">{value}</div>
      <div className="label">{label}</div>
      {hint && <div className="small muted">{hint}</div>}
    </div>
  );
}

export function Pill({ kind, children }) {
  return <span className={`pill ${kind || "neutral"}`}>{children}</span>;
}

export function Loading({ label = "Loading" }) {
  return (
    <p className="row muted" role="status">
      <span className="spinner" aria-hidden="true" /> {label}…
    </p>
  );
}

export function ErrorMessage({ error, onRetry }) {
  if (!error) return null;
  return (
    <div className="alert error" role="alert">
      <strong>{error.code === "network_error" ? "Backend not reachable" : "Something went wrong"}</strong>
      <p>{error.message}</p>
      {onRetry && (
        <button className="btn small" onClick={onRetry} style={{ marginTop: "0.5rem" }}>
          Try again
        </button>
      )}
    </div>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="empty">
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </div>
  );
}

// Sortable table. columns: [{ key, label, numeric, render }]
export function DataTable({ columns, rows, onRowClick, initialSort, caption }) {
  const [sort, setSort] = useState(initialSort || null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const { key, dir } = sort;
    return [...rows].sort((a, b) => {
      const x = a[key];
      const y = b[key];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x > y ? 1 : -1) * (dir === "asc" ? 1 : -1);
    });
  }, [rows, sort]);
  const toggle = (key) =>
    setSort((current) => (current?.key === key ? { key, dir: current.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }));
  return (
    <div className="table-wrap">
      <table>
        {caption && <caption className="visually-hidden">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key} className={column.numeric ? "numeric" : ""}
                aria-sort={sort?.key === column.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
                {column.sortable === false ? column.label : (
                  <button onClick={() => toggle(column.key)}>
                    {column.label}
                    {sort?.key === column.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                  </button>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, index) => (
            <tr key={row.id ?? index} className={onRowClick ? "clickable" : ""}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              onKeyDown={onRowClick ? (e) => e.key === "Enter" && onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}>
              {columns.map((column) => (
                <td key={column.key} className={column.numeric ? "numeric" : ""}>
                  {column.render ? column.render(row) : column.numeric ? formatNumber(row[column.key]) : String(row[column.key] ?? "–")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Horizontal bars for category frequencies, built with CSS (no chart library needed).
export function BarList({ items, valueLabel = (item) => `${item.pct}%` }) {
  const max = Math.max(...items.map((item) => item.count), 1);
  return (
    <div className="bars">
      {items.map((item) => (
        <div className="bar-row" key={item.value}>
          <span className="name" title={item.value}>{item.value}</span>
          <span className="track" aria-hidden="true"><span className="fill" style={{ width: `${(item.count / max) * 100}%`, display: "block" }} /></span>
          <span className="num small" style={{ textAlign: "right" }}>{valueLabel(item)}</span>
        </div>
      ))}
    </div>
  );
}

export function SimpleTable({ table }) {
  return (
    <div className="stack-sm">
      <h3>{table.title}</h3>
      <div className="table-wrap">
        <table>
          <thead><tr>{table.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {table.rows.map((row, i) => (
              <tr key={i}>{row.map((cell, j) => <td key={j} className={typeof cell === "number" ? "numeric" : ""}>{typeof cell === "number" ? formatNumber(cell) : String(cell ?? "–")}</td>)}</tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
