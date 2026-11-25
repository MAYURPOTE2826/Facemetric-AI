"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AdminAuthError, adminFetch, getToken, setToken, type AdminRow } from "@/lib/admin";

const FILTERS = [
  ["pending", "Needs review"],
  ["paid", "Paid"],
  ["unpaid", "Unpaid"],
  ["all", "All"],
] as const;

const STATUS_STYLE: Record<AdminRow["review_status"], string> = {
  pending: "bg-warn/15 text-warn",
  approved: "bg-good/15 text-good",
  not_required: "bg-line text-muted",
  unpaid: "bg-line text-muted",
};
const STATUS_LABEL: Record<AdminRow["review_status"], string> = {
  pending: "Needs review",
  approved: "Approved",
  not_required: "Released",
  unpaid: "Unpaid",
};

export default function AdminPage() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number][0]>("pending");
  const [rows, setRows] = useState<AdminRow[] | null>(null);
  const [reviewRequired, setReviewRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const d = await adminFetch<{ items: AdminRow[]; review_required: boolean }>(`/analyses?status=${filter}`);
      setRows(d.items);
      setReviewRequired(d.review_required);
      setAuthed(true);
      setError(null);
    } catch (e) {
      if (e instanceof AdminAuthError) {
        setAuthed(false);
        if (getToken()) setError(e.message);
      } else setError(e instanceof Error ? e.message : "Failed to load");
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  if (authed === false)
    return (
      <main className="mx-auto max-w-sm px-5 py-24">
        <h1 className="font-serif text-3xl">Specialist login</h1>
        <form
          className="mt-6 space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            setToken(tokenInput.trim());
            load();
          }}
        >
          <input className="input" type="password" placeholder="Admin token" value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)} autoFocus />
          <button className="btn-primary w-full">Sign in</button>
          {error && <p className="text-sm text-bad">{error}</p>}
        </form>
      </main>
    );

  return (
    <main className="mx-auto max-w-6xl px-5 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.2em] text-accent">Specialist dashboard</p>
          <h1 className="mt-1 font-serif text-4xl">Reports</h1>
          <p className="mt-1 text-sm text-muted">
            Review is {reviewRequired ? "required — paid reports wait for your approval" : "optional — paid reports release instantly; you can still edit them"}.
          </p>
        </div>
        <button className="btn-secondary" onClick={() => { setToken(""); setAuthed(false); setRows(null); }}>Sign out</button>
      </div>

      <div className="mt-6 flex flex-wrap gap-2">
        {FILTERS.map(([k, label]) => (
          <button key={k} onClick={() => setFilter(k)} className={`chip ${filter === k ? "chip-on" : ""}`}>{label}</button>
        ))}
      </div>

      {error && <p className="mt-4 text-sm text-bad">{error}</p>}
      {!rows ? (
        <p className="mt-10 text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="mt-10 text-muted">Nothing here.</p>
      ) : (
        <div className="mt-6 overflow-x-auto rounded-2xl border border-line bg-surface">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-3">Date</th>
                <th className="px-4 py-3">Client</th>
                <th className="px-4 py-3">Photos</th>
                <th className="px-4 py-3">Score</th>
                <th className="px-4 py-3">Report</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0 hover:bg-background">
                  <td className="whitespace-nowrap px-4 py-3">{new Date(r.created_at * 1000).toLocaleString()}</td>
                  <td className="px-4 py-3">
                    <div className="font-medium">{r.name || "—"}</div>
                    <div className="text-xs text-muted">{[r.age, r.sex].filter(Boolean).join(" · ")}</div>
                  </td>
                  <td className="px-4 py-3 text-xs">{r.photos.join(", ")}</td>
                  <td className="px-4 py-3 tabular-nums">{r.harmony_score}</td>
                  <td className="px-4 py-3 text-xs">{r.report_source}</td>
                  <td className="px-4 py-3">
                    <span className={`rounded-full px-2.5 py-1 text-xs ${STATUS_STYLE[r.review_status]}`}>{STATUS_LABEL[r.review_status]}</span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Link href={`/admin/${r.id}`} className="font-medium text-accent hover:underline">Open →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
