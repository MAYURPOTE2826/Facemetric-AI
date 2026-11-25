"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Slider } from "@/components/BeforeAfter";
import { authHeaders, reportHeaders, signOut, useUser } from "@/lib/auth";
import type { Analysis } from "@/lib/types";

type Checkin = {
  id: string; created_at: number; paid: boolean; harmony_score: number | null; skin_score: number | null;
  hair_score: number | null; concerns: Record<string, { label: string; score: number }>; face_shape: string | null; photo: string;
  aligned?: string;
};
type HairChange = { key: string; label: string; from: number; to: number; change: number; unit: string; real: boolean; better: boolean | null };
type RoutineCheckin = { analysis_id: string; days_since: number; due_in_days: number; due: boolean; overdue: boolean; due_at: number; last: unknown };
type Progress = {
  checkins: Checkin[];
  changes: null | {
    days: number; skin_score: number | null; hair_score: number | null; harmony_score: number | null;
    concerns: { key: string; label: string; from: number; to: number; change: number | null }[];
    hair?: HairChange[]; comparability?: string[];
    hair_visible?: { status: string; text?: string; reasons?: string[]; note?: string };
  };
  routine_checkin?: RoutineCheckin | null;
};

const fmtDate = (t: number) => new Date(t * 1000).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export default function AccountPage() {
  const router = useRouter();
  const user = useUser();
  const [data, setData] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user === undefined) return;
    if (user === null) {
      router.replace("/login?next=/account");
      return;
    }
    fetch("/api/me/progress", { headers: authHeaders() })
      .then(async (res) => {
        if (res.status === 401) {
          await signOut();
          router.replace("/login?next=/account");
          return;
        }
        setData(await res.json());
      })
      .catch(() => setError("Could not reach the server."));
  }, [user, router]);

  async function clearAll() {
    if (!window.confirm("Delete ALL your check-ins and every photo and report in this account? This cannot be undone.")) return;
    if (window.prompt('Type DELETE to confirm') !== "DELETE") return;
    const res = await fetch("/api/me/progress/clear", {
      method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() }, body: JSON.stringify({ confirm: "DELETE" }),
    });
    if (res.ok) setData({ ...(data as Progress), checkins: [], changes: null, routine_checkin: null });
    else setError("Could not clear your progress. Please try again.");
  }

  if (!user || !data) return <main className="mx-auto max-w-3xl px-5 py-20 text-center text-muted">{error ?? "Loading…"}</main>;
  const { checkins, changes } = data;
  const latest = checkins[checkins.length - 1];
  const daysSince = latest ? Math.floor((Date.now() / 1000 - latest.created_at) / 86400) : 0;

  return (
    <main className="mx-auto max-w-6xl px-5 py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.2em] text-accent">{user.name || user.email}</p>
          <h1 className="mt-2 font-serif text-4xl tracking-tight md:text-5xl">Your progress</h1>
        </div>
        <div className="flex gap-2">
          <Link href="/analyze" className="btn-primary">New check-in</Link>
          <button className="btn-secondary" data-testid="clear-progress" onClick={clearAll}>Clear all my progress</button>
          <button className="btn-secondary" onClick={() => signOut().then(() => router.push("/"))}>Sign out</button>
        </div>
      </div>

      {checkins.length === 0 && (
        <section className="mt-10 rounded-3xl border border-line bg-surface p-8 text-center">
          <p className="font-serif text-2xl">No check-ins yet</p>
          <p className="mx-auto mt-2 max-w-md text-muted">Do your first analysis while signed in — then retake it every 4-6 weeks in the same light to see what&apos;s changing.</p>
          <Link href="/analyze" className="btn-primary mt-6 inline-block">Start your first check-in</Link>
        </section>
      )}

      {checkins.length > 0 && daysSince >= 28 && (
        <p className="mt-6 rounded-2xl bg-accent-soft/60 p-4 text-sm">
          It&apos;s been {daysSince} days since your last check-in — a good time to retake your photo and see how your routine is working.
        </p>
      )}

      {changes && (
        <section className="mt-10 grid gap-4 sm:grid-cols-3">
          <Delta label="Skin score" value={changes.skin_score} days={changes.days} />
          <Delta label="Hair score" value={changes.hair_score} days={changes.days} />
          <div className="rounded-3xl border border-line bg-surface p-6">
            <p className="text-sm text-muted">Check-ins</p>
            <p className="mt-1 font-serif text-4xl">{checkins.length}</p>
            <p className="text-xs text-muted">over {changes.days} days</p>
          </div>
        </section>
      )}

      {changes?.hair_visible && changes.hair_visible.status !== "not_available" && (
        <p className="mt-4 rounded-xl bg-surface p-3 text-sm" data-testid="hair-longitudinal-result">
          <b>Visible hairline, first vs latest:</b>{" "}
          {changes.hair_visible.text ?? `Not compared - ${(changes.hair_visible.reasons ?? []).join(" ")}`}{" "}
          <span className="text-xs text-muted">{changes.hair_visible.note}</span>
        </p>
      )}

      {checkins.length >= 2 && (
        <section className="mt-6 grid gap-4 md:grid-cols-2">
          <TrendChart title="Skin score" points={checkins.map((c) => ({ t: c.created_at, v: c.skin_score }))} />
          <TrendChart title="Hair score" points={checkins.map((c) => ({ t: c.created_at, v: c.hair_score }))} />
        </section>
      )}

      {data.routine_checkin && (
        <RoutineCheckinCard c={data.routine_checkin} onDone={() => setData({ ...data, routine_checkin: { ...data.routine_checkin!, due: false, last: true } })} />
      )}

      {checkins.length >= 2 && checkins[0].aligned && latest.aligned && (
        <section className="mt-6 grid gap-6 rounded-3xl border border-line bg-surface p-6 md:grid-cols-[minmax(0,360px)_1fr]">
          <Slider before={`data:image/jpeg;base64,${checkins[0].aligned}`} after={`data:image/jpeg;base64,${latest.aligned}`}
            beforeLabel={fmtDate(checkins[0].created_at)} afterLabel={fmtDate(latest.created_at)} />
          <div>
            <h2 className="font-semibold">First vs latest photo, lined up</h2>
            <p className="mt-1 text-xs text-muted">Both photos are scaled and rotated so your eyes sit in the same place — drag to compare.</p>
            {changes?.hair && changes.hair.length > 0 && (
              <ul className="mt-4 space-y-2 text-sm">
                {changes.hair.map((h) => (
                  <li key={h.key} className="flex items-baseline justify-between gap-3">
                    <span>{h.label}</span>
                    <span className="tabular-nums text-muted">
                      {h.from} → {h.to} {h.unit}{" "}
                      {!h.real ? <span className="rounded-full bg-line px-2 py-0.5 text-xs">● no real change</span>
                        : h.better ? <span className="rounded-full bg-good/10 px-2 py-0.5 text-xs text-good">better</span>
                        : <span className="rounded-full bg-bad/10 px-2 py-0.5 text-xs text-bad">worse</span>}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-3 text-xs text-muted">&quot;No real change&quot; means the difference is within what two photos taken on the same day would show.</p>
            {changes?.comparability?.map((n) => <p key={n} className="mt-3 rounded-xl bg-warn/10 p-3 text-xs text-warn">{n}</p>)}
          </div>
        </section>
      )}

      {changes && changes.concerns.length > 0 && (
        <section className="mt-6 rounded-3xl border border-line bg-surface p-6">
          <h2 className="font-semibold">Skin concerns — first vs latest check-in</h2>
          <p className="mt-1 text-xs text-muted">Higher is better. Small changes (±3) are usually lighting, not your skin.</p>
          <ul className="mt-4 grid gap-x-8 gap-y-3 md:grid-cols-2">
            {changes.concerns.map((c) => (
              <li key={c.key} className="flex items-baseline justify-between gap-3 text-sm">
                <span>{c.label}</span>
                <span className="tabular-nums text-muted">
                  {Math.round(c.from)} → {Math.round(c.to)}{" "}
                  <ChangeBadge v={c.change} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {checkins.length > 0 && (
        <section className="mt-10">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-serif text-3xl tracking-tight">All check-ins</h2>
            <button className="btn-secondary" data-testid="clear-progress-checkins" onClick={clearAll}>Delete all check-ins</button>
          </div>
          <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[...checkins].reverse().map((c) => (
              <Link key={c.id} href={`/report/${c.id}`} className="overflow-hidden rounded-3xl border border-line bg-surface hover:border-accent">
                {c.photo && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`data:image/jpeg;base64,${c.photo}`} alt={`Check-in on ${fmtDate(c.created_at)}`} className="aspect-square w-full object-cover" />
                )}
                <div className="p-4 text-sm">
                  <p className="font-medium">{fmtDate(c.created_at)}</p>
                  <p className="mt-1 text-muted">
                    Skin {c.skin_score != null ? Math.round(c.skin_score) : "—"} · Hair {c.hair_score ?? "—"}
                    {c.face_shape ? ` · ${c.face_shape}` : ""}
                  </p>
                  <p className="mt-1 text-xs text-accent">{c.paid ? "Full report" : "Preview"} →</p>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

function ChangeBadge({ v }: { v: number | null }) {
  if (v == null) return null;
  if (Math.abs(v) < 3) return <span className="rounded-full bg-line px-2 py-0.5 text-xs">● steady</span>;
  return v > 0
    ? <span className="rounded-full bg-good/10 px-2 py-0.5 text-xs text-good">▲ {v.toFixed(0)}</span>
    : <span className="rounded-full bg-bad/10 px-2 py-0.5 text-xs text-bad">▼ {Math.abs(v).toFixed(0)}</span>;
}

function Delta({ label, value, days }: { label: string; value: number | null; days: number }) {
  return (
    <div className="rounded-3xl border border-line bg-surface p-6">
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-1 font-serif text-4xl tabular-nums">
        {value == null ? "—" : `${value > 0 ? "+" : ""}${Math.round(value)}`}
      </p>
      <p className="text-xs text-muted">{value == null ? "Not measured in both check-ins" : `since your first check-in ${days} days ago`}</p>
    </div>
  );
}

/** Single-series line chart on a fixed 0-100 scale; hover a point for its value. */
function TrendChart({ title, points }: { title: string; points: { t: number; v: number | null }[] }) {
  const pts = points.filter((p): p is { t: number; v: number } => p.v != null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 520, H = 200, L = 32, R = 16, T = 16, B = 28;
  if (pts.length < 2)
    return (
      <div className="rounded-3xl border border-line bg-surface p-6">
        <h3 className="font-semibold">{title}</h3>
        <p className="mt-6 text-sm text-muted">Needs two check-ins with this measured.</p>
      </div>
    );
  const t0 = pts[0].t, t1 = pts[pts.length - 1].t || t0 + 1;
  const x = (t: number) => L + ((t - t0) / Math.max(t1 - t0, 1)) * (W - L - R);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  const last = pts[pts.length - 1];
  const h = hover != null ? pts[hover] : null;
  return (
    <div className="rounded-3xl border border-line bg-surface p-6">
      <h3 className="font-semibold">{title}</h3>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-3 w-full" role="img" aria-label={`${title} over time`}>
        {[0, 50, 100].map((g) => (
          <g key={g}>
            <line x1={L} x2={W - R} y1={y(g)} y2={y(g)} stroke="var(--line)" strokeWidth="1" />
            <text x={L - 6} y={y(g)} textAnchor="end" dominantBaseline="middle" fontSize="11" fill="var(--muted)">{g}</text>
          </g>
        ))}
        <text x={L} y={H - 6} fontSize="11" fill="var(--muted)">{fmtDate(t0)}</text>
        <text x={W - R} y={H - 6} fontSize="11" fill="var(--muted)" textAnchor="end">{fmtDate(t1)}</text>
        <polyline fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinejoin="round"
          points={pts.map((p) => `${x(p.t)},${y(p.v)}`).join(" ")} />
        {h && <line x1={x(h.t)} x2={x(h.t)} y1={T} y2={H - B} stroke="var(--muted)" strokeWidth="1" strokeDasharray="3 3" />}
        {pts.map((p, i) => (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <circle cx={x(p.t)} cy={y(p.v)} r="14" fill="transparent" />
            <circle cx={x(p.t)} cy={y(p.v)} r="4.5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2" />
          </g>
        ))}
        <text x={x(last.t) - 8} y={y(last.v) - 10} textAnchor="end" fontSize="12" fill="var(--foreground)">{Math.round(last.v)}</text>
        {h && (
          <g pointerEvents="none">
            <rect x={Math.min(x(h.t) + 8, W - 130)} y={T} width="120" height="36" rx="6" fill="var(--foreground)" />
            <text x={Math.min(x(h.t) + 16, W - 122)} y={T + 15} fontSize="11" fill="var(--background)">{fmtDate(h.t)}</text>
            <text x={Math.min(x(h.t) + 16, W - 122)} y={T + 29} fontSize="12" fill="var(--background)">{title}: {Math.round(h.v)}</text>
          </g>
        )}
      </svg>
    </div>
  );
}

const STEP_LABELS: Record<string, string> = {
  niacinamide: "Niacinamide serum", vitamin_c: "Vitamin C serum", salicylic: "Salicylic acid", azelaic: "Azelaic acid",
  pigment: "Alpha arbutin / tranexamic serum", retinol: "Retinol", lactic: "Lactic acid", spot: "Spot treatment", eye: "Under-eye cream",
};

function icsReminder(dueAt: number) {
  const d = new Date(dueAt * 1000);
  const day = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  const ics = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Facemetric-AI//Check-in//EN", "BEGIN:VEVENT",
    `UID:checkin-${dueAt}@aurea`, `DTSTART;VALUE=DATE:${day}`, `DTEND;VALUE=DATE:${day}`,
    "SUMMARY:Facemetric-AI skin check-in", "DESCRIPTION:Retake your photo in the same light and tell us how your routine is going.",
    "END:VEVENT", "END:VCALENDAR"].join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
  a.download = "aurea-checkin.ics";
  a.click();
}

/** 6-8 week routine check-in: answers adjust the routine on the latest report. */
function RoutineCheckinCard({ c, onDone }: { c: RoutineCheckin; onDone: () => void }) {
  const [open, setOpen] = useState(c.due);
  const [steps, setSteps] = useState<string[]>([]);
  const [irritation, setIrritation] = useState<boolean | null>(null);
  const [irritating, setIrritating] = useState<string[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const [consistency, setConsistency] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!open) return;
    fetch(`/api/analyses/${c.analysis_id}`, { headers: reportHeaders(c.analysis_id) })
      .then((r) => r.json())
      .then((a: Analysis) => {
        const kinds = [...(a.routine?.am ?? []), ...(a.routine?.pm ?? [])]
          .map((st) => st.kind)
          .filter((k): k is string => !!k && k in STEP_LABELS);
        setSteps([...new Set(kinds)]);
      })
      .catch(() => setSteps([]));
  }, [open, c.analysis_id]);

  async function submit() {
    setBusy(true);
    const res = await fetch("/api/me/checkin", {
      method: "POST", headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ analysis_id: c.analysis_id, irritation, irritating, progress, consistency }),
    }).catch(() => null);
    setBusy(false);
    if (res?.ok) {
      setDone(true);
      onDone();
    }
  }

  const chip = (on: boolean, label: string, onClick: () => void) => (
    <button key={label} type="button" onClick={onClick} className={`chip ${on ? "chip-on" : ""}`}>{label}</button>
  );

  if (done)
    return (
      <section className="mt-6 rounded-3xl border border-good/30 bg-good/5 p-6">
        <p className="font-semibold text-good">Thanks — your routine has been updated.</p>
        <p className="mt-1 text-sm">
          See the changes in your <Link className="underline" href={`/report/${c.analysis_id}`}>latest report</Link>, then{" "}
          <Link className="underline" href="/analyze">retake your photo</Link> in the same light to track progress.
        </p>
      </section>
    );
  return (
    <section className="mt-6 rounded-3xl border border-line bg-surface p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h2 className="font-semibold">{c.due ? "Your 6-week routine check-in is due" : "Routine check-in"}</h2>
          <p className="mt-1 text-sm text-muted">
            {c.due ? "Two minutes: tell us how it\u2019s going and we\u2019ll adjust your routine."
              : c.last ? "Thanks for checking in. You can update your answers any time."
              : `Due in ${c.due_in_days} days (6-8 weeks after your last analysis).`}
          </p>
        </div>
        <div className="flex gap-2">
          {!c.due && c.due_in_days > 0 && <button className="btn-secondary" onClick={() => icsReminder(c.due_at)}>Add reminder to calendar</button>}
          {!open && <button className="btn-secondary" onClick={() => setOpen(true)}>Check in now</button>}
        </div>
      </div>
      {open && (
        <div className="mt-5 space-y-4 text-sm">
          <div>
            <p className="font-medium">Did anything sting, burn, peel a lot or cause breakouts?</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {chip(irritation === false, "No", () => { setIrritation(false); setIrritating([]); })}
              {chip(irritation === true, "Yes", () => setIrritation(true))}
            </div>
          </div>
          {irritation && (
            <div>
              <p className="font-medium">Which one? (skip if you&apos;re not sure — we&apos;ll pause all treatments)</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {steps.map((k) => chip(irritating.includes(k), STEP_LABELS[k],
                  () => setIrritating((x) => (x.includes(k) ? x.filter((y) => y !== k) : [...x, k]))))}
              </div>
            </div>
          )}
          <div>
            <p className="font-medium">How is your skin compared with when you started?</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {([["better", "Better"], ["same", "About the same"], ["worse", "Worse"]] as const).map(([k, l]) => chip(progress === k, l, () => setProgress(k)))}
            </div>
          </div>
          <div>
            <p className="font-medium">How often did you use the routine?</p>
            <div className="mt-2 flex flex-wrap gap-2">
              {([["daily", "Almost every day"], ["sometimes", "Sometimes"], ["stopped", "I stopped"]] as const).map(([k, l]) => chip(consistency === k, l, () => setConsistency(k)))}
            </div>
          </div>
          <button className="btn-primary" disabled={busy || irritation === null || !progress} onClick={submit}>
            {busy ? "Saving…" : "Update my routine"}
          </button>
        </div>
      )}
    </section>
  );
}
