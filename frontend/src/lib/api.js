import axios from "axios";

// Set REACT_APP_BACKEND_URL at build time (e.g. https://home-genies-api.vercel.app).
// Without it, requests go to this site's own /api path.
const BACKEND_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/+$/, "");
if (!BACKEND_URL) console.warn("REACT_APP_BACKEND_URL is not set; calling /api on this site.");
export const API = axios.create({ baseURL: `${BACKEND_URL}/api` });

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
