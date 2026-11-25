import type { Analysis } from "@/lib/types";

type Routine = NonNullable<Analysis["routine"]>;
type Remedy = NonNullable<Analysis["remedies"]>[number];
type Countdown = NonNullable<Analysis["countdown"]>;

export const VERDICT: Record<Remedy["verdict"], { label: string; cls: string; icon: string }> = {
  harmful: { label: "Avoid", cls: "bg-bad/10 text-bad", icon: "✕" },
  works: { label: "Works", cls: "bg-good/10 text-good", icon: "✓" },
  okay: { label: "Okay, with care", cls: "bg-warn/10 text-warn", icon: "~" },
  myth: { label: "Myth", cls: "bg-line text-muted", icon: "?" },
};

const fmtDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

export function CountdownSection({ c, lockedSteps }: { c: Countdown; lockedSteps?: number }) {
  const shown = c.phases.reduce((n, p) => n + p.items.length, 0);
  return (
    <section className="mt-12 rounded-3xl border border-accent/40 bg-accent-soft/50 p-6 md:p-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm uppercase tracking-[0.2em] text-accent">{c.label} · {fmtDate(c.date)}</p>
          <h2 className="mt-1 font-serif text-3xl">Your glow-up countdown</h2>
        </div>
        <p className="font-serif text-5xl text-accent">
          {c.days_left}<span className="ml-2 text-base text-muted">{c.days_left === 1 ? "day" : "days"} to go</span>
        </p>
      </div>
      <ol className="mt-6 space-y-5 border-l-2 border-accent/40 pl-6">
        {c.phases.map((p) => (
          <li key={p.date} className="relative">
            <span className="absolute -left-[31px] top-1 h-3 w-3 rounded-full bg-accent" />
            <p className="text-sm font-medium text-accent">
              {fmtDate(p.date)}{p.days_before === c.days_left ? " · start now" : p.days_before === 0 ? " · the big day" : ` · ${p.days_before} ${p.days_before === 1 ? "day" : "days"} before`}
            </p>
            <ul className="mt-1 space-y-1.5">
              {p.items.map((i) => (
                <li key={i.title}><span className="font-medium">{i.title}.</span> <span className="text-muted">{i.detail}</span></li>
              ))}
            </ul>
          </li>
        ))}
      </ol>
      {lockedSteps !== undefined && lockedSteps > shown && (
        <p className="mt-5 rounded-xl bg-surface p-3 text-sm">🔒 {lockedSteps - shown} more dated steps in your full report.</p>
      )}
    </section>
  );
}

export function RoutineSection({ r }: { r: Routine }) {
  return (
    <section className="mt-12">
      <h2 className="font-serif text-3xl tracking-tight">Your skincare routine</h2>
      <p className="mt-2 text-muted">
        Built for your {r.skin_type} skin and budget. Start with the basics; add one new product every 1-2 weeks.
      </p>
      <div className="mt-6 grid gap-6 md:grid-cols-2">
        {([["☀️ Morning", r.am], ["🌙 Night", r.pm]] as const).map(([title, steps]) => (
          <div key={title} className="rounded-3xl border border-line bg-surface p-6">
            <h3 className="font-semibold">{title}</h3>
            <ol className="mt-4 space-y-5">
              {steps.map((st, i) => (
                <li key={st.step + i} className="flex gap-3">
                  <span className="font-serif text-xl text-accent">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{st.step} <span className="text-xs font-normal text-muted">· {st.how}</span></p>
                    <p className="text-sm text-muted">{st.why}</p>
                    <div className="mt-2 space-y-1.5">
                      {st.products.map((p) => (
                        <div key={p.name} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                          {p.swap && <span className="rounded-full bg-line px-2 py-0.5 text-[11px]">budget swap</span>}
                          <span>{p.name}</span>
                          <span className="text-xs text-muted">{p.price_band}</span>
                          <a href={p.links.nykaa} target="_blank" rel="noopener sponsored" className="text-xs text-accent hover:underline">Nykaa</a>
                          <a href={p.links.amazon} target="_blank" rel="noopener sponsored" className="text-xs text-accent hover:underline">Amazon</a>
                        </div>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      <ul className="mt-4 space-y-1 text-sm text-muted">
        {r.notes.map((n) => <li key={n}>• {n}</li>)}
      </ul>
      {r.removals && (
        <div className="mt-6 rounded-3xl border border-line bg-surface p-6" data-testid="routine-removals">
          <h3 className="font-semibold">What to remove from your routine</h3>
          <p className="mt-1 text-xs text-muted">{r.removals.status}</p>
          {r.removals.note && <p className="mt-2 text-sm">{r.removals.note}</p>}
          <h4 className="mt-4 text-sm font-medium">Stop now, when you start these products</h4>
          <ul className="mt-2 space-y-1 text-sm">
            {r.removals.stop_now.map((x) => <li key={x.item}>• <b>{x.item}</b> <span className="text-muted">- {x.why}</span></li>)}
          </ul>
          {r.removals.step_down.length > 0 && (<>
            <h4 className="mt-4 text-sm font-medium">Step down later, once your skin has settled</h4>
            <ul className="mt-2 space-y-1 text-sm">
              {r.removals.step_down.map((x) => <li key={x.item}>• <b>{x.item}</b> <span className="text-muted">({x.when}) - {x.why}</span></li>)}
            </ul>
          </>)}
          <p className="mt-4 text-sm text-muted">{r.removals.keep}</p>
        </div>
      )}
      <p className="mt-2 text-xs text-muted">{r.disclaimer}</p>
    </section>
  );
}

export function RemediesSection({ items, lockedCount }: { items: Remedy[]; lockedCount?: number }) {
  return (
    <section className="mt-12">
      <h2 className="font-serif text-3xl tracking-tight">Desi nuskhe — what works, what doesn&apos;t</h2>
      <p className="mt-2 text-muted">Popular home remedies for your concerns, rated honestly by the evidence.</p>
      <div className="mt-6 grid gap-3 md:grid-cols-2">
        {items.map((r) => (
          <div key={r.name} className="rounded-2xl border border-line bg-surface p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="font-medium">{r.name}</p>
              <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${VERDICT[r.verdict].cls}`}>
                {VERDICT[r.verdict].icon} {VERDICT[r.verdict].label}
              </span>
            </div>
            <p className="mt-2 text-sm text-muted">{r.why}</p>
          </div>
        ))}
      </div>
      {lockedCount !== undefined && lockedCount > items.length && (
        <p className="mt-4 text-sm text-muted">🔒 {lockedCount - items.length} more remedies rated in your full report.</p>
      )}
    </section>
  );
}
