"use client";

const KEY = "aurea-admin-token";

export function getToken(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string) {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable */
  }
}

export class AdminAuthError extends Error {}

export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api/admin${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", "X-Admin-Token": getToken(), ...(init.headers ?? {}) },
  });
  if (res.status === 401 || res.status === 503) {
    const body = await res.json().catch(() => ({}));
    throw new AdminAuthError(body.detail ?? "Not authorised");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status})`);
  }
  return res.json();
}

export type AdminRow = {
  id: string;
  created_at: number;
  name: string;
  age: string;
  sex: string;
  goals: string[];
  paid: boolean;
  review_status: "unpaid" | "pending" | "approved" | "not_required";
  harmony_score: number;
  report_source: string;
  photos: string[];
};
