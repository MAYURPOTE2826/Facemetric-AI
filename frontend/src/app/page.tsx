import Link from "next/link";

const steps = [
  { n: "01", title: "Tell us about you", body: "Age, goals and budget so every recommendation fits your life." },
  { n: "02", title: "Upload a photo", body: "We check pose, lighting and focus, then map 478 facial landmarks." },
  { n: "03", title: "Get your report", body: "Measured proportions, strengths, and a 90-day non-surgical plan." },
];

const features = [
  ["13 measured markers", "Canthal tilt, facial thirds, midface ratio, jaw width, symmetry and more, compared with published reference ranges."],
  ["Explained, not judged", "Each number is explained in plain language. We highlight strengths first and never rank your attractiveness."],
  ["Non-surgical first", "Grooming, skincare, lifestyle and makeup methods ranked by cost and time before anything clinical."],
  ["Skin snapshot", "An early look at redness, tone evenness and texture, with a routine to match."],
];

export default function Home() {
  return (
    <main>
      <section className="mx-auto grid max-w-6xl gap-12 px-5 py-20 md:grid-cols-[1.2fr_1fr] md:py-28">
        <div>
          <p className="mb-5 text-sm uppercase tracking-[0.2em] text-accent">Facial analysis</p>
          <h1 className="font-serif text-5xl leading-[1.05] tracking-tight md:text-7xl">
            Understand your face, measurably.
          </h1>
          <p className="mt-6 max-w-lg text-lg text-muted">
            Facemetric-AI maps your facial proportions from a single photo and turns them into a clear, personal plan to look
            your best — without surgery.
          </p>
          <div className="mt-10 flex flex-wrap gap-3">
            <Link href="/analyze" className="rounded-full bg-accent px-7 py-3.5 font-medium text-white hover:opacity-90">
              Analyse my face
            </Link>
            <a href="#how" className="rounded-full border border-line px-7 py-3.5 font-medium hover:bg-surface">
              How it works
            </a>
          </div>
        </div>
        <div className="relative aspect-[4/5] overflow-hidden rounded-[2rem] border border-line bg-surface">
          <svg viewBox="0 0 400 500" className="h-full w-full">
            <ellipse cx="200" cy="245" rx="130" ry="175" fill="none" stroke="var(--line)" strokeWidth="2" />
            {[130, 230, 330, 420].map((y) => (
              <line key={y} x1="60" x2="340" y1={y} y2={y} stroke="var(--accent)" strokeDasharray="4 6" />
            ))}
            <line x1="200" x2="200" y1="60" y2="440" stroke="var(--accent)" strokeOpacity="0.5" />
            <path d="M120 200 L175 205 M225 205 L280 200" stroke="var(--foreground)" strokeWidth="3" strokeLinecap="round" />
            <circle cx="148" cy="203" r="5" fill="var(--accent)" />
            <circle cx="252" cy="203" r="5" fill="var(--accent)" />
            <path d="M178 300 Q200 312 222 300" stroke="var(--foreground)" strokeWidth="2" fill="none" />
            <path d="M165 360 Q200 380 235 360" stroke="var(--foreground)" strokeWidth="2.5" fill="none" />
            <text x="345" y="134" fontSize="12" fill="var(--muted)">⅓</text>
            <text x="345" y="234" fontSize="12" fill="var(--muted)">⅓</text>
            <text x="345" y="334" fontSize="12" fill="var(--muted)">⅓</text>
          </svg>
          <div className="absolute bottom-5 left-5 right-5 rounded-2xl bg-background/90 p-4 backdrop-blur">
            <div className="flex items-baseline justify-between">
              <span className="text-sm text-muted">Harmony score</span>
              <span className="font-serif text-3xl">82</span>
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-line">
              <div className="h-full w-[82%] rounded-full bg-accent" />
            </div>
          </div>
        </div>
      </section>

      <section id="how" className="border-y border-line bg-surface">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-16 md:grid-cols-3">
          {steps.map((s) => (
            <div key={s.n}>
              <p className="font-serif text-3xl text-accent">{s.n}</p>
              <h3 className="mt-3 text-lg font-semibold">{s.title}</h3>
              <p className="mt-2 text-muted">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-5 py-20">
        <h2 className="font-serif text-4xl tracking-tight">What&apos;s in your report</h2>
        <div className="mt-10 grid gap-5 md:grid-cols-2">
          {features.map(([t, b]) => (
            <div key={t} className="rounded-2xl border border-line bg-surface p-6">
              <h3 className="font-semibold">{t}</h3>
              <p className="mt-2 text-muted">{b}</p>
            </div>
          ))}
        </div>
        <p className="mt-12 text-sm text-muted">
          Facemetric-AI is an educational tool and does not provide medical advice. Consult a licensed professional before any
          clinical treatment.
        </p>
      </section>
    </main>
  );
}
