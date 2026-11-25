import type { HairAnalysis, HairDensity } from "@/lib/types";

const LABEL: Record<string, string> = {
  relatively_straight: "Relatively straight", rounded: "Rounded", mildly_mature: "Mildly mature / temple-shaped", m_shaped: "M-shaped appearance",
  v_shaped: "V-shaped appearance", irregular: "Irregular", asymmetric: "Left and right differ", insufficient_visibility: "Not enough visible to describe",
  no_obvious_recession: "No obvious recession detected", mildly_mature_temple_shape: "Mildly higher temple corner (common)",
  possible_recession_pattern: "Possible recession pattern detected", pronounced_possible_recession_pattern: "Possible recession pattern (more pronounced)",
  not_assessable: "Not assessable", no_reduced_visible_density_detected: "No reduced visible density detected",
  slightly_reduced_visible_density: "Slightly reduced visible density", reduced_visible_density_detected: "Reduced visible density detected",
  inconclusive: "Inconclusive", detected: "Detected", not_reliably_visible: "Not reliably visible", not_detected: "Not detected",
};
const FLAG: Record<string, string> = {
  low_resolution: "Low resolution", blurry: "Blurry", overexposed: "Over-exposed", too_dark: "Too dark", hair_colour_close_to_skin: "Hair colour close to skin colour",
  glossy_or_wet_hair_or_strong_overhead_light: "Glossy / wet hair or strong overhead light", head_turned: "Head turned", very_short_hair: "Very short hair",
  fringe_or_hair_over_forehead: "Fringe or hair over the forehead", headwear_or_covering: "Cap or head covering", hairline_outside_frame: "Hairline outside the frame",
  irregular_boundary_textured_or_styled_hair: "Textured or styled hair outline",
};
const pct = (c: number) => `${Math.round(c * 100)}%`;
const conf = (c: number) => (c >= 0.7 ? "High confidence" : c >= 0.4 ? "Moderate confidence" : "Low confidence") + ` (${pct(c)})`;

function Row({ title, value, sub, confidence, testid }: { title: string; value: string; sub?: string; confidence?: number; testid?: string }) {
  return (
    <div className="break-avoid rounded-2xl border border-line bg-surface p-4" data-testid={testid}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-medium">{title}</p>
        {confidence !== undefined && <span className="text-xs text-muted">{conf(confidence)}</span>}
      </div>
      <p className="mt-1 text-sm"><span className="text-xs uppercase tracking-wide text-muted">Screening result · </span>{value}</p>
      {sub && <p className="mt-1 text-sm text-muted">{sub}</p>}
    </div>
  );
}

const dens = (d: HairDensity | null) => (d ? LABEL[d.status] ?? d.status : "Not assessable");

export function HairAnalysisSection({ a }: { a: HairAnalysis }) {
  const q = a.image_quality;
  const t = a.temples;
  return (
    <div className="mt-8" data-testid="hair-analysis">
      <p className="text-sm uppercase tracking-[0.2em] text-accent">Hair &amp; hairline analysis</p>
      <p className="mt-1 text-sm text-muted">
        Screening from your photos - not a diagnosis. Status: <b>{a.status}</b>. {a.reason ?? ""}
      </p>
      <div className="mt-4 grid gap-6 md:grid-cols-[320px_1fr]">
        <figure className="break-avoid print:max-w-[300px]">
          {a.image && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`data:image/jpeg;base64,${a.image}`} alt="Hairline analysis" className="w-full rounded-2xl border border-line" />
          )}
          <figcaption className="mt-1 text-xs text-muted" data-testid="hair-legend">
            Green line: high-confidence boundary · Yellow: low confidence · Grey: not assessable · Blue: frontal analysis region ·
            Temple tint: green ordinary, yellow possible pattern, red more pronounced pattern.
          </figcaption>
        </figure>
        <div className="space-y-3">
          <Row testid="hair-quality" title="Image confidence" confidence={q.confidence}
            value={q.hairline_visible ? "Hairline visible enough to analyse" : "Hairline not visible enough for a confident result"}
            sub={q.flags.length ? "Lowers confidence: " + q.flags.map((f) => FLAG[f] ?? f).join(", ") : "No photo problems detected."} />
          <Row testid="hair-hairline" title="Hairline" confidence={a.hairline.confidence} value={LABEL[a.hairline.status] ?? a.hairline.status}
            sub={`${a.hairline.shape.text}${a.hairline.ratios ? ` Normalised distance (ratio to face width, not calibrated): ${a.hairline.ratios.hairline_to_glabella_ratio.toFixed(2)}.` : ""}`} />
          <Row testid="hair-temple-left" title="Left temple" confidence={t.left.confidence} value={LABEL[t.left.status] ?? t.left.status}
            sub={`${t.left.text} Density: ${dens(t.left.density)}.`} />
          <Row testid="hair-temple-right" title="Right temple" confidence={t.right.confidence} value={LABEL[t.right.status] ?? t.right.status}
            sub={`${t.right.text} Density: ${dens(t.right.density)}.`} />
          <Row testid="hair-symmetry" title="Hairline symmetry" confidence={a.hairline.symmetry.confidence}
            value={a.hairline.symmetry.score != null ? `${a.hairline.symmetry.score}/100 similarity` : "Not assessable"} sub={a.hairline.symmetry.note} />
          <Row testid="hair-frontal-density" title="Frontal density" confidence={a.frontal_density.confidence}
            value={LABEL[a.frontal_density.status] ?? a.frontal_density.status} sub={a.frontal_density.text} />
          <Row testid="hair-crown" title="Crown / vertex" confidence={a.crown.status === "assessed" ? a.crown.confidence : undefined}
            value={a.crown.status === "assessed" ? a.crown.density?.text ?? "Assessed" : a.crown.status === "not_assessable" ? "NOT ASSESSABLE" : "Inconclusive"}
            sub={a.crown.status === "assessed"
              ? `${a.crown.regional ? `Centre ${a.crown.regional.central_scalp_pct}% vs outer ${a.crown.regional.outer_scalp_pct}% scalp visible. ` : ""}${a.crown.parting?.visible ? `Parting: visible${a.crown.parting.widens_towards_one_end ? ", widening towards one end" : ""}.` : "Parting: not clearly visible."}`
              : a.crown.reason} />
          <Row testid="hair-longitudinal" title="Longitudinal tracking" value="Needs two check-ins"
            sub="Compare your photos over time on your progress page. Change is only reported when lighting, angle and styling are comparable." />
        </div>
      </div>
      <div className="break-avoid mt-6 rounded-2xl bg-foreground p-6 text-background" data-testid="hair-guidance">
        <h3 className="font-semibold">Hair-care guidance</h3>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-sm">{a.guidance.map((g) => <li key={g}>{g}</li>)}</ul>
      </div>
      <div className="break-avoid mt-4" data-testid="hair-limitations">
        <p className="text-sm font-medium">Limitations</p>
        <ul className="mt-1 space-y-1 text-xs text-muted">{a.limitations.map((l) => <li key={l}>• {l}</li>)}</ul>
        <p className="mt-2 text-xs font-medium text-muted">{a.validation_status}</p>
      </div>
    </div>
  );
}
