import axios from "axios";

// The only place the backend URL is read. Set REACT_APP_BACKEND_URL at build time to the API's public
// origin (no trailing slash, no /api). `npm run build` refuses to build without it (scripts/check-env.js);
// local development reads it from .env.development.local. There is deliberately no fallback URL.
export const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").trim().replace(/\/+$/, "");
export const API_CONFIGURED = Boolean(BACKEND_URL);
if (!API_CONFIGURED) console.error("REACT_APP_BACKEND_URL is not set: API requests are disabled.");
export const API = axios.create({ baseURL: API_CONFIGURED ? `${BACKEND_URL}/api` : undefined });

// Fail loudly instead of silently calling a wrong host when the URL is missing.
API.interceptors.request.use((config) => {
  if (!API_CONFIGURED) {
    const err = new Error("The service is not configured yet. Please try again later.");
    err.response = { status: 503, data: { detail: err.message } };
    return Promise.reject(err);
  }
  return config;
});

// If the API is unreachable, a static host can answer /api/* with the app's own index.html.
// Treat any HTML reply as a failed request so pages show their empty/error state instead of crashing.
API.interceptors.response.use((res) => {
  const type = String(res.headers?.["content-type"] || "");
  if (type.includes("text/html") || (typeof res.data === "string" && res.data.trimStart().startsWith("<"))) {
    const err = new Error("The service is temporarily unavailable. Please try again shortly.");
    err.response = { status: 503, data: { detail: err.message } };
    return Promise.reject(err);
  }
  return res;
});

API.interceptors.request.use((config) => {
  const token = localStorage.getItem("anj_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

export function apiError(e, fallback = "Something went wrong. Please try again.") {
  const d = e?.response?.data?.detail;
  if (d == null) return e?.message || fallback;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => (x?.msg ? x.msg : JSON.stringify(x))).join(" ");
  if (d?.message) return d.message;
  if (d?.msg) return d.msg;
  return fallback;
}
