"use client";

type Consult = { title: string; status: "indicated" | "not_indicated" | "could_not_assess" | "not_offered_safety"; why: string };
export type Medical = {
  content_status: string;
  limits: string[];
  red_flags: Record<"urgent" | "soon" | "dermatologist", { title: string; items: string[] }>;
  consults: Consult[];
  history: { answer: string; effect: string }[];
  history_note: string;
};

const STATUS_LABEL: Record<Consult["status"], string> = {
  indicated: "Worth discussing",
  not_indicated: "Not indicated by your measurements",
  could_not_assess: "Could not assess from this photo",
  not_offered_safety: "Not offered for you (safety)",
};
const ANSWER_LABEL: Record<string, string> = {
  pregnant: "Pregnant", breastfeeding: "Breastfeeding", isotretinoin: "Taking isotretinoin", steroid_history: "Used steroid or 'fairness' creams",
  skin_condition: "Eczema, psoriasis or rosacea", prescribed_skin_treatment: "Using a prescribed skin treatment",
};

/** Shown in every report, whatever the photo shows. General information only. */
export function MedicalSection({ m }: { m: Medical }) {
  return (
    <section className="mt-12 rounded-3xl border border-line bg-surface p-6 md:p-8" data-testid="medical-section">
      <p className="text-sm uppercase tracking-[0.2em] text-accent">Health &amp; professional care</p>
      <h2 className="mt-1 font-serif text-3xl">What this report can and cannot do</h2>
      <p className="mt-2 text-xs font-medium text-muted" data-testid="medical-content-status">Content status: {m.content_status}</p>
      <ul className="mt-4 list-disc space-y-1.5 pl-5 text-sm text-muted">{m.limits.map((l) => <li key={l}>{l}</li>)}</ul>

      <h3 className="mt-8 font-serif text-2xl">When to seek care</h3>
      <div className="mt-3 grid gap-4 md:grid-cols-3">
        {(["urgent", "soon", "dermatologist"] as const).map((k) => (
          <div key={k} className={`rounded-2xl border p-4 text-sm ${k === "urgent" ? "border-bad/40 bg-bad/5" : "border-line"}`}>
            <p className="font-medium">{m.red_flags[k].title}</p>
            <ul className="mt-2 list-disc space-y-1.5 pl-4 text-muted">{m.red_flags[k].items.map((i) => <li key={i}>{i}</li>)}</ul>
          </div>
        ))}
      </div>

      <h3 className="mt-8 font-serif text-2xl">Professional consults - every option, and where you stand</h3>
      <p className="mt-1 text-sm text-muted">A consult is a conversation with a licensed provider, not a recommendation to have a procedure.</p>
      <div className="mt-3 overflow-x-auto rounded-2xl border border-line">
        <table className="w-full text-sm" data-testid="consult-table">
          <thead className="text-left text-xs text-muted"><tr><th className="px-3 py-2">Consult</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Why</th></tr></thead>
          <tbody>
            {m.consults.map((c) => (
              <tr key={c.title} className="border-t border-line align-top">
                <td className="px-3 py-2 font-medium">{c.title}</td>
                <td className="px-3 py-2 whitespace-nowrap">{STATUS_LABEL[c.status]}</td>
                <td className="px-3 py-2 text-muted">{c.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 className="mt-8 font-serif text-2xl">Your health answers</h3>
      <p className="mt-1 text-sm text-muted" data-testid="history-note">{m.history_note}</p>
      {m.history.length > 0 && (
        <ul className="mt-2 space-y-1.5 text-sm">
          {m.history.map((h) => <li key={h.answer}><span className="font-medium">{ANSWER_LABEL[h.answer] ?? h.answer}:</span> <span className="text-muted">{h.effect}</span></li>)}
        </ul>
      )}
    </section>
  );
}
