"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { GuidedFrontCamera, SideTimerCamera, type BlinkSamples, type LandmarkFrames } from "@/components/Cameras";
import { authHeaders, saveReportToken, useUser } from "@/lib/auth";
import type { HairAnswers, Profile, Quality } from "@/lib/types";

const GOALS = ["Sharper jawline", "Better skin", "Eye area", "Facial balance", "Lips", "Hair & grooming", "Look less tired", "Overall glow-up"];
const ETHNICITIES = ["Prefer not to say", "East Asian", "South Asian", "Southeast Asian", "Black / African", "White / European", "Hispanic / Latino", "Middle Eastern / North African", "Mixed / Other"];
const BUDGETS = ["Minimal (under ₹500/month)", "₹500–1,500/month", "₹1,500–3,000/month", "₹3,000+/month"];
const SKIN_TYPES = ["Oily", "Combination", "Normal", "Dry", "Sensitive"];
const EVENTS = [["own_wedding", "My wedding"], ["family_wedding", "A family wedding"], ["festival", "Festival"], ["other", "Other big day"]] as const;

const CITIES = ["Agra", "Ahmedabad", "Amritsar", "Bengaluru", "Bhopal", "Bhubaneswar", "Chandigarh", "Chennai", "Coimbatore", "Darjeeling", "Dehradun", "Delhi NCR", "Goa", "Guwahati", "Hyderabad", "Imphal", "Indore", "Jaipur", "Jodhpur", "Kanpur", "Kochi", "Kolkata", "Lucknow", "Ludhiana", "Manali", "Mangaluru", "Mumbai", "Mysuru", "Nagpur", "Nashik", "Ooty", "Patna", "Pune", "Raipur", "Rajkot", "Ranchi", "Shillong", "Shimla", "Srinagar", "Surat", "Thiruvananthapuram", "Varanasi", "Visakhapatnam"];
// Hairs lost per hair wash - the refined wash test (~28 normal, ~52 pattern loss, ~126 shock shedding).
const HAIR_WASH = [["under50", "Under 50"], ["50to100", "50–100"], ["over100", "Over 100"]] as const;
const HAIR_DURATION = [["weeks", "A few weeks"], ["months", "1–6 months"], ["long", "Over 6 months"]] as const;
const HAIR_FLAGS = [["scalp_pain", "Scalp pain, burning or shiny patches"], ["brows_lashes", "Losing eyebrow / eyelash hair"],
  ["androgen", "Acne, extra facial/body hair or deeper voice"], ["weight_loss_fever", "Unexplained weight loss or fever"],
  ["new_medicine", "Started a new medicine"], ["tight_styles", "Tight buns, braids or extensions"]] as const;
const SAFETY = [["pregnant", "Pregnant"], ["breastfeeding", "Breastfeeding"], ["isotretinoin", "Taking isotretinoin (e.g. Isotroin)"],
  ["steroid_history", "Used steroid or 'fairness' creams"], ["skin_condition", "Eczema, psoriasis or rosacea"],
  ["prescribed_skin_treatment", "Using a prescribed skin treatment"]] as const;
const SUN = [["indoor", "Mostly indoors"], ["two_wheeler", "Commute on a two-wheeler"], ["outdoor", "Work outdoors"]] as const;
const HAIR_PATTERN = [["overall", "All over"], ["temples", "Receding temples"], ["crown", "Crown"], ["parting", "Widening parting"], ["patches", "Round bald patches"]] as const;
const HAIR_TRIGGERS = [["illness", "Recent fever / illness"], ["stress", "Major stress"], ["crash_diet", "Crash diet / weight loss"], ["childbirth", "Had a baby"], ["surgery", "Surgery"], ["thyroid", "Known thyroid issue"]] as const;

const PROGRESS = ["Mapping 478 landmarks…", "Correcting head pose…", "Measuring proportions…", "Checking skin…", "Writing your report…"];

async function readError(res: Response) {
  try {
    const body = await res.json();
    const d = body.detail;
    if (typeof d === "string") return { message: d };
    return { message: d?.message ?? "Something went wrong.", quality: d?.quality as Quality | undefined };
  } catch {
    return { message: `Server error (${res.status}). Is the backend running?` };
  }
}

