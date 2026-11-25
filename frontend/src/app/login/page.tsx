"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { setSession } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mode === "signup" ? form : { email: form.email, password: form.password }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Something went wrong.");
      setSession(body.token, body.user);
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next && next.startsWith("/") ? next : "/account");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <main className="mx-auto max-w-md px-5 py-16">
      <h1 className="font-serif text-4xl tracking-tight">{mode === "login" ? "Welcome back" : "Create your account"}</h1>
      <p className="mt-3 text-muted">
        Save every analysis and see how your skin and hair change over time — retake a photo every few weeks to track progress.
      </p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        {mode === "signup" && (
          <label className="block space-y-2">
            <span className="text-sm font-medium">First name</span>
            <input className="input" value={form.name} onChange={set("name")} autoComplete="given-name" />
          </label>
        )}
        <label className="block space-y-2">
          <span className="text-sm font-medium">Email</span>
          <input className="input" type="email" required value={form.email} onChange={set("email")} autoComplete="email" />
        </label>
        <label className="block space-y-2">
          <span className="text-sm font-medium">Password</span>
          <input className="input" type="password" required minLength={mode === "signup" ? 8 : undefined} value={form.password}
            onChange={set("password")} autoComplete={mode === "signup" ? "new-password" : "current-password"} />
        </label>
        {error && <p className="rounded-xl bg-bad/10 p-3 text-sm text-bad">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
      <p className="mt-6 text-sm text-muted">
        {mode === "login" ? "New here? " : "Already have an account? "}
        <button className="font-medium text-accent hover:underline" onClick={() => { setMode(mode === "login" ? "signup" : "login"); setError(null); }}>
          {mode === "login" ? "Create an account" : "Sign in"}
        </button>
      </p>
    </main>
  );
}
