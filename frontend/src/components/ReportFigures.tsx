"use client";

import type { Analysis } from "@/lib/types";

type Anth = NonNullable<Analysis["anthropometry"]>;
type Eyes = NonNullable<Analysis["eyes"]>;
type Diagrams = NonNullable<Analysis["diagrams"]>;

function Fig({ src, caption }: { src?: string; caption: string }) {
  if (!src) return null;
  return (
    <figure>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={`data:image/jpeg;base64,${src}`} alt={caption} className="w-full rounded-2xl border border-line" />
      <figcaption className="mt-1.5 text-xs text-muted">{caption}</figcaption>
    </figure>
  );
}

export function MeasurementTable({ a, locked }: { a: Anth; locked?: number }) {
  return (
    <div>
      <div className="overflow-x-auto rounded-2xl border border-line">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted">
            <tr>
              <th className="px-3 py-2">Measurement</th>
              <th className="px-3 py-2">You</th>
              <th className="px-3 py-2">Typical <span className="block text-[10px] font-normal uppercase tracking-wide" data-testid="range-placeholder">placeholder - not validated</span></th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {a.rows.map((r) => (
              <tr key={r.key} className="border-t border-line" title={r.description}>
                <td className="px-3 py-2">{r.label}</td>
                <td className="px-3 py-2 font-medium">{r.value} {r.unit}</td>
                <td className="px-3 py-2 text-muted">{r.range[0]}–{r.range[1]}</td>
                <td className="px-3 py-2 text-muted">
                  {r.status === "typical" ? "Typical" : `${r.status === "above" ? "Above" : "Below"} (${r.deviation_pct > 0 ? "+" : ""}${r.deviation_pct}%)`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {a.ratios.length > 0 && (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {a.ratios.map((r) => (
            <li key={r.key} className="rounded-xl border border-line px-3 py-2 text-sm">
              <span className="font-medium">{r.label}: {r.value}</span>
              <span className="block text-xs text-muted">{r.note}</span>
            </li>
          ))}
        </ul>
      )}
      {locked ? <p className="mt-3 text-xs text-muted">🔒 {Math.max(locked - a.rows.length, 0)} more measurements and ratios in the full report.</p> : null}
      <p className="mt-2 text-xs text-muted">{a.note}</p>
      {a.range_status && <p className="mt-1 text-xs font-medium text-muted" data-testid="range-status">Typical ranges: {a.range_status}</p>}
    </div>
  );
}

export function EyesBrows({ e, locked }: { e: Eyes; locked?: number }) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <div>
        <ul className="list-disc space-y-1.5 pl-5">
          {e.findings.map((f, i) => <li key={i}>{f}</li>)}
        </ul>
        {e.advice.length > 0 && (
          <>
            <h3 className="mt-5 font-medium">Brow &amp; eye guidance</h3>
            <ul className="mt-2 list-disc space-y-1.5 pl-5">
              {e.advice.map((f, i) => <li key={i}>{f}</li>)}
            </ul>
          </>
        )}
        {locked ? <p className="mt-3 text-xs text-muted">🔒 {locked} findings and tips in the full report.</p> : null}
        <p className="mt-3 text-xs text-muted">{e.note}</p>
        {e.thresholds_status && <p className="mt-1 text-xs font-medium text-muted" data-testid="eye-thresholds-status">Eye and brow thresholds: {e.thresholds_status}</p>}
      </div>
      <Fig src={e.image} caption="Eye and brow lines used for these measurements" />
    </div>
  );
}

export function ProportionFigures({ d }: { d: Diagrams }) {
  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <Fig src={d.measurements} caption="Key measurements in mm" />
      <Fig src={d.fifths} caption="Rule of fifths" />
      <Fig src={d.thirds} caption="Facial thirds" />
    </div>
  );
}

export function SymmetryFigures({ d, score }: { d: Diagrams; score?: number }) {
  return (
    <div>
      {score !== undefined && <p className="mb-4 text-muted">Symmetry score: {Math.round(score)}. Each image mirrors one half of your face.</p>}
      <div className="grid gap-6 sm:grid-cols-2">
        <Fig src={d.symmetry_right} caption="Your right side, mirrored" />
        <Fig src={d.symmetry_left} caption="Your left side, mirrored" />
      </div>
    </div>
  );
}