export default function AnalyzePage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [profile, setProfile] = useState<Profile>({
    name: "", age: "", sex: "", ethnicity: ETHNICITIES[0], goals: [], budget: BUDGETS[1], notes: "", skin_type: "",
  });
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [quality, setQuality] = useState<Quality | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [side, setSide] = useState<SideState>(EMPTY_SLOT);
  const [tq, setTq] = useState<SideState>(EMPTY_SLOT);
  const [top, setTop] = useState<SideState>(EMPTY_SLOT);
  const [frames, setFrames] = useState<LandmarkFrames | undefined>(undefined);
  const [blinks, setBlinks] = useState<BlinkSamples | undefined>(undefined);
  const [source, setSource] = useState<"camera" | "upload">("upload");
  const user = useUser();

  const set = <K extends keyof Profile>(k: K, v: Profile[K]) => setProfile((p) => ({ ...p, [k]: v }));
  const toggleGoal = (g: string) =>
    set("goals", profile.goals.includes(g) ? profile.goals.filter((x) => x !== g) : [...profile.goals, g]);

  async function choosePhoto(f: File, camFrames?: LandmarkFrames, fromCamera = false, camBlinks?: BlinkSamples) {
    setBlinks(camBlinks);
    setFile(f);
    setFrames(camFrames);
    setSource(fromCamera ? "camera" : "upload");
    setPreview(URL.createObjectURL(f));
    setQuality(null);
    setError(null);
    setChecking(true);
    const fd = new FormData();
    fd.append("front", f);
    fd.append("source", fromCamera ? "camera" : "upload");
    try {
      const res = await fetch("/api/check", { method: "POST", body: fd });
      if (!res.ok) setError((await readError(res)).message);
      else setQuality(await res.json());
    } catch {
      setError("Could not reach the server.");
    } finally {
      setChecking(false);
    }
  }

  async function analyze() {
    if (!file) return;
    setStep(3);
    setError(null);
    setProgress(0);
    const timer = setInterval(() => setProgress((p) => Math.min(p + 1, PROGRESS.length - 1)), 2500);
    const fd = new FormData();
    fd.append("front", file);
    if (side.file && side.ok) fd.append("side", side.file);
    if (tq.file && tq.ok) fd.append("three_quarter", tq.file);
    if (top.file && top.ok) fd.append("top", top.file);
    fd.append("profile", JSON.stringify(profile));
    fd.append("source", source);
    if (frames) fd.append("frames", JSON.stringify(frames));
    if (blinks) fd.append("blinks", JSON.stringify(blinks));
    try {
      const res = await fetch("/api/analyze", { method: "POST", body: fd, headers: authHeaders() });
      if (!res.ok) {
        const e = await readError(res);
        setError(e.message);
        if (e.quality) setQuality(e.quality);
        setStep(2);
        return;
      }
      const data = await res.json();
      if (data.access_token) saveReportToken(data.id, data.access_token);
      router.push(`/report/${data.id}`);
    } catch {
      setError("Could not reach the server.");
      setStep(2);
    } finally {
      clearInterval(timer);
    }
  }

  const profileValid = profile.age && profile.sex;

  return (
    <main className="mx-auto max-w-3xl px-5 py-12">
      <ol className="mb-10 flex gap-2 text-sm">
        {["About you", "Photo", "Analysis"].map((label, i) => (
          <li key={label} className={`flex-1 border-t-2 pt-2 ${step >= i + 1 ? "border-accent text-foreground" : "border-line text-muted"}`}>
            {label}
          </li>
        ))}
      </ol>

      {step === 1 && (
        <section className="space-y-7">
          <h1 className="font-serif text-4xl tracking-tight">A little about you</h1>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="First name (optional)">
              <input className="input" value={profile.name} onChange={(e) => set("name", e.target.value)} />
            </Field>
            <Field label="Age">
              <input className="input" type="number" min={18} max={99} value={profile.age} onChange={(e) => set("age", e.target.value)} />
            </Field>
            <Field label="Sex (used for reference ranges)">
              <div className="flex gap-2">
                {["Male", "Female"].map((s) => (
                  <button key={s} type="button" onClick={() => set("sex", s.toLowerCase())}
                    className={`chip flex-1 ${profile.sex === s.toLowerCase() ? "chip-on" : ""}`}>{s}</button>
                ))}
              </div>
            </Field>
            <Field label="Ethnic background">
              <select className="input" value={profile.ethnicity} onChange={(e) => set("ethnicity", e.target.value)}>
                {ETHNICITIES.map((x) => <option key={x}>{x}</option>)}
              </select>
            </Field>
          </div>
          <Field label="What would you like to improve?">
            <div className="flex flex-wrap gap-2">
              {GOALS.map((g) => (
                <button key={g} type="button" onClick={() => toggleGoal(g)}
                  className={`chip ${profile.goals.includes(g) ? "chip-on" : ""}`}>{g}</button>
              ))}
            </div>
          </Field>
          <Field label="Your skin type">
            <div className="flex flex-wrap gap-2">
              {SKIN_TYPES.map((t) => (
                <button key={t} type="button" onClick={() => set("skin_type", t.toLowerCase())}
                  className={`chip ${profile.skin_type === t.toLowerCase() ? "chip-on" : ""}`}>{t}</button>
              ))}
            </div>
          </Field>
          <Field label="Your city (we tune your routine to its climate and the season)">
            <select className="input" value={profile.city ?? ""} onChange={(e) => set("city", e.target.value || undefined)}>
              <option value="">Select your city</option>
              {CITIES.map((c) => <option key={c}>{c}</option>)}
              <option value="">Other / not listed</option>
            </select>
          </Field>
          <Field label="Anything we should know for safety? (optional — changes which products we suggest)">
            <div className="flex flex-wrap gap-2">
              {SAFETY.map(([k, label]) => {
                const on = !!profile.safety?.includes(k);
                return (
                  <button key={k} type="button" className={`chip ${on ? "chip-on" : ""}`}
                    onClick={() => set("safety", on ? profile.safety!.filter((x) => x !== k) : [...(profile.safety ?? []), k])}>{label}</button>
                );
              })}
            </div>
          </Field>
          <Field label="Do you have dark, thick, velvety skin on the back of your neck or in your underarms?">
            <div className="flex flex-wrap gap-2">
              {([["yes", "Yes"], ["no", "No / not sure"]] as const).map(([k, label]) => {
                const on = k === "yes" ? !!profile.skin_signs?.includes("neck_dark") : !profile.skin_signs?.includes("neck_dark");
                return (
                  <button key={k} type="button" className={`chip ${on ? "chip-on" : ""}`}
                    onClick={() => set("skin_signs", k === "yes" ? ["neck_dark"] : [])}>{label}</button>
                );
              })}
            </div>
          </Field>
          <Field label="Daily sun exposure">
            <div className="flex flex-wrap gap-2">
              {SUN.map(([k, label]) => (
                <button key={k} type="button" onClick={() => set("sun", profile.sun === k ? undefined : k)}
                  className={`chip ${profile.sun === k ? "chip-on" : ""}`}>{label}</button>
              ))}
            </div>
          </Field>
          <Field label="Worried about hair fall? (optional — adds a hair check)">
            <div className="flex gap-2">
              {(["Yes", "No"] as const).map((x) => (
                <button key={x} type="button" onClick={() => set("hair", x === "Yes" ? (profile.hair ?? {}) : undefined)}
                  className={`chip ${(x === "Yes") === !!profile.hair ? "chip-on" : ""}`}>{x}</button>
              ))}
            </div>
            {profile.hair && <HairQuestions value={profile.hair} sex={profile.sex} onChange={(h) => set("hair", h)} />}
          </Field>
          <Field label="Big day coming up? (optional — we'll build a dated glow-up countdown)">
            <div className="flex flex-wrap gap-2">
              {EVENTS.map(([k, label]) => (
                <button key={k} type="button"
                  onClick={() => set("event", profile.event?.type === k ? undefined : { type: k, date: profile.event?.date ?? "" })}
                  className={`chip ${profile.event?.type === k ? "chip-on" : ""}`}>{label}</button>
              ))}
            </div>
            {profile.event && (
              <input type="date" className="input mt-2 max-w-xs" min={new Date().toISOString().slice(0, 10)}
                value={profile.event.date} onChange={(e) => set("event", { ...profile.event!, date: e.target.value })} />
            )}
          </Field>
          <Field label="Monthly budget">
            <div className="flex flex-wrap gap-2">
              {BUDGETS.map((b) => (
                <button key={b} type="button" onClick={() => set("budget", b)}
                  className={`chip ${profile.budget === b ? "chip-on" : ""}`}>{b}</button>
              ))}
            </div>
          </Field>
          <Field label="Anything else? (e.g. can't grow a beard, no makeup, wear glasses)">
            <textarea className="input min-h-24" value={profile.notes} onChange={(e) => set("notes", e.target.value)} />
          </Field>
          <button disabled={!profileValid} onClick={() => setStep(2)} className="btn-primary">Continue</button>
        </section>
      )}

      {step === 2 && (
        <section className="space-y-6">
          <h1 className="font-serif text-4xl tracking-tight">Your photos</h1>
          <h2 className="text-lg font-semibold">1. Front photo <span className="text-sm font-normal text-muted">(required)</span></h2>
          <ul className="grid gap-2 text-sm text-muted sm:grid-cols-2">
            <li>• Face the camera straight on, eye level</li>
            <li>• Neutral expression, mouth closed</li>
            <li>• Soft, even light (face a window)</li>
            <li>• Hair off the face, no glasses</li>
          </ul>

          <div className="grid gap-5 sm:grid-cols-[1fr_1fr]">
            <div className="aspect-[3/4] overflow-hidden rounded-2xl border border-line bg-surface">
              {preview ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={preview} alt="Your photo" className="h-full w-full object-cover" />
              ) : (
                <GuidedFrontCamera onCapture={(f, fr, bl) => choosePhoto(f, fr, true, bl)} />
              )}
            </div>
            <div className="space-y-4">
              <label className="btn-secondary block cursor-pointer text-center">
                {preview ? "Choose a different photo" : "Upload a photo"}
                <input type="file" accept="image/*" className="hidden"
                  onChange={(e) => e.target.files?.[0] && choosePhoto(e.target.files[0])} />
              </label>
              {preview && (
                <button className="btn-secondary w-full" onClick={() => { setPreview(null); setFile(null); setQuality(null); }}>
                  Use camera instead
                </button>
              )}
              {checking && <p className="text-sm text-muted">Checking photo quality…</p>}
              {quality && <QualityPanel q={quality} />}
              {error && <p className="rounded-xl bg-bad/10 p-3 text-sm text-bad">{error}</p>}
            </div>
          </div>

          <OptionalPhoto kind="side" sex={profile.sex} state={side} onChange={setSide} />
          <OptionalPhoto kind="three_quarter" sex={profile.sex} state={tq} onChange={setTq} />
          <p className="rounded-xl bg-surface p-3 text-sm" data-testid="hair-capture-explainer">
            <b>Hair photos (optional).</b> Front photo → hairline and temples. Top-of-head photo → crown and parting. Without a top photo the crown is
            reported as <i>not assessable</i>. Use daylight, dry hair in its natural position, no cap, no filter.
          </p>
          <OptionalPhoto kind="top" sex={profile.sex} state={top} onChange={setTop} />

          {user === null && (
            <p className="rounded-xl bg-accent-soft/60 p-3 text-sm">
              <Link href="/login?next=/analyze" className="font-medium text-accent hover:underline">Sign in</Link> to save this
              analysis and track your skin and hair over time.
            </p>
          )}

          <div className="flex gap-3">
            <button className="btn-secondary" onClick={() => setStep(1)}>Back</button>
            <button className="btn-primary" disabled={!file || checking || side.checking || tq.checking || top.checking || (quality ? !quality.ok : true)} onClick={analyze}>
              Analyse my face
            </button>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="flex flex-col items-center py-20 text-center">
          <div className="h-16 w-16 animate-spin rounded-full border-4 border-line border-t-accent" />
          <h1 className="mt-8 font-serif text-3xl">Analysing</h1>
          <p className="mt-3 text-muted">{PROGRESS[progress]}</p>
          <p className="mt-1 text-xs text-muted">This usually takes under a minute.</p>
        </section>
      )}
    </main>
  );
}

