"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";
import { Previews, Slider } from "@/components/BeforeAfter";
import { CountdownSection, RemediesSection, RoutineSection } from "@/components/IndiaSections";
import { ClimateCard, HairSection, StyleSection } from "@/components/LifestyleSections";
import { forgetReportToken, reportHeaders, useUser } from "@/lib/auth";
import { ShareButton } from "@/components/ShareCard";
import { TryOnPanel } from "@/components/TryOn";
import { MedicalSection } from "@/components/MedicalSection";
import { EyesBrows, MeasurementTable, ProportionFigures, SymmetryFigures } from "@/components/ReportFigures";
import type { Analysis, Metric } from "@/lib/types";

const CATEGORY_LABELS: Record<string, string> = {
  eyes: "Eyes", proportions: "Proportions", lips: "Lips & mouth", nose: "Nose", jaw: "Jaw", symmetry: "Symmetry",
  profile: "Side profile",
};
const TYPE_STYLES: Record<string, string> = {
  grooming: "bg-[#e8eef6] text-[#2f5b8a]",
  makeup: "bg-[#f6e8ef] text-[#8a2f5b]",
  skincare: "bg-[#e8f4ec] text-[#2f7a4c]",
  lifestyle: "bg-[#f5f0e1] text-[#7d6420]",
  professional: "bg-[#f1e6e1] text-[#8a3f2f]",
};

// Evidence keys that aren't measurements or skin concerns.
const EVIDENCE_LABELS: Record<string, string> = {
  skin_tone: "Skin tone group", neck: "Neck vs face", hairline: "Hairline", crown: "Top of head",
  hair_answers: "Your hair answers", face_shape: "Face shape", goals: "Your goals", routine: "Your routine",
  climate: "City & season",
};

function evidenceLabel(data: Analysis, key: string): string {
  const m = data.metrics.find((x) => x.key === key);
  if (m) return `${m.label}: ${m.value}${m.unit === "°" ? "°" : ""}`;
  const c = data.skin.concerns?.find((x) => x.key === key);
  if (c) return `${c.label}: ${Math.round(c.score)}/100`;
  return EVIDENCE_LABELS[key] ?? key.replace(/_/g, " ");
}


// Which simulated photo best illustrates a report section's recommendations.
const PREVIEW_FOR_METRIC: Record<string, string> = {
  canthal_tilt: "brows", nasofrontal: "brows", eye_aspect: "brows", intercanthal_eye: "brows",
  jaw_zygo: "jaw", gonial_angle: "jaw", cervicomental: "jaw", mentocervical: "jaw", submental_length: "jaw",
  lip_ratio: "lips",
};
const PREVIEW_FOR_CATEGORY: Record<string, string> = { eyes: "brows", jaw: "jaw", lips: "lips" };

function previewForSection(data: Analysis, s: { feature: string; based_on?: string[] }) {
  const pv = data.previews;
  if (!pv || pv.items.length === 0) return null;
  const find = (k: string) => pv.items.find((i) => i.key === k);
  const keys = s.based_on ?? [];
  let want: string | undefined;
  if (s.feature === "Skin" || keys.some((k) => data.skin.concerns?.some((c) => c.key === k))) want = "skin";
  for (const k of keys) {
    const m = data.metrics.find((x) => x.key === k);
    want ??= PREVIEW_FOR_METRIC[k] ?? (m ? PREVIEW_FOR_CATEGORY[m.category] : undefined);
  }
  // No dedicated preview (e.g. glasses switch off the brow preview): fall back to the combined plan, else the first one.
  const item = (want && find(want)) || find("all") || pv.items[0];
  return { before: pv.before, item };
}

