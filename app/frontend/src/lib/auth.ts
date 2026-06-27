/**
 * 前端 auth 工具：token 存 localStorage + 全局 fetch wrap 自动加 Bearer header
 */

const TOKEN_KEY = "qb-auth-token";
const USER_KEY = "qb-auth-user";

export interface AuthUser {
  user_id: string;
  username: string;
  display_name: string;
  bio?: string;
  avatar_url?: string;
  created_at_utc?: string;
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function getStoredUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function setSession(token: string, user: AuthUser): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event("qb-auth-change"));
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  window.dispatchEvent(new Event("qb-auth-change"));
}

export async function authFetch(input: RequestInfo, init: RequestInit = {}): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !headers.has("content-type") && !isFormData) headers.set("content-type", "application/json");
  return fetch(input, { ...init, headers });
}

export async function login(username: string, password: string): Promise<AuthUser> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(j.detail || `HTTP ${res.status}`);
  }
  const j = await res.json();
  setSession(j.token, j.user);
  return j.user;
}

export async function register(username: string, password: string, displayName?: string): Promise<AuthUser> {
  const res = await fetch("/api/auth/register", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password, display_name: displayName || username }),
  });
  if (!res.ok) {
    const j = await res.json().catch(() => ({}));
    throw new Error(j.detail || `HTTP ${res.status}`);
  }
  const j = await res.json();
  setSession(j.token, j.user);
  return j.user;
}

export async function logout(): Promise<void> {
  await authFetch("/api/auth/logout", { method: "POST" });
  clearSession();
}
