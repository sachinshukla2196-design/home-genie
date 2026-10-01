import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API = axios.create({ baseURL: `${BACKEND_URL}/api` });

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
