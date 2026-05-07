const TOKEN_KEY = "metaporn_portal_token";
const CREATOR_KEY = "metaporn_portal_creator";

export function getApiBase() {
  return (import.meta.env.VITE_METAPORN_API_BASE || "").replace(/\/$/, "");
}

export function buildApiUrl(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const base = getApiBase();
  return `${base}${normalized}`;
}

export function getToken() {
  return window.localStorage.getItem(TOKEN_KEY) || "";
}

export function getStoredCreator() {
  const raw = window.localStorage.getItem(CREATOR_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function saveSession(session) {
  if (session?.token) {
    window.localStorage.setItem(TOKEN_KEY, session.token);
  }
  if (session?.creator) {
    window.localStorage.setItem(CREATOR_KEY, JSON.stringify(session.creator));
  }
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(CREATOR_KEY);
}

export async function portalFetch(path, options = {}) {
  const token = getToken();
  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(buildApiUrl(path), {
    ...options,
    headers,
  });

  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : await response.text();

  if (!response.ok) {
    const detail =
      typeof payload === "string"
        ? payload
        : payload?.detail || payload?.error || response.statusText;
    throw new Error(detail || "Falha na requisição");
  }
  return payload;
}

export async function portalLogin(email, password) {
  const session = await portalFetch("/api/portal/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  saveSession(session);
  return session;
}

export async function fetchPortalBrandingBySlug(slug) {
  return portalFetch(`/api/portal/brand/${encodeURIComponent(String(slug || "").trim())}`);
}
