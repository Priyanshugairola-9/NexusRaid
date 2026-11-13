// Single place for talking to the backend.
// The base URL comes from VITE_API_BASE_URL (set when frontend and backend are hosted
// separately). Empty means "same origin": the Vite proxy in development, or the
// backend itself in single-port mode.
const BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const API = `${BASE}/api/v1`;
const KEY_STORAGE = "nexusraid-access-key";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function getAccessKey() {
  try {
    return localStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setAccessKey(value) {
  try {
    if (value) localStorage.setItem(KEY_STORAGE, value);
    else localStorage.removeItem(KEY_STORAGE);
  } catch {
    /* storage unavailable: key only lives for this page view */
  }
}

function headers(extra = {}) {
  const key = getAccessKey();
  return key ? { ...extra, "X-Access-Key": key } : extra;
}

async function toError(response) {
  let code = `http_${response.status}`;
  let message = `The server answered with status ${response.status}.`;
  try {
    const body = await response.json();
    if (body?.error) {
      code = body.error.code;
      message = body.error.message;
      if (body.error.details?.length) {
        message += " " + body.error.details.map((d) => `${d.field}: ${d.message}`).join("; ");
      }
    }
  } catch {
    /* not JSON */
  }
  return new ApiError(response.status, code, message);
}

export async function request(path, { method = "GET", body, query } = {}) {
  const url = new URL(`${API}${path}`, window.location.origin);
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  });
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: headers(body ? { "Content-Type": "application/json" } : {}),
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the NexusRaid backend. Check that it is running.");
  }
  if (!response.ok) throw await toError(response);
  return response.status === 204 ? null : response.json();
}

// Upload with progress: fetch() cannot report upload progress, XMLHttpRequest can.
export function uploadDataset(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API}/datasets/upload`);
    const key = getAccessKey();
    if (key) xhr.setRequestHeader("X-Access-Key", key);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress?.(Math.round((event.loaded / event.total) * 100));
    };
    xhr.onload = () => {
      let body = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new ApiError(xhr.status, body?.error?.code || "upload_failed", body?.error?.message || "Upload failed."));
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "Cannot reach the NexusRaid backend."));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

// Downloads go through fetch so the access-key header is included, then are saved as a file.
export async function download(path, filename) {
  const response = await fetch(`${API}${path}`, { headers: headers() });
  if (!response.ok) throw await toError(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const api = {
  info: () => request("/info"),
  health: () => request("/health"),
  overview: () => request("/overview"),
  datasets: () => request("/datasets"),
  dataset: (id) => request(`/datasets/${id}`),
  profile: (id) => request(`/datasets/${id}/profile`),
  deleteDataset: (id) => request(`/datasets/${id}`, { method: "DELETE" }),
  analyze: (id, config) => request(`/datasets/${id}/analyze`, { method: "POST", body: config ? { config } : {} }),
  results: (id) => request(`/datasets/${id}/results`),
  anomalies: (id, query) => request(`/datasets/${id}/anomalies`, { query }),
  getSettings: () => request("/settings/analysis"),
  saveSettings: (config) => request("/settings/analysis", { method: "PUT", body: { config } }),
  monitoringStatus: () => request("/monitoring/status"),
  monitoringMetrics: (machineId, minutes) => request("/monitoring/metrics", { query: { machine_id: machineId, minutes } }),
  monitoringAlerts: (machineId) => request("/monitoring/alerts", { query: { machine_id: machineId, limit: 30 } }),
  monitoringAnalysis: (machineId, hours) => request("/monitoring/analysis", { query: { machine_id: machineId, hours } }),
};
