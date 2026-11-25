"use client";

import { useRef, useState } from "react";

type Preview = { key: string; title: string; description: string; image: string };

export function Previews({ before, items, note }: { before: string; items: Preview[]; note: string }) {
  const [active, setActive] = useState(items[items.length - 1]?.key ?? "");
  const item = items.find((i) => i.key === active) ?? items[0];
  return (
    <section className="mt-12">
      <h2 className="font-serif text-3xl tracking-tight">Your potential</h2>
      <p className="mt-2 text-muted">Drag the slider to compare. {note}</p>
      <div className="mt-6 grid gap-6 md:grid-cols-[minmax(0,560px)_320px]">
        <Slider before={`data:image/jpeg;base64,${before}`} after={`data:image/jpeg;base64,${item.image}`} />
        <div className="space-y-2">
          {items.map((i) => (
            <button key={i.key} onClick={() => setActive(i.key)}
              className={`block w-full rounded-2xl border p-4 text-left transition ${i.key === item.key ? "border-accent bg-accent-soft" : "border-line bg-surface hover:border-foreground"}`}>
              <p className="font-medium">{i.title}</p>
              <p className="mt-1 text-sm text-muted">{i.description}</p>
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Slider({ before, after, beforeLabel = "Before", afterLabel = "After · simulated" }: {
  before: string; after: string; beforeLabel?: string; afterLabel?: string;
}) {
  const [pos, setPos] = useState(50);
  const box = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const move = (clientX: number) => {
    const r = box.current?.getBoundingClientRect();
    if (r) setPos(Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100)));
  };

  return (
    <div
      ref={box}
      className="break-avoid relative select-none overflow-hidden rounded-3xl border border-line bg-surface"
      style={{ touchAction: "none" }}
      onPointerDown={(e) => { dragging.current = true; (e.target as HTMLElement).setPointerCapture?.(e.pointerId); move(e.clientX); }}
      onPointerMove={(e) => dragging.current && move(e.clientX)}
      onPointerUp={() => { dragging.current = false; }}
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={after} alt={afterLabel} className="block w-full" draggable={false} />
      <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={before} alt={beforeLabel} className="block w-full" draggable={false} />
      </div>
      <div className="pointer-events-none absolute inset-y-0" style={{ left: `${pos}%` }}>
        <div className="absolute inset-y-0 -ml-px w-0.5 bg-white shadow" />
        <div className="absolute top-1/2 -ml-5 -mt-5 flex h-10 w-10 items-center justify-center rounded-full bg-white text-sm shadow">⇆</div>
      </div>
      <span className="absolute left-3 top-3 rounded-full bg-black/50 px-3 py-1 text-xs text-white">{beforeLabel}</span>
      <span className="absolute right-3 top-3 rounded-full bg-black/50 px-3 py-1 text-xs text-white">{afterLabel}</span>
      <input type="range" min={0} max={100} value={pos} onChange={(e) => setPos(Number(e.target.value))}
        aria-label="Compare before and after" className="sr-only" />
    </div>
  );
}