type SideState = { file: File | null; checking: boolean; ok: boolean; message?: string; notes?: string[]; preview?: string };

const EMPTY_SLOT: SideState = { file: null, checking: false, ok: false };

const OPTIONAL_PHOTOS = {
  side: {
    title: "2. Side profile",
    adds: "adds nose, lip, chin & jaw-neck angles",
    endpoint: "/api/check-side",
    tips: ["Turn fully side-on (90°), look straight ahead", "Plain wall that contrasts with your skin and hair",
      "Hair behind the ear, chin level, neck visible", "Ask someone to take it, or use a timer"],
    checking: "Tracing your profile…",
    success: "✓ Profile traced. Check the dots sit on your brow, nose, lips and chin.",
    cameraPrompt: "Turn side-on now and hold still",
  },
  three_quarter: {
    title: "3. Three-quarter view",
    adds: "adds your jaw (gonial) angle",
    endpoint: "/api/check-three-quarter",
    tips: ["Turn your head about 45° — both eyes still visible", "Chin level, jaw and neck visible",
      "Hair off the jaw and cheek", "Same plain background and soft light"],
    checking: "Measuring your jawline…",
    success: "✓ Jawline traced. Check the white line follows your jaw.",
    cameraPrompt: "Turn about 45° and hold still",
  },
  top: {
    title: "4. Top of head",
    adds: "checks thinning at the crown and parting",
    endpoint: "/api/check-top",
    tips: ["Ask someone to photograph the top of your head from above", "Bright, even light (daylight is best)",
      "Dry hair, combed into your usual parting", "Hold the camera about 30 cm away"],
    checking: "Checking scalp coverage…",
    success: "✓ Hair traced. Red shows scalp visible through the hair.",
    cameraPrompt: "Tilt your head down towards the camera",
  },
} as const;

