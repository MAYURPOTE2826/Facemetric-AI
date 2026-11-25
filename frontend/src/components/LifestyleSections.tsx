import type { Analysis } from "@/lib/types";
import { VERDICT } from "./IndiaSections";
import { HairAnalysisSection } from "./HairAnalysisSection";

type Style = NonNullable<Analysis["style"]>;
type Hair = NonNullable<Analysis["hair"]>;
type Climate = NonNullable<Analysis["climate"]>;

const scoreColor = (s: number) => (s >= 75 ? "var(--good)" : s >= 50 ? "var(--warn)" : "var(--bad)");

function List({ title, items, icon = "✦" }: { title: string; items?: string[]; icon?: string }) {
  if (!items?.length) return null;
  return (
    <div>
      <h3 className="font-semibold">{title}</h3>
      <ul className="mt-2 space-y-1.5 text-sm">
        {items.map((i) => <li key={i} className="flex gap-2"><span className="text-accent">{icon}</span>{i}</li>)}
      </ul>
    </div>
  );
}

export function StyleSection({ s, locked }: { s: Style; locked?: number }) {
  return (
    <section className="mt-12 rounded-3xl border border-line bg-surface p-6 md:p-8">
      <p className="text-sm uppercase tracking-[0.2em] text-accent">Face shape</p>
      <h2 className="mt-1 font-serif text-3xl">{s.label}{s.secondary ? <span className="text-muted"> · leans {s.secondary}</span> : null}</h2>
      <p className="mt-2 max-w-2xl text-muted">{s.summary}</p>
      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <List title="Hairstyles that suit you" items={s.hairstyles} />
        <List title="Beard styles" items={s.beard} />
        <List title="Glasses frames" items={s.glasses} />
        <List title="Best avoided" items={s.avoid} icon="✕" />
      </div>
      {s.notes && s.notes.length > 0 && (
        <ul className="mt-5 space-y-1 text-sm text-muted">{s.notes.map((n) => <li key={n}>• {n}</li>)}</ul>
      )}
      {locked !== undefined && (
        <p className="mt-5 rounded-xl bg-background p-3 text-sm">🔒 {Math.max(locked - s.hairstyles.length, 0)} more hairstyle, beard and glasses picks in your full report.</p>
      )}
    </section>
  );
}