function DeleteButton({ id }: { id: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  async function remove() {
    if (!window.confirm("Permanently delete this report and your photos? This cannot be undone.")) return;
    setBusy(true);
    const res = await fetch(`/api/analyses/${id}`, { method: "DELETE", headers: reportHeaders(id) }).catch(() => null);
    setBusy(false);
    if (res?.ok) {
      forgetReportToken(id);
      router.push("/");
    } else {
      window.alert("Could not delete the report. Please try again.");
    }
  }
  return <button onClick={remove} disabled={busy} className="no-print btn-secondary">{busy ? "Deleting…" : "Delete report"}</button>;
}

const scoreColor = (s: number) => (s >= 75 ? "var(--good)" : s >= 50 ? "var(--warn)" : "var(--bad)");

export default function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);

  useEffect(() => {
    // Returning from checkout: confirm the payment (this also writes the full report).
    const q = new URLSearchParams(window.location.search);
    const sessionId = q.get("session_id");
    const devPlan = q.get("dev_paid");
    const returning = sessionId || devPlan;
    if (returning) window.history.replaceState(null, "", `/report/${id}`);

    const load = async () => {
      if (returning) {
        setUnlocking(true);
        const res = await fetch(`/api/analyses/${id}/confirm`, {
          method: "POST",
          headers: reportHeaders(id, { "Content-Type": "application/json" }),
          body: JSON.stringify({ session_id: sessionId, plan: devPlan }),
        });
        setUnlocking(false);
        if (res.ok) return setData(await res.json());
        if (res.status === 402) setError("Payment wasn't completed. You can try again below.");
      }
      const res = await fetch(`/api/analyses/${id}`, { headers: reportHeaders(id) });
      if (!res.ok) return setError("Report not found.");
      setData(await res.json());
      if (returning) setError(null);
    };
    load().catch(() => setError("Could not reach the server."));
  }, [id]);

  if (unlocking)
    return (
      <main className="flex flex-col items-center px-5 py-24 text-center">
        <div className="h-14 w-14 animate-spin rounded-full border-4 border-line border-t-accent" />
        <h1 className="mt-8 font-serif text-3xl">Payment received — thank you</h1>
        <p className="mt-3 text-muted">Writing your full personalised report. This can take up to a minute.</p>
      </main>
    );
  if (!data) return <main className="mx-auto max-w-3xl px-5 py-20 text-center text-muted">{error ?? "Loading report…"}</main>;

  const { report } = data;
  const byCategory = data.metrics.reduce<Record<string, Metric[]>>((acc, m) => {
    (acc[m.category] ??= []).push(m);
    return acc;
  }, {});

  return (
    <main className="mx-auto max-w-6xl px-5 py-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.2em] text-accent">
            {data.profile.name ? `${data.profile.name}'s report` : "Your report"}
          </p>
          <h1 className="mt-2 max-w-3xl font-serif text-4xl tracking-tight md:text-5xl">{report.headline}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <SaveButton data={data} onSaved={() => setData({ ...data, saved: true })} />
          <ShareButton data={data} />
          <DeleteButton id={data.id} />
          {data.paid && !data.in_review && (
            <Link href={`/report/${data.id}/print`} target="_blank" className="no-print btn-secondary">Download PDF report</Link>
          )}
        </div>
      </div>
      {error && <p className="mt-6 rounded-2xl bg-bad/10 p-4 text-sm text-bad">{error}</p>}
      {data.validation && data.validation.suppressed.length > 0 && (
        <div className="mt-6 rounded-2xl border border-line bg-surface p-5 text-sm">
          <p className="font-medium">Some results were withheld because of the photo</p>
          <ul className="mt-2 space-y-1 text-muted">
            {data.validation.suppressed.map((x) => <li key={x.item}><span className="text-foreground">{x.label}:</span> {x.reason}</li>)}
          </ul>
          {data.validation.retake_tips && data.validation.retake_tips.length > 0 && (
            <div className="mt-4 border-t border-line pt-3" data-testid="retake-tips">
              <p className="font-medium">To get these results, retake the photo:</p>
              <ul className="mt-1 list-disc space-y-1 pl-5 text-muted">{data.validation.retake_tips.map((t) => <li key={t}>{t}</li>)}</ul>
            </div>
          )}
        </div>
      )}
      {data.paid && !data.in_review && (data.review_status === "approved" || data.reviewer_note) && (
        <div className="mt-6 rounded-2xl border border-good/30 bg-good/5 p-5">
          {data.review_status === "approved" && <p className="text-sm font-semibold text-good">✓ Specialist reviewed</p>}
          {data.reviewer_note && (
            <p className="mt-1 leading-relaxed"><span className="font-medium">Note from your specialist: </span>{data.reviewer_note}</p>
          )}
        </div>
      )}

      {/* Overview */}
      <section className="mt-10 grid gap-6 lg:grid-cols-[1fr_1.1fr]">
        <div className={`grid items-start gap-4 self-start ${data.profile_image || data.three_quarter_image ? "grid-cols-2" : ""}`}>
          {([
            ["Front", data.annotated_image],
            ["Side profile", data.profile_image],
            ["Three-quarter", data.three_quarter_image],
          ] as const).filter(([, img]) => img).map(([label, img], _, all) => (
            <figure key={label} className="overflow-hidden rounded-3xl border border-line bg-surface">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`data:image/jpeg;base64,${img}`} alt={`${label} map`} className="w-full" />
              {all.length > 1 && <figcaption className="px-4 py-2 text-xs text-muted">{label}</figcaption>}
            </figure>
          ))}
        </div>
        <div className="space-y-6">
          <div className="flex items-center gap-6 rounded-3xl border border-line bg-surface p-6">
            <ScoreRing score={data.harmony_score} size={120} />
            <div>
              <p className="text-sm text-muted">Proportion harmony</p>
              <p className="mt-1 text-sm">How closely your measurements sit within commonly cited reference ranges. It is not an attractiveness rating.</p>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {Object.entries(data.category_scores).map(([k, v]) => (
              <div key={k} className="rounded-2xl border border-line bg-surface p-4">
                <p className="text-xs text-muted">{CATEGORY_LABELS[k] ?? k}</p>
                <p className="mt-1 font-serif text-3xl" style={{ color: scoreColor(v) }}>{Math.round(v)}</p>
              </div>
            ))}
          </div>
          <p className="leading-relaxed">{report.overview}</p>
          {data.goal_alignment && data.goal_alignment.length > 0 && (
            <div className="mt-4 rounded-2xl border border-line p-4 text-sm" data-testid="goal-alignment">
              <p className="font-medium">Your goals</p>
              <ul className="mt-2 space-y-1.5 text-muted">
                {data.goal_alignment.map((g) => (
                  <li key={g.goal}>
                    <span className="text-foreground">{g.goal}:</span>{" "}
                    {g.status === "recommendations_available" && "your recommendations are ordered with this in mind (measurements still decide what is suggested)."}
                    {g.status === "general_recommendations_only" && "no measurement points to a specific change here, so only general habits are suggested."}
                    {g.status === "measurements_in_range" && "your measurements for this are within the reference range, so no change is recommended."}
                    {g.status === "measurement_unavailable" && "we couldn't measure this reliably from your photo (see the withheld results above)."}
                    {g.status === "partly_unavailable" && "some of the readings behind this were withheld because of the photo (see above), so part of it could not be assessed."}
                    {g.status === "no_specific_target" && "no single target - recommendations follow your measurements."}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {report.strengths.length > 0 && (
            <div>
              <h2 className="mb-2 font-semibold">Your strengths</h2>
              <ul className="space-y-1.5">
                {report.strengths.map((s) => <li key={s} className="flex gap-2"><span className="text-good">✦</span>{s}</li>)}
              </ul>
            </div>
          )}
        </div>
      </section>

      {data.countdown && <CountdownSection c={data.countdown} lockedSteps={data.paid ? undefined : data.locked?.countdown_steps} />}
      {data.climate && <ClimateCard c={data.climate} />}
      {!data.paid && data.style && <StyleSection s={data.style} locked={data.locked?.style} />}
      {!data.paid && data.hair?.available && <HairSection h={data.hair} locked={data.locked?.hair} />}
      {!data.paid && data.remedies && data.remedies.length > 0 && (
        <RemediesSection items={data.remedies} lockedCount={data.locked?.remedies} />
      )}

      {!data.paid && data.anthropometry && (
        <section className="mt-12">
          <h2 className="font-serif text-3xl tracking-tight">Your estimated measurements</h2>
          <p className="mt-2 text-muted">Approximate sizes from your photo (scale estimated from your iris), compared with typical adult ranges.</p>
          <div className="mt-6 grid gap-6 md:grid-cols-[1fr_320px]">
            <MeasurementTable a={data.anthropometry} locked={data.locked?.mm_rows} />
            {data.diagrams?.fifths && (
              <figure>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`data:image/jpeg;base64,${data.diagrams.fifths}`} alt="Rule of fifths" className="w-full rounded-2xl border border-line" />
                <figcaption className="mt-1.5 text-xs text-muted">Rule of fifths. 🔒 {Math.max((data.locked?.diagrams ?? 1) - 1, 0)} more figures in the full report.</figcaption>
              </figure>
            )}
          </div>
        </section>
      )}
      {!data.paid && data.eyes && (
        <section className="mt-12">
          <h2 className="font-serif text-3xl tracking-tight">Eyes &amp; brows</h2>
          <div className="mt-6"><EyesBrows e={data.eyes} locked={data.locked?.eyes} /></div>
        </section>
      )}

      {!data.paid && <LockedReport data={data} onUnlocking={setUnlocking} onUnlocked={setData} />}
      {data.in_review && (
        <section className="mt-12 rounded-3xl border border-line bg-surface p-8 text-center">
          <p className="text-4xl">🔍</p>
          <h2 className="mt-3 font-serif text-3xl">Your specialist is reviewing your report</h2>
          <p className="mx-auto mt-3 max-w-xl text-muted">
            Payment received. A specialist checks every measurement and personalises your plan before release — usually within 24 hours.
            Bookmark this page; your full report will appear here.
          </p>
        </section>
      )}

      {data.paid && !data.in_review && <>
      {/* Priority plan */}
      {report.priority_plan.length > 0 && (
        <section className="mt-12 rounded-3xl bg-foreground p-8 text-background">
          <h2 className="font-serif text-3xl">Your 90-day plan</h2>
          <ol className="mt-6 grid gap-4 md:grid-cols-2">
            {report.priority_plan.map((p, i) => (
              <li key={p} className="flex gap-4">
                <span className="font-serif text-2xl text-accent">{String(i + 1).padStart(2, "0")}</span>
                <span className="pt-1">{p}</span>
              </li>
            ))}
          </ol>
        </section>
      )}

      {data.preview_status && data.preview_status.some((p) => !p.offered) && (
        <section className="mt-12" data-testid="preview-status">
          <h2 className="font-serif text-3xl tracking-tight">Before / after previews</h2>
          <p className="mt-2 text-muted">{data.previews && data.previews.items.length > 0 ? "Some previews are shown above. For the others:" : "No before/after picture was made for this photo. Here is why, so nothing is silently missing:"}</p>
          <ul className="mt-4 space-y-2 text-sm">
            {data.preview_status.filter((p) => !p.offered).map((p) => (
              <li key={p.preview} className="rounded-2xl border border-line p-3"><span className="font-medium capitalize">{p.preview === "other" ? "Other recommendations" : p.preview}:</span> <span className="text-muted">{p.reason}</span></li>
            ))}
          </ul>
        </section>
      )}

      {data.previews && data.previews.items.length > 0 && (
        <Previews before={data.previews.before} items={data.previews.items} note={data.previews.note} />
      )}

      {data.anthropometry && (
        <section className="mt-12">
          <h2 className="font-serif text-3xl tracking-tight">Your estimated measurements</h2>
          <p className="mt-2 text-muted">Real sizes from your photo, compared with typical adult ranges — a description of your face, not a grade.</p>
          <div className="mt-6"><MeasurementTable a={data.anthropometry} /></div>
          {data.diagrams && <div className="mt-8"><ProportionFigures d={data.diagrams} /></div>}
        </section>
      )}
      {data.diagrams?.symmetry_left && (
        <section className="mt-12">
          <h2 className="font-serif text-3xl tracking-tight">Symmetry</h2>
          <div className="mt-6">
            <SymmetryFigures d={data.diagrams} score={data.metrics.find((m) => m.key === "symmetry")?.score} />
          </div>
        </section>
      )}
      {data.eyes && (
        <section className="mt-12">
          <h2 className="font-serif text-3xl tracking-tight">Eyes &amp; brows</h2>
          <div className="mt-6"><EyesBrows e={data.eyes} /></div>
        </section>
      )}

      {data.routine && <RoutineSection r={data.routine} />}
      {data.routine && (() => {
        const skin = data.previews?.items.find((i) => i.key === "skin");
        const why = data.preview_status?.find((p) => p.preview === "skin")?.reason;
        return (
          <section className="mt-8 rounded-3xl border border-line bg-surface p-6" data-testid="routine-preview">
            <h3 className="font-serif text-2xl">What consistent use of this routine may look like</h3>
            {skin ? (
              <div className="mt-4 max-w-md">
                <Slider before={`data:image/jpeg;base64,${data.previews!.before}`} after={`data:image/jpeg;base64,${skin.image}`} />
                <p className="mt-2 text-xs text-muted">Simulated with image editing (smoothing, tone evening, brighter under-eyes) - the direction of change, not a product result. It cannot show what any one product does.</p>
              </div>
            ) : (
              <p className="mt-2 text-sm text-muted">{why ?? "No simulation was made for this photo."} No product-specific before/after exists: image editing cannot show what an individual product does, and we do not fake it.</p>
            )}
          </section>
        );
      })()}
      {data.style && <StyleSection s={data.style} />}
      {data.style && <div className="no-print"><TryOnPanel data={data} /></div>}
      {data.hair?.available && <HairSection h={data.hair} />}

      {/* Feature sections */}
      <section className="mt-12 space-y-6">
        <h2 className="font-serif text-3xl tracking-tight">Feature by feature</h2>
        {report.sections.map((s) => (
          <article key={s.feature} className="rounded-3xl border border-line bg-surface p-6 md:p-8">
            {(() => {
              const pv = previewForSection(data, s);
              return (
                <div className={pv ? "grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px]" : ""}>
                  <div>
            <h3 className="font-serif text-2xl">{s.feature}</h3>
            <p className="mt-2 text-muted">{s.summary}</p>
            {s.based_on && s.based_on.length > 0 && (
              <p className="mt-3 flex flex-wrap gap-1.5 text-xs">
                <span className="text-muted">Based on:</span>
                {s.based_on.map((k) => <span key={k} className="rounded-full bg-background px-2.5 py-0.5">{evidenceLabel(data, k)}</span>)}
              </p>
            )}
            {s.observations.length > 0 && (
              <ul className="mt-4 space-y-1 text-sm">
                {s.observations.map((o) => <li key={o}>— {o}</li>)}
              </ul>
            )}
            <div className="mt-6 grid gap-3 md:grid-cols-2">
              {s.recommendations.map((r) => (
                <div key={r.title} className="rounded-2xl border border-line p-4">
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-medium">{r.title}</p>
                    <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs capitalize ${TYPE_STYLES[r.type] ?? "bg-line"}`}>{r.type}</span>
                  </div>
                  <p className="mt-2 text-sm text-muted">{r.detail}</p>
                  <p className="mt-3 text-xs text-muted">{r.cost} · {r.timeline}</p>
                </div>
              ))}
            </div>
                  </div>
                  {pv && (
                    <aside className="lg:sticky lg:top-6 lg:self-start">
                      <Slider before={`data:image/jpeg;base64,${pv.before}`} after={`data:image/jpeg;base64,${pv.item.image}`} />
                      <p className="mt-3 text-sm font-medium">{pv.item.title}</p>
                      <p className="mt-1 text-xs text-muted">{pv.item.description}</p>
                      <p className="mt-2 text-[11px] text-muted">Simulated with image editing (not an AI image model) - the direction of change, not a guaranteed result.</p>
                    </aside>
                  )}
                </div>
              );
            })()}
          </article>
        ))}
      </section>

      {data.remedies && data.remedies.length > 0 && <RemediesSection items={data.remedies} />}

      {/* Measurements */}
      <section className="mt-12">
        <h2 className="font-serif text-3xl tracking-tight">All measurements</h2>
        {data.validation?.reference_ranges && (
          <p className="mt-2 text-xs font-medium text-muted" data-testid="harmony-reference-status">
            Reference values behind the harmony score: {data.validation.reference_ranges.harmony_metric_references}
          </p>
        )}
        {data.withheld_metrics && data.withheld_metrics.length > 0 && (
          <p className="mt-3 text-sm text-muted">
            Not measured because a beard hides the jawline: {data.withheld_metrics.join(", ")}. Take a clean-shaven photo to add them.
          </p>
        )}
        <div className="mt-6 grid gap-6 md:grid-cols-2">
          {Object.entries(byCategory).map(([cat, ms]) => (
            <div key={cat} className="rounded-3xl border border-line bg-surface p-6">
              <h3 className="mb-4 font-semibold">{CATEGORY_LABELS[cat] ?? cat}</h3>
              <div className="space-y-5">{ms.map((m) => <MetricRow key={m.key} m={m} />)}</div>
            </div>
          ))}
          {data.skin.available && data.skin.concerns && (
            <div className="rounded-3xl border border-line bg-surface p-6 md:col-span-2">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="font-semibold">Skin <span className="text-xs font-normal text-muted">(beta)</span></h3>
                {data.skin.score != null
                  ? <p className="text-sm text-muted">Skin score <span className="font-serif text-2xl" style={{ color: scoreColor(data.skin.score) }}>{Math.round(data.skin.score)}</span></p>
                  : <p className="max-w-xs text-right text-xs text-muted" data-testid="skin-score-withheld">{(data.skin as { score_note?: string }).score_note ?? "Skin score not available for this photo."}</p>}
              </div>
              <div className="mt-4 grid gap-6 md:grid-cols-[280px_1fr]">
                {data.skin.image && (
                  <figure>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`data:image/jpeg;base64,${data.skin.image}`} alt="Skin map" className="w-full rounded-2xl border border-line" />
                    <figcaption className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                      <span><span className="text-[#ffdc3c]">━</span> lines</span>
                      <span><span className="text-[#eb4646]">◯</span> blemishes</span>
                      <span><span className="text-[#aa6e28]">◯</span> dark spots</span>
                      <span><span className="text-[#f0963c]">◯</span> acne marks</span>
                      <span><span className="text-[#3c78c8]">▢</span> pigmentation</span>
                      <span><span className="text-[#a050a0]">■</span> dark circles</span>
                    </figcaption>
                  </figure>
                )}
                <div className="space-y-4">
                  {data.skin.concerns.map((c) => (
                    <div key={c.key}>
                      <div className="flex items-baseline justify-between gap-3 text-sm">
                        <span className="font-medium">{c.label}</span>
                        <span className={`rounded-full px-2 py-0.5 text-xs ${c.severity === "low" ? "bg-good/10 text-good" : c.severity === "moderate" ? "bg-warn/10 text-warn" : "bg-bad/10 text-bad"}`}>
                          {c.severity === "low" ? "looks good" : c.severity}
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 rounded-full bg-line">
                        <div className="h-full rounded-full" style={{ width: `${c.score}%`, background: scoreColor(c.score) }} />
                      </div>
                      <p className="mt-1 text-xs text-muted">{c.detail}</p>
                    </div>
                  ))}
                  {data.skin.tone && data.skin.tone.group !== "unknown" && (
                    <p className="rounded-xl bg-background p-3 text-sm">
                      <span className="font-medium">Your skin tone group: {data.skin.tone.group}.</span>{" "}
                      {data.skin.tone.advice} <span className="text-muted">We use this only to keep advice safe for your skin — never to judge it.</span>
                    </p>
                  )}
                  {data.skin.neck && (data.skin.neck.available || data.skin.neck.finding === "reported") && data.skin.neck.detail && (
                    <div className={`rounded-xl p-3 text-sm ${data.skin.neck.see_doctor ? "border border-bad/30 bg-bad/5" : "bg-background"}`}>
                      <p className="font-medium">Neck &amp; tan check</p>
                      <p className="mt-1">{data.skin.neck.detail}</p>
                      {data.skin.neck.tests && <p className="mt-1 text-xs text-muted">Tests to ask for: {data.skin.neck.tests.join(", ")}</p>}
                    </div>
                  )}
                  <p className="text-xs text-muted">{data.skin.note}</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>
      </>}

      {(data.quality.issues.length > 0 || data.profile_notes?.length || data.profile_error || data.three_quarter_error) && (
        <p className="mt-8 rounded-2xl bg-warn/10 p-4 text-sm text-warn">
          Photo notes:{" "}
          {[
            ...data.quality.issues.map((i) => i.message),
            ...(data.profile_notes ?? []),
            ...(data.profile_error ? [`Side photo not used: ${data.profile_error}`] : []),
            ...(data.three_quarter_error ? [`Three-quarter photo not used: ${data.three_quarter_error}`] : []),
          ].join(" ")}
        </p>
      )}
      {data.liveness?.checked && (
        <p className="mt-4 text-xs text-muted">
          {data.liveness.passed ? "✓ Live photo — blink check passed." : "Blink check not passed — this may be a photo of a photo."}
        </p>
      )}
      {data.medical && <MedicalSection m={data.medical} />}
      <p className="mt-10 text-sm text-muted">{report.disclaimer}</p>
      <div className="no-print mt-8">
        <Link href="/analyze" className="btn-secondary">Analyse another photo</Link>
      </div>
    </main>
  );
}

function SaveButton({ data, onSaved }: { data: Analysis; onSaved: () => void }) {
  const user = useUser();
  const [busy, setBusy] = useState(false);
  if (user === undefined || data.saved) return null;
  if (!user)
    return <Link href={`/login?next=/report/${data.id}`} className="no-print btn-secondary">Sign in to track progress</Link>;
  async function save() {
    setBusy(true);
    const res = await fetch(`/api/me/analyses/${data.id}/claim`, { method: "POST", headers: reportHeaders(data.id) }).catch(() => null);
    setBusy(false);
    if (res?.ok) onSaved();
  }
  return (
    <button onClick={save} disabled={busy} className="no-print btn-secondary">{busy ? "Saving…" : "Save to my progress"}</button>
  );
}

function formatMoney(amount: number, currency: string) {
  return new Intl.NumberFormat(currency.toLowerCase() === "inr" ? "en-IN" : undefined, {
    style: "currency", currency: currency.toUpperCase(), maximumFractionDigits: amount % 1 ? 2 : 0,
  }).format(amount);
}

type RazorpayOptions = Record<string, unknown> & { handler: (r: Record<string, string>) => void };
declare global {
  interface Window { Razorpay?: new (o: RazorpayOptions) => { open: () => void } }
}

function loadRazorpay(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Could not load Razorpay"));
    document.body.appendChild(s);
  });
}

function LockedReport({ data, onUnlocking, onUnlocked }: {
  data: Analysis; onUnlocking: (v: boolean) => void; onUnlocked: (d: Analysis) => void;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const locked = data.locked!;

  async function checkout(plan: string) {
    setBusy(plan);
    setErr(null);
    try {
      const res = await fetch(`/api/analyses/${data.id}/checkout`, {
        method: "POST", headers: reportHeaders(data.id, { "Content-Type": "application/json" }), body: JSON.stringify({ plan }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? "Checkout failed");
      if (!body.razorpay) {
        window.location.href = body.url ?? `/report/${data.id}`;
        return;
      }
      await loadRazorpay();
      const rp = new window.Razorpay!({
        ...body.razorpay,
        theme: { color: "#b5652f" },
        modal: { ondismiss: () => setBusy(null) },
        handler: async (resp: Record<string, string>) => {
          onUnlocking(true);
          const r = await fetch(`/api/analyses/${data.id}/confirm`, {
            method: "POST", headers: reportHeaders(data.id, { "Content-Type": "application/json" }), body: JSON.stringify(resp),
          });
          onUnlocking(false);
          if (r.ok) onUnlocked(await r.json());
          else setErr("We couldn't confirm the payment. If money was debited, refresh in a minute — it will unlock automatically.");
          setBusy(null);
        },
      });
      rp.open();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Checkout failed");
      setBusy(null);
    }
  }

  const included = [
    `All ${locked.metrics} measurements explained, with your exact values`,
    `${locked.sections} feature-by-feature sections with non-surgical methods`,
    ...(locked.mm_rows ? [`${locked.mm_rows} measurements in millimetres vs typical ranges`] : []),
    ...(locked.diagrams ? ["Proportion diagrams (fifths, thirds) and left/right mirror faces"] : []),
    ...(locked.eyes ? ["Your personal brow-shaping guide (take it to your threading appointment)"] : []),
    "A designed PDF report to download and keep",
    "A personalised 90-day plan, written for your goals and budget",
    ...(locked.routine ? ["Your morning & night skincare routine with products in ₹"] : []),
    ...(locked.previews ? [`${locked.previews} simulated before/after previews of your results`] : []),
    ...(locked.style ? ["Hairstyles, beard styles and glasses picked for your face shape"] : []),
    ...(locked.hair ? ["Hair fall causes to check, blood tests to ask for and a hair plan"] : []),
    ...(locked.countdown_steps ? [`Your full dated glow-up countdown (${locked.countdown_steps} steps)`] : []),
  ];

  return (
    <>
      <section className="mt-12">
        <h2 className="font-serif text-3xl tracking-tight">A preview of your measurements</h2>
        <div className="mt-6 grid gap-6 md:grid-cols-2">
          <div className="space-y-5 rounded-3xl border border-line bg-surface p-6">
            {data.metrics.map((m) => <MetricRow key={m.key} m={m} />)}
          </div>
          <div className="relative overflow-hidden rounded-3xl border border-line bg-surface p-6">
            <div className="pointer-events-none select-none space-y-5 blur-[5px]" aria-hidden>
              {locked.feature_names.slice(0, 4).map((name, i) => (
                <div key={name}>
                  <div className="flex justify-between text-sm font-medium"><span>{name}</span><span>{[1.12, 0.94, 128, 0.46][i]}</span></div>
                  <div className="mt-2 h-1.5 rounded-full bg-line"><div className="h-full w-1/2 rounded-full bg-good/40" /></div>
                </div>
              ))}
            </div>
            <div className="absolute inset-0 flex items-center justify-center">
              <span className="rounded-full bg-foreground px-4 py-2 text-sm text-background">
                🔒 {locked.metrics - data.metrics.length} more measurements
              </span>
            </div>
          </div>
        </div>
      </section>

      <section className="no-print mt-12 rounded-3xl bg-foreground p-8 text-background md:p-10">
        <p className="text-sm uppercase tracking-[0.2em] text-accent">Full report</p>
        <h2 className="mt-2 font-serif text-4xl">Unlock your complete analysis</h2>
        <ul className="mt-6 grid gap-3 md:grid-cols-2">
          {included.map((t) => <li key={t} className="flex gap-3"><span className="text-accent">✓</span>{t}</li>)}
        </ul>
        {locked.feature_names.length > 0 && (
          <p className="mt-4 text-sm text-background/70">Includes: {locked.feature_names.join(" · ")}</p>
        )}
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          {data.price.plans.map((p) => (
            <div key={p.id} className={`flex flex-col rounded-2xl p-6 ${p.id === "expert" ? "bg-accent/20 ring-1 ring-accent" : "bg-background/10"}`}>
              <div className="flex items-baseline justify-between gap-2">
                <p className="font-medium">{p.name}</p>
                {p.id === "expert" && <span className="rounded-full bg-accent px-2.5 py-0.5 text-xs text-white">Most trusted</span>}
              </div>
              <p className="mt-2 font-serif text-5xl">{formatMoney(p.amount, data.price.currency)}</p>
              <p className="text-sm text-background/70">One-time · no subscription</p>
              <ul className="mt-4 flex-1 space-y-1.5 text-sm text-background/85">
                {p.features.map((f) => <li key={f}>· {f}</li>)}
              </ul>
              <button onClick={() => checkout(p.id)} disabled={!!busy}
                className={`mt-6 rounded-full px-6 py-3.5 font-medium hover:opacity-90 disabled:opacity-50 ${p.id === "expert" ? "bg-accent text-white" : "bg-background text-foreground"}`}>
                {busy === p.id ? "Opening secure checkout…" : `Get ${p.id === "expert" ? "expert-reviewed report" : "full report"}`}
              </button>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-background/60">
          {data.price.mode === "razorpay" && "Secure payment by Razorpay · UPI, cards, netbanking & wallets."}
          {data.price.mode === "stripe" && "Secure payment by Stripe."}
          {data.price.mode === "dev" && "Dev mode: payment keys not set — this unlocks without payment."}
        </p>
        {err && <p className="mt-3 text-sm text-[#ffb4a2]">{err}</p>}
      </section>
    </>
  );
}

function ScoreRing({ score, size }: { score: number; size: number }) {
  const r = size / 2 - 8;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} className="shrink-0">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="8" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--accent)" strokeWidth="8" strokeLinecap="round"
        strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      <text x="50%" y="54%" textAnchor="middle" dominantBaseline="middle" className="font-serif" fontSize={size / 3.2} fill="var(--foreground)">
        {Math.round(score)}
      </text>
    </svg>
  );
}

function MetricRow({ m }: { m: Metric }) {
  // Position the measured value on a scale spanning ideal ± 3 tolerances.
  const lo = m.ideal - 3 * m.tolerance;
  const hi = m.ideal + 3 * m.tolerance;
  const pos = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`;
  const badge = { ideal: "text-good bg-good/10", near: "text-warn bg-warn/10", outside: "text-bad bg-bad/10" }[m.status];
  return (
    <div title={m.description}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{m.label}</span>
        <span className="flex items-center gap-2 text-sm">
          <span className="tabular-nums">{m.value}{m.unit === "°" ? "°" : ""}</span>
          <span className={`rounded-full px-2 py-0.5 text-xs ${badge}`}>{m.status}</span>
        </span>
      </div>
      <div className="relative mt-2 h-1.5 rounded-full bg-line">
        <div className="absolute inset-y-0 rounded-full bg-good/30" style={{ left: pos(m.ideal - m.tolerance), right: `calc(100% - ${pos(m.ideal + m.tolerance)})` }} />
        <div className="absolute -top-1 h-3.5 w-1 rounded-full bg-foreground" style={{ left: pos(m.value) }} />
      </div>
      <p className="mt-1.5 text-xs text-muted">{m.description}</p>
    </div>
  );
}
