"use client";

import { reportHeaders } from "@/lib/auth";

import { useState } from "react";
import type { Analysis, TryOn } from "@/lib/types";

const KINDS = [["hair", "Hairstyles"], ["beard", "Beard"], ["glasses", "Glasses"]] as const;

/** AI try-on of the styles recommended in this report (paid reports, small quota per report). */
export function TryOnPanel({ data }: { data: Analysis }) {
  const [results, setResults] = useState<Record<string, TryOn>>(data.tryons ?? {});
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(Object.keys(data.tryons ?? {})[0] ?? null);
  const info = data.tryon;
  const [granted, setGranted] = useState<boolean>(!!data.tryon?.consent?.granted);
  const [declined, setDeclined] = useState(false);
  const [consentBusy, setConsentBusy] = useState(false);
  const style = data.style;
  if (!info || !style) return null;
  const used = Object.keys(results).length;
  const options = KINDS.flatMap(([kind, title]) => {
    const list = kind === "hair" ? style.hairstyles : kind === "beard" ? style.beard : style.glasses;
    return list?.length ? [{ kind, title, list }] : [];
  });

  async function setConsent(accept: boolean) {
    const d = info?.disclosure;
    if (!d) return;
    setConsentBusy(true);
    setErr(null);
    try {
      const res = await fetch(`/api/analyses/${data.id}/consent/tryon`, {
        method: "POST", headers: reportHeaders(data.id, { "Content-Type": "application/json" }),
        body: JSON.stringify({ accept, provider: d.provider, version: d.version }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Could not save your choice");
      setGranted(!!body.granted);
      if (!accept) setDeclined(false);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save your choice");
    } finally {
      setConsentBusy(false);
    }
  }

  async function run(kind: string, s: string) {
    const key = `${kind}|${s}`;
    if (results[key]) return setActive(key);
    setBusy(key);
    setErr(null);
    try {
      const res = await fetch(`/api/analyses/${data.id}/tryon`, {
        method: "POST", headers: reportHeaders(data.id, { "Content-Type": "application/json" }), body: JSON.stringify({ kind, style: s }),
      });
      const body = await res.json();
      if (res.status === 403 && body.detail?.code === "consent_required") { setGranted(false); throw new Error(body.detail.message); }
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message ?? "Try-on failed");
      setResults((r) => ({ ...r, [key]: body }));
      setActive(key);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Try-on failed");
    } finally {
      setBusy(null);
    }
  }

  const shown = active ? results[active] : null;
  return (
    <section className="mt-12 rounded-3xl border border-line bg-surface p-6 md:p-8">
      <p className="text-sm uppercase tracking-[0.2em] text-accent">Try it on</p>
      <h2 className="mt-1 font-serif text-3xl">See your recommended styles on you</h2>
      {!info.available ? (
        <p className="mt-3 text-muted">AI try-on is coming soon.</p>
      ) : !granted ? (
        <div className="mt-4 rounded-2xl border border-line bg-background p-5 text-sm">
          <p className="font-semibold">Before you use try-on: your photo is sent to {info.disclosure?.provider_name}</p>
          <p className="mt-2 inline-block rounded-full border border-line px-3 py-1 text-xs font-medium tracking-wide" data-testid="provider-policy-badge">
            PROVIDER POLICY UNVERIFIED
          </p>
          {info.disclosure && (
            <ul className="mt-3 list-disc space-y-2 pl-5 text-muted">
              <li><span className="text-foreground">Where it goes:</span> {info.disclosure.leaves_infrastructure}</li>
              <li><span className="text-foreground">Why:</span> {info.disclosure.why}</li>
              <li><span className="text-foreground">What is requested:</span> {info.disclosure.processing}</li>
              <li><span className="text-foreground">Retention:</span> {info.disclosure.retention}</li>
              <li><span className="text-foreground">Optional:</span> {info.disclosure.optional}</li>
              <li><span className="text-foreground">How long:</span> {info.disclosure.duration}</li>
            </ul>
          )}
          {declined && <p className="mt-3 text-muted">No problem — your photo was not sent. The rest of your report is unaffected.</p>}
          {err && <p className="mt-3 text-bad">{err}</p>}
          <div className="mt-4 flex flex-wrap gap-3">
            <button type="button" disabled={consentBusy} onClick={() => setConsent(true)} className="btn-primary">
              {consentBusy ? "Saving…" : `I agree — send my photo to ${info.disclosure?.provider_name ?? "the provider"}`}
            </button>
            <button type="button" disabled={consentBusy} onClick={() => setDeclined(true)} className="btn-secondary">No thanks</button>
          </div>
        </div>
      ) : (
        <>
          <p className="mt-2 text-sm text-muted">
            AI simulation on your own photo. We check every image still looks like you and that your skin colour hasn&apos;t
            changed — if not, we don&apos;t show it. {Math.max(info.quota - used, 0)} of {info.quota} try-ons left.
          </p>
          <div className="mt-6 grid gap-6 md:grid-cols-[minmax(0,420px)_1fr]">
            <div className="flex aspect-[3/4] items-center justify-center overflow-hidden rounded-2xl border border-line bg-background">
              {shown ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`data:image/jpeg;base64,${shown.image}`} alt={`You with: ${shown.style}`} className="h-full w-full object-cover" />
              ) : (
                <p className="p-6 text-center text-sm text-muted">{busy ? "Creating your preview… (about 10-30 seconds)" : "Pick a style to try"}</p>
              )}
            </div>
            <div className="space-y-5">
              {options.map(({ kind, title, list }) => (
                <div key={kind}>
                  <h3 className="font-semibold">{title}</h3>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {list.map((s) => {
                      const key = `${kind}|${s}`;
                      return (
                        <button key={key} type="button" disabled={!!busy || (!results[key] && used >= info.quota)}
                          onClick={() => run(kind, s)}
                          className={`chip ${active === key ? "chip-on" : ""} disabled:opacity-50`}>
                          {busy === key ? "Creating…" : results[key] ? `✓ ${s}` : s}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
              {shown && <p className="text-xs text-muted">AI simulation · passed our same-person and skin-colour checks</p>}
              <button type="button" disabled={consentBusy} onClick={() => setConsent(false)} className="text-xs text-muted underline">
                Withdraw my consent to share my photo
              </button>
              {err && <p className="text-sm text-bad">{err}</p>}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
