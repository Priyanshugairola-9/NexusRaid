export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  if (typeof value !== "number") return String(value);
  if (Number.isInteger(value)) return value.toLocaleString();
  const abs = Math.abs(value);
  return value.toLocaleString(undefined, { maximumFractionDigits: abs >= 100 ? 1 : digits });
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "–";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function formatDate(iso) {
  if (!iso) return "–";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toLocaleString();
}

export function formatTimeAxis(value, spanMs) {
  const date = new Date(value);
  if (spanMs !== undefined && spanMs < 2 * 86400000) return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return date.toLocaleDateString([], { month: "short", day: "numeric" }) + (spanMs < 8 * 86400000 ? " " + date.toLocaleTimeString([], { hour: "2-digit" }) : "");
}

export const DOMAIN_TITLES = {
  server: "Server monitoring", website: "Website performance", network: "Network traffic", iot: "IoT sensor data",
  financial: "Financial transactions", student: "Student performance", general: "General dataset",
};
