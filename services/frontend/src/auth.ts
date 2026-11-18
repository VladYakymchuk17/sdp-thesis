import type { AuthUser } from "./types";

const KEY = "sdp_auth";

export function getUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function saveUser(user: AuthUser) {
  localStorage.setItem(KEY, JSON.stringify(user));
}

export function clearUser() {
  localStorage.removeItem(KEY);
}

export function getToken(): string | null {
  return getUser()?.token ?? null;
}