function OptionalPhoto({ kind, sex, state, onChange }: {
  kind: keyof typeof OPTIONAL_PHOTOS; sex: string; state: SideState; onChange: (s: SideState) => void;
}) {
  const cfg = OPTIONAL_PHOTOS[kind];
  async function choose(f: File) {
    const raw = URL.createObjectURL(f);
    onChange({ file: f, checking: true, ok: false, preview: raw });
    const fd = new FormData();
    fd.append(kind, f);
    fd.append("sex", sex || "unspecified");
    try {
      const res = await fetch(cfg.endpoint, { method: "POST", body: fd });
      if (!res.ok) {
        onChange({ file: f, checking: false, ok: false, preview: raw, message: (await readError(res)).message });
        return;
      }
      const d = await res.json();
      onChange({
        file: f, checking: false, ok: d.ok, message: d.message, notes: d.notes,
        preview: d.annotated_image ? `data:image/jpeg;base64,${d.annotated_image}` : raw,
      });
    } catch {
      onChange({ file: f, checking: false, ok: false, preview: raw, message: "Could not reach the server." });
    }
  }

  return (
    <div className="space-y-4 border-t border-line pt-6">
      <h2 className="text-lg font-semibold">
        {cfg.title} <span className="text-sm font-normal text-muted">(optional — {cfg.adds})</span>
      </h2>
      <ul className="grid gap-2 text-sm text-muted sm:grid-cols-2">
        {cfg.tips.map((t) => <li key={t}>• {t}</li>)}
      </ul>
      <div className="grid gap-5 sm:grid-cols-[1fr_1fr]">
        <div className="flex aspect-[3/4] items-center justify-center overflow-hidden rounded-2xl border border-line bg-surface">
          {state.preview ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={state.preview} alt={cfg.title} className="h-full w-full object-contain" />
          ) : (
            <SideTimerCamera onCapture={choose} prompt={cfg.cameraPrompt} />
          )}
        </div>
        <div className="space-y-4">
          <label className="btn-secondary block cursor-pointer text-center">
            {state.file ? "Choose a different photo" : "Upload photo"}
            <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && choose(e.target.files[0])} />
          </label>
          {state.file && (
            <button className="btn-secondary w-full" onClick={() => onChange(EMPTY_SLOT)}>Skip this photo</button>
          )}
          {state.checking && <p className="text-sm text-muted">{cfg.checking}</p>}
          {!state.checking && state.file && state.ok && (
            <p className="rounded-xl bg-good/10 p-3 text-sm text-good">{cfg.success}</p>
          )}
          {state.notes?.map((n) => <p key={n} className="rounded-xl bg-warn/10 p-3 text-sm text-warn">{n}</p>)}
          {!state.checking && state.file && !state.ok && (
            <p className="rounded-xl bg-bad/10 p-3 text-sm text-bad">{state.message} You can retake it or continue without it.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function HairQuestions({ value, sex, onChange }: { value: HairAnswers; sex: string; onChange: (h: HairAnswers) => void }) {
  const set = <K extends keyof HairAnswers>(k: K, v: HairAnswers[K]) => onChange({ ...value, [k]: v });
  const toggle = (k: "pattern" | "triggers" | "flags", v: string) => {
    const cur = value[k] ?? [];
    set(k, cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v]);
  };
  const chips = <T extends string>(opts: readonly (readonly [T, string])[], on: (k: T) => boolean, click: (k: T) => void) => (
    <div className="flex flex-wrap gap-2">
      {opts.map(([k, label]) => (
        <button key={k} type="button" onClick={() => click(k)} className={`chip ${on(k) ? "chip-on" : ""}`}>{label}</button>
      ))}
    </div>
  );
  return (
    <div className="mt-3 space-y-4 rounded-2xl border border-line bg-surface p-4">
      <Field label="Roughly how many hairs come out when you wash your hair?">
        {chips(HAIR_WASH, (k) => value.wash === k, (k) => set("wash", k))}
      </Field>
      <Field label="For how long?">{chips(HAIR_DURATION, (k) => value.duration === k, (k) => set("duration", k))}</Field>
      <Field label="Where do you notice it? (pick any)">{chips(HAIR_PATTERN, (k) => !!value.pattern?.includes(k), (k) => toggle("pattern", k))}</Field>
      <Field label="Anything in the last 6 months? (pick any)">{chips(HAIR_TRIGGERS, (k) => !!value.triggers?.includes(k), (k) => toggle("triggers", k))}</Field>
      <Field label="Any of these? (pick any — they help us spot when to see a doctor)">
        {chips(HAIR_FLAGS, (k) => !!value.flags?.includes(k), (k) => toggle("flags", k))}
      </Field>
      <Field label="Diet">{chips([["veg", "Vegetarian"], ["nonveg", "Non-vegetarian"], ["vegan", "Vegan"]] as const, (k) => value.diet === k, (k) => set("diet", k))}</Field>
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => set("fall", value.fall === "clumps" ? undefined : "clumps")}
          className={`chip ${value.fall === "clumps" ? "chip-on" : ""}`}>Coming out in clumps</button>
        <button type="button" onClick={() => set("short_hairs", !value.short_hairs)}
          className={`chip ${value.short_hairs ? "chip-on" : ""}`}>Many short, thin hairs in what falls</button>
        <button type="button" onClick={() => set("family", !value.family)} className={`chip ${value.family ? "chip-on" : ""}`}>Parents / siblings have hair loss</button>
        <button type="button" onClick={() => set("dandruff", !value.dandruff)} className={`chip ${value.dandruff ? "chip-on" : ""}`}>Dandruff or itchy scalp</button>
        {sex === "female" && (
          <button type="button" onClick={() => set("periods", !value.periods)} className={`chip ${value.periods ? "chip-on" : ""}`}>Irregular periods / PCOS</button>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <p className="text-sm font-medium">{label}</p>
      {children}
    </div>
  );
}

function QualityPanel({ q }: { q: Quality }) {
  if (q.issues.length === 0)
    return <p className="rounded-xl bg-good/10 p-3 text-sm text-good">✓ Photo looks great.</p>;
  return (
    <ul className="space-y-2">
      {q.issues.map((i) => (
        <li key={i.code} className={`rounded-xl p-3 text-sm ${i.level === "error" ? "bg-bad/10 text-bad" : "bg-warn/10 text-warn"}`}>
          {i.message}
        </li>
      ))}
    </ul>
  );
}
