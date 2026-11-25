"use client";

import { useEffect, useState } from "react";

export type User = { id: string; email: string; name: string; created_at: number };

const TOKEN = "aurea_token";
const USER = "aurea_user";
const EVENT = "aurea-auth";

function read<T>(key: string): T | null {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : null;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return read<string>(TOKEN);
}

export function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

const reportTokenKey = (id: string) => `facemetric_ai_rt_${id}`;
const legacyReportTokenKey = (id: string) => `alexendra_rt_${id}`;

/** The per-report access token returned once by /api/analyze. Kept only in this browser. */
export function saveReportToken(id: string, token: string) {
  try {
    localStorage.setItem(reportTokenKey(id), token);
    localStorage.removeItem(legacyReportTokenKey(id));
  } catch { /* private mode: report still opens via sign-in */ }
}

export function forgetReportToken(id: string) {
  try {
    localStorage.removeItem(reportTokenKey(id));
    localStorage.removeItem(legacyReportTokenKey(id));
  } catch { /* ignore */ }
}

/** Credentials for one report: the signed-in session and/or this report's access token. */
export function reportHeaders(id: string, extra: Record<string, string> = {}): Record<string, string> {
  let t: string | null = null;
  try {
    t = localStorage.getItem(reportTokenKey(id));
    if (!t) {
      t = localStorage.getItem(legacyReportTokenKey(id));
      if (t) {
        localStorage.setItem(reportTokenKey(id), t);
        localStorage.removeItem(legacyReportTokenKey(id));
      }
    }
  } catch { /* ignore */ }
  return { ...authHeaders(), ...(t ? { "X-Report-Token": t } : {}), ...extra };
}

export function setSession(token: string, user: User) {
  localStorage.setItem(TOKEN, JSON.stringify(token));
  localStorage.setItem(USER, JSON.stringify(user));
  window.dispatchEvent(new Event(EVENT));
}

export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST", headers: authHeaders() }).catch(() => {});
  localStorage.removeItem(TOKEN);
  localStorage.removeItem(USER);
  window.dispatchEvent(new Event(EVENT));
}

/** The signed-in user (from localStorage), kept in sync across tabs. `undefined` until mounted. */
export function useUser(): User | null | undefined {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => {
    const sync = () => setUser(getToken() ? read<User>(USER) : null);
    sync();
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return user;
}
