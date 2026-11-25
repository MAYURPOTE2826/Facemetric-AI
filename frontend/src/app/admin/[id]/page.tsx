"use client";

import Link from "next/link";
import { use, useEffect, useState } from "react";
import { AdminAuthError, adminFetch } from "@/lib/admin";
import type { Analysis, Recommendation, Report } from "@/lib/types";

type FullAnalysis = Analysis & {
  review_status: string;
  reviewer_note?: string;
  candidates: (Recommendation & { feature: string })[];
};

const TYPES = ["grooming", "makeup", "skincare", "lifestyle", "professional"];
const lines = (s: string) => s.split("\n").map((l) => l.trim()).filter(Boolean);

export default function AdminEditor({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [data, setData] = useState<FullAnalysis | null>(null);
  const [rep, setRep] = useState<Report | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [dirty, setDirty] = useState(false);

  function apply(d: FullAnalysis) {
    setData(d);
    setRep(structuredClone(d.report));
    setNote(d.reviewer_note ?? "");
    setDirty(false);
  }

  useEffect(() => {
    adminFetch<FullAnalysis>(`/analyses/${id}`)
      .then(apply)
      .catch((e) => setMsg({ ok: false, text: e instanceof AdminAuthError ? "Not signed in — go back to /admin." : String(e.message) }));
  }, [id]);

  const edit = (fn: (r: Report) => void) => {
    setRep((r) => {
      if (!r) return r;
      const next = structuredClone(r);
      fn(next);
      return next;
    });
    setDirty(true);
  };

  async function run(label: string, path: string, method: string, body?: unknown) {
    setBusy(label);
    setMsg(null);
    try {
      const d = await adminFetch<FullAnalysis>(path, { method, body: body ? JSON.stringify(body) : undefined });
      apply(d);
      setMsg({ ok: true, text: `${label} ✓` });
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy(null);
    }
  }

  const save = () => run("Saved", `/analyses/${id}/report`, "PUT", { report: rep, reviewer_note: note });
  async function saveAndApprove() {
    if (dirty) await save();
    await run("Approved & released", `/analyses/${id}/approve`, "POST");
  }

  if (!data || !rep) return <main className="mx-auto max-w-6xl px-5 py-16 text-muted">{msg?.text ?? "Loading…"}</main>;

  return (
    <main className="mx-auto max-w-7xl px-5 py-8">
      <div className="sticky top-0 z-10 -mx-5 mb-6 flex flex-wrap items-center justify-between gap-3 border-b border-line bg-background/95 px-5 py-3 backdrop-blur">
        <div className="flex items-center gap-3">
          <Link href="/admin" className="text-sm text-muted hover:text-foreground">← Reports</Link>
          <span className="font-medium">{data.profile.name || "Client"} · {data.id}</span>
          <span className="rounded-full bg-line px-2.5 py-0.5 text-xs">{data.paid ? data.review_status : "unpaid"}</span>
          <span className="rounded-full bg-line px-2.5 py-0.5 text-xs">source: {data.report_source}</span>
          {dirty && <span className="text-xs text-warn">unsaved changes</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          <a href={`/report/${data.id}`} target="_blank" className="btn-secondary !py-2 text-sm">View as client</a>
          <button className="btn-secondary !py-2 text-sm" disabled={!!busy}
            onClick={() => confirm("Replace the report with a newly generated one?") && run("Regenerated", `/analyses/${id}/regenerate`, "POST")}>
            {busy === "Regenerated" ? "Writing…" : "Regenerate"}
          </button>
          <button className="btn-secondary !py-2 text-sm" disabled={!!busy || !dirty} onClick={save}>Save</button>
          <button className="btn-primary !py-2 text-sm" disabled={!!busy || !data.paid} onClick={saveAndApprove}>
            {data.review_status === "approved" ? "Save & keep approved" : "Approve & release"}
          </button>
        </div>
      </div>
      {msg && <p className={`mb-4 rounded-xl p-3 text-sm ${msg.ok ? "bg-good/10 text-good" : "bg-bad/10 text-bad"}`}>{msg.text}</p>}

      <div className="grid gap-8 lg:grid-cols-[380px_1fr]">
        {/* Left: evidence */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <div className="grid grid-cols-2 gap-2">
            {[data.annotated_image, data.profile_image, data.three_quarter_image].filter(Boolean).map((img, i) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={i} src={`data:image/jpeg;base64,${img}`} alt="" className="w-full rounded-xl border border-line" />
            ))}
          </div>
          <div className="rounded-2xl border border-line bg-surface p-4 text-sm">
            <p className="font-semibold">Client</p>
            <p className="mt-1 text-muted">
              {[data.profile.age && `${data.profile.age} y`, data.profile.sex, data.profile.ethnicity, data.profile.budget].filter(Boolean).join(" · ")}
            </p>
            {data.profile.goals?.length > 0 && <p className="mt-1">Goals: {data.profile.goals.join(", ")}</p>}
            {data.profile.notes && <p className="mt-1 italic">“{data.profile.notes}”</p>}
          </div>
          <div className="max-h-[45vh] overflow-auto rounded-2xl border border-line bg-surface p-4">
            <p className="mb-2 text-sm font-semibold">Measurements · harmony {data.harmony_score}</p>
            <table className="w-full text-xs">
              <tbody>
                {data.metrics.map((m) => (
                  <tr key={m.key} className="border-b border-line last:border-0">
                    <td className="py-1.5 pr-2">{m.label}</td>
                    <td className="py-1.5 pr-2 tabular-nums">{m.value}{m.unit === "°" ? "°" : ""}</td>
                    <td className={`py-1.5 ${m.status === "ideal" ? "text-good" : m.status === "near" ? "text-warn" : "text-bad"}`}>{m.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>

        {/* Right: editable report */}
        <div className="space-y-6">
          <Field label="Note from your specialist (shown at the top of the client's report)">
            <textarea className="input min-h-20" value={note} placeholder="e.g. Great bone structure — focus on skin and brows first."
              onChange={(e) => { setNote(e.target.value); setDirty(true); }} />
          </Field>
          <Field label="Headline">
            <input className="input" value={rep.headline} onChange={(e) => edit((r) => { r.headline = e.target.value; })} />
          </Field>
          <Field label="Overview">
            <textarea className="input min-h-28" value={rep.overview} onChange={(e) => edit((r) => { r.overview = e.target.value; })} />
          </Field>
          <div className="grid gap-6 md:grid-cols-2">
            <Field label="Strengths (one per line)">
              <textarea className="input min-h-32" value={rep.strengths.join("\n")} onChange={(e) => edit((r) => { r.strengths = lines(e.target.value); })} />
            </Field>
            <Field label="90-day plan (one step per line)">
              <textarea className="input min-h-32" value={rep.priority_plan.join("\n")} onChange={(e) => edit((r) => { r.priority_plan = lines(e.target.value); })} />
            </Field>
          </div>

          <div className="flex items-center justify-between">
            <h2 className="font-serif text-2xl">Sections</h2>
            <button className="btn-secondary !py-2 text-sm"
              onClick={() => edit((r) => { r.sections.push({ feature: "New section", summary: "", observations: [], recommendations: [] }); })}>
              + Add section
            </button>
          </div>
          {rep.sections.map((s, si) => (
            <div key={si} className="space-y-3 rounded-2xl border border-line bg-surface p-5">
              <div className="flex gap-2">
                <input className="input font-semibold" value={s.feature} onChange={(e) => edit((r) => { r.sections[si].feature = e.target.value; })} />
                <button className="btn-secondary !px-3 !py-2 text-xs" disabled={si === 0}
                  onClick={() => edit((r) => { [r.sections[si - 1], r.sections[si]] = [r.sections[si], r.sections[si - 1]]; })}>↑</button>
                <button className="btn-secondary !px-3 !py-2 text-xs text-bad"
                  onClick={() => edit((r) => { r.sections.splice(si, 1); })}>Delete</button>
              </div>
              <textarea className="input min-h-16 text-sm" placeholder="Summary" value={s.summary}
                onChange={(e) => edit((r) => { r.sections[si].summary = e.target.value; })} />
              <textarea className="input min-h-16 text-sm" placeholder="Observations (one per line)" value={s.observations.join("\n")}
                onChange={(e) => edit((r) => { r.sections[si].observations = lines(e.target.value); })} />
              <div className="space-y-2">
                {s.recommendations.map((rec, ri) => (
                  <div key={ri} className="grid gap-2 rounded-xl border border-line p-3 md:grid-cols-[1fr_140px_70px_150px_auto]">
                    <input className="input !py-1.5 text-sm" value={rec.title} onChange={(e) => edit((r) => { r.sections[si].recommendations[ri].title = e.target.value; })} />
                    <select className="input !py-1.5 text-sm" value={rec.type} onChange={(e) => edit((r) => { r.sections[si].recommendations[ri].type = e.target.value; })}>
                      {TYPES.map((t) => <option key={t}>{t}</option>)}
                    </select>
                    <input className="input !py-1.5 text-sm" value={rec.cost} onChange={(e) => edit((r) => { r.sections[si].recommendations[ri].cost = e.target.value; })} />
                    <input className="input !py-1.5 text-sm" value={rec.timeline} onChange={(e) => edit((r) => { r.sections[si].recommendations[ri].timeline = e.target.value; })} />
                    <button className="text-xs text-bad" onClick={() => edit((r) => { r.sections[si].recommendations.splice(ri, 1); })}>Remove</button>
                    <textarea className="input min-h-14 text-sm md:col-span-5" value={rec.detail}
                      onChange={(e) => edit((r) => { r.sections[si].recommendations[ri].detail = e.target.value; })} />
                  </div>
                ))}
                <AddFromLibrary candidates={data.candidates}
                  onAdd={(c) => edit((r) => { r.sections[si].recommendations.push({ title: c.title, type: c.type, detail: c.detail, cost: c.cost, timeline: c.timeline }); })} />
              </div>
            </div>
          ))}
          <Field label="Disclaimer">
            <input className="input text-sm" value={rep.disclaimer} onChange={(e) => edit((r) => { r.disclaimer = e.target.value; })} />
          </Field>
        </div>
      </div>
    </main>
  );
}

function AddFromLibrary({ candidates, onAdd }: { candidates: FullAnalysis["candidates"]; onAdd: (c: FullAnalysis["candidates"][number]) => void }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex gap-2">
      <select className="input !py-1.5 text-sm" value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">+ Add a recommendation from the method library…</option>
        {candidates.map((c, i) => <option key={i} value={i}>{c.feature}: {c.title}</option>)}
        <option value="blank">Blank recommendation</option>
      </select>
      <button className="btn-secondary !py-1.5 text-sm" disabled={!value}
        onClick={() => {
          onAdd(value === "blank" ? { feature: "", title: "New recommendation", type: "lifestyle", detail: "", cost: "$", timeline: "" } : candidates[Number(value)]);
          setValue("");
        }}>Add</button>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-sm font-medium">{label}</span>
      {children}
    </label>
  );
}