export function HairSection({ h, locked }: { h: Hair; locked?: number }) {
  return (
    <section className="mt-12">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-serif text-3xl tracking-tight">Hair fall check</h2>
        {!h.analysis && h.score != null && (
          <p className="text-sm text-muted">Hair score <span className="font-serif text-2xl" style={{ color: scoreColor(h.score) }}>{h.score}</span></p>
        )}
      </div>
      {h.see_doctor && (
        <p className="mt-4 rounded-2xl border border-bad/30 bg-bad/5 p-4 text-sm">
          <span className="font-semibold text-bad">Please see a dermatologist.</span> We noticed: {h.doctor_reasons?.join("; ")}.
          Early treatment works best for most hair loss.
        </p>
      )}
      {h.analysis && <HairAnalysisSection a={h.analysis} />}
      <div className={`mt-6 grid gap-6 ${h.top_image ? "md:grid-cols-[1fr_1fr]" : "md:grid-cols-[320px_1fr]"}`}>
        <div className={`grid gap-3 ${h.top_image ? "grid-cols-2" : ""}`}>
          {h.image && (
            <figure>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`data:image/jpeg;base64,${h.image}`} alt="Hairline map" className="w-full rounded-2xl border border-line" />
              <figcaption className="mt-1 text-xs text-muted">Hairline: white = centre, red = temples</figcaption>
            </figure>
          )}
          {h.top_image && (
            <figure>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`data:image/jpeg;base64,${h.top_image}`} alt="Scalp coverage" className="w-full rounded-2xl border border-line" />
              <figcaption className="mt-1 text-xs text-muted">Scalp showing through (red), parting (blue)</figcaption>
            </figure>
          )}
        </div>
        <div className="space-y-4">
          {h.analysis ? null : h.hairline ? (
            <Reading title="Hairline" label={h.hairline.label} score={h.hairline.score} detail={h.hairline.detail} />
          ) : h.hairline_note ? <p className="text-sm text-muted">{h.hairline_note}</p> : null}
          {h.shedding_note && <p className="rounded-2xl bg-surface p-4 text-sm" data-testid="hair-shedding-note">{h.shedding_note}</p>}
          {h.hairline_limits && <p className="text-xs text-muted" data-testid="hair-hairline-limits">{h.hairline_limits}</p>}
          {!h.analysis && h.crown && <Reading title="Top of head" label={h.crown.label} score={h.crown.score} detail={h.crown.detail} />}
          {!h.analysis && h.crown?.parting && (
            <Reading title="Parting" label={h.crown.parting.label} score={h.crown.parting.score} detail={h.crown.parting.detail} />
          )}
          {h.top_error && <p className="text-sm text-warn">Top photo not used: {h.top_error}</p>}
          {!h.analysis && !h.crown && !h.top_error && (
            <p className="text-xs text-muted">Add a top-of-head photo next time to check thinning at the crown and parting.</p>
          )}
        </div>
      </div>

      {h.causes && h.causes.length > 0 && (
        <div className="mt-8">
          <h3 className="font-serif text-2xl">Likely causes to check</h3>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {h.causes.map((c) => (
              <div key={c.key} className="rounded-2xl border border-line bg-surface p-4">
                <p className="font-medium">{c.title}</p>
                <p className="mt-1 text-sm text-muted">{c.why}</p>
                <ul className="mt-2 space-y-1 text-sm">{c.actions.map((a) => <li key={a}>→ {a}</li>)}</ul>
              </div>
            ))}
          </div>
        </div>
      )}
      {h.plan && h.plan.length > 0 && (
        <div className="mt-6 rounded-2xl bg-foreground p-6 text-background">
          <h3 className="font-semibold">Your hair plan</h3>
          <ol className="mt-3 list-decimal space-y-1.5 pl-5 text-sm">{h.plan.map((p) => <li key={p}>{p}</li>)}</ol>
        </div>
      )}
      {h.myths && h.myths.length > 0 && (
        <div className="mt-6">
          <h3 className="font-semibold">Hair myths, checked</h3>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {h.myths.map((m) => (
              <div key={m.name} className="rounded-2xl border border-line bg-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <p className="font-medium">{m.name}</p>
                  <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${VERDICT[m.verdict].cls}`}>
                    {VERDICT[m.verdict].icon} {VERDICT[m.verdict].label}
                  </span>
                </div>
                <p className="mt-2 text-sm text-muted">{m.why}</p>
              </div>
            ))}
          </div>
        </div>
      )}
      {locked !== undefined && locked > 0 && (
        <p className="mt-5 rounded-xl bg-surface p-3 text-sm">🔒 Likely causes, blood tests to ask for and your hair plan ({locked} items) are in your full report.</p>
      )}
      <p className="mt-4 text-xs text-muted">A photo-based screening, not a diagnosis. Lighting, hair colour and styling affect these readings.</p>
    </section>
  );
}

function Reading({ title, label, score, detail }: { title: string; label: string; score: number; detail: string }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{title}: {label}</span>
        <span className="tabular-nums text-muted">{score}</span>
      </div>
      <div className="mt-1.5 h-1.5 rounded-full bg-line">
        <div className="h-full rounded-full" style={{ width: `${score}%`, background: scoreColor(score) }} />
      </div>
      <p className="mt-1 text-xs text-muted">{detail}</p>
    </div>
  );
}

export function ClimateCard({ c }: { c: Climate }) {
  return (
    <section className="mt-12 rounded-3xl border border-line bg-surface p-6 md:p-8">
      <p className="text-sm uppercase tracking-[0.2em] text-accent">{c.city} · {c.zone_label}</p>
      <h2 className="mt-1 font-serif text-3xl">{c.season_label} skin care{c.pollution ? " + pollution season" : ""}</h2>
      <ul className="mt-4 space-y-1.5 text-sm">
        {c.tips.map((t) => <li key={t} className="flex gap-2"><span className="text-accent">✦</span>{t}</li>)}
      </ul>
      {c.upcoming && (
        <p className="mt-4 rounded-xl bg-background p-3 text-sm">
          <span className="font-medium">Coming up: {c.upcoming.label}.</span> {c.upcoming.tip}
        </p>
      )}
    </section>
  );
}
