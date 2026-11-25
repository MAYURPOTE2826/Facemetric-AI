"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Analysis } from "@/lib/types";

const W = 1080;
const H = 1350;
const C = {
  bg: "#f6f3ee", ink: "#1b1a17", muted: "#6f6a61", line: "#e4ded3", accent: "#b5652f",
  good: "#3f7d58", warn: "#b58a2f", bad: "#b5452f", surface: "#ffffff",
};
const LABELS: Record<string, string> = {
  eyes: "Eyes", proportions: "Proportions", lips: "Lips & mouth", nose: "Nose", jaw: "Jaw",
  symmetry: "Symmetry", profile: "Side profile", three_quarter: "Jawline",
};
const scoreColor = (s: number) => (s >= 75 ? C.good : s >= 50 ? C.warn : C.bad);

function fontFamily(variable: string, fallback: string) {
  const v = getComputedStyle(document.body).getPropertyValue(variable).trim();
  return v || fallback;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

function wrap(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  const words = text.split(" ");
  const lines: string[] = [];
  let line = "";
  for (const w of words) {
    const test = line ? `${line} ${w}` : w;
    if (ctx.measureText(test).width > maxWidth && line) {
      lines.push(line);
      line = w;
    } else line = test;
  }
  if (line) lines.push(line);
  return lines;
}

async function drawCard(canvas: HTMLCanvasElement, data: Analysis, withPhoto: boolean) {
  await document.fonts.ready;
  const serif = fontFamily("--font-fraunces", "Georgia, serif");
  const sans = fontFamily("--font-inter", "Arial, sans-serif");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d")!;
  const pad = 80;

  ctx.fillStyle = C.bg;
  ctx.fillRect(0, 0, W, H);

  // Header
  ctx.fillStyle = C.accent;
  ctx.font = `600 26px ${sans}`;
  ctx.letterSpacing = "6px";
  ctx.fillText("FACEMETRIC-AI · FACIAL ANALYSIS", pad, pad + 20);
  ctx.letterSpacing = "0px";
  ctx.fillStyle = C.ink;
  ctx.font = `400 68px ${serif}`;
  ctx.fillText(data.profile.name ? `${data.profile.name}'s results` : "My results", pad, pad + 110);

  // Score ring
  const ringX = withPhoto ? pad + 170 : W / 2;
  const ringY = 430;
  const r = 150;
  ctx.lineWidth = 26;
  ctx.lineCap = "round";
  ctx.strokeStyle = C.line;
  ctx.beginPath();
  ctx.arc(ringX, ringY, r, 0, Math.PI * 2);
  ctx.stroke();
  ctx.strokeStyle = C.accent;
  ctx.beginPath();
  ctx.arc(ringX, ringY, r, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * data.harmony_score) / 100);
  ctx.stroke();
  ctx.fillStyle = C.ink;
  ctx.textAlign = "center";
  ctx.font = `400 120px ${serif}`;
  ctx.fillText(String(Math.round(data.harmony_score)), ringX, ringY + 40);
  ctx.font = `500 26px ${sans}`;
  ctx.fillStyle = C.muted;
  ctx.fillText("Proportion harmony", ringX, ringY + r + 70);
  ctx.textAlign = "left";

  // Optional photo
  if (withPhoto) {
    const img = await loadImage(`data:image/jpeg;base64,${data.annotated_image}`);
    const bw = 420;
    const bh = 520;
    const bx = W - pad - bw;
    const by = 190;
    ctx.save();
    ctx.beginPath();
    ctx.roundRect(bx, by, bw, bh, 36);
    ctx.clip();
    const s = Math.max(bw / img.width, bh / img.height);
    ctx.drawImage(img, bx + (bw - img.width * s) / 2, by + (bh - img.height * s) / 2, img.width * s, img.height * s);
    ctx.restore();
  }

  // Category bars
  let y = 750;
  const entries = Object.entries(data.category_scores).slice(0, 8);
  const colW = (W - pad * 2 - 60) / 2;
  const rowH = 66;
  entries.forEach(([k, v], i) => {
    const x = pad + (i % 2) * (colW + 60);
    const yy = y + Math.floor(i / 2) * rowH;
    ctx.fillStyle = C.ink;
    ctx.font = `500 26px ${sans}`;
    ctx.fillText(LABELS[k] ?? k, x, yy);
    ctx.textAlign = "right";
    ctx.fillStyle = scoreColor(v);
    ctx.font = `600 26px ${sans}`;
    ctx.fillText(String(Math.round(v)), x + colW, yy);
    ctx.textAlign = "left";
    ctx.fillStyle = C.line;
    ctx.beginPath();
    ctx.roundRect(x, yy + 16, colW, 10, 5);
    ctx.fill();
    ctx.fillStyle = scoreColor(v);
    ctx.beginPath();
    ctx.roundRect(x, yy + 16, Math.max(10, (colW * v) / 100), 10, 5);
    ctx.fill();
  });
  y += Math.ceil(entries.length / 2) * rowH + 20;

  // Strengths
  const strengths = data.report.strengths.slice(0, 3);
  if (strengths.length && y < H - 230) {
    ctx.fillStyle = C.ink;
    ctx.font = `600 28px ${sans}`;
    ctx.fillText("Strengths", pad, y);
    y += 46;
    ctx.font = `400 26px ${sans}`;
    for (const s of strengths) {
      for (const [li, line] of wrap(ctx, s, W - pad * 2 - 44).entries()) {
        if (y > H - 170) break;
        if (li === 0) {
          ctx.fillStyle = C.good;
          ctx.fillText("✦", pad, y);
        }
        ctx.fillStyle = C.ink;
        ctx.fillText(line, pad + 44, y);
        y += 38;
      }
    }
  }

  // Footer
  ctx.strokeStyle = C.line;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(pad, H - 130);
  ctx.lineTo(W - pad, H - 130);
  ctx.stroke();
  ctx.fillStyle = C.ink;
  ctx.font = `600 28px ${sans}`;
  ctx.fillText(`Get your analysis → ${window.location.host}`, pad, H - 80);
  ctx.fillStyle = C.muted;
  ctx.font = `400 20px ${sans}`;
  ctx.fillText("Measured proportions · not an attractiveness rating", pad, H - 46);
}

export function ShareButton({ data }: { data: Analysis }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} className="no-print btn-secondary">Share results</button>
      {open && <ShareModal data={data} onClose={() => setOpen(false)} />}
    </>
  );
}

function ShareModal({ data, onClose }: { data: Analysis; onClose: () => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [withPhoto, setWithPhoto] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const render = useCallback(async () => {
    if (!canvas.current) return;
    await drawCard(canvas.current, data, withPhoto);
    setUrl(canvas.current.toDataURL("image/png"));
  }, [data, withPhoto]);

  useEffect(() => {
    render();
  }, [render]);

  async function share() {
    if (!canvas.current) return;
    const blob = await new Promise<Blob | null>((r) => canvas.current!.toBlob(r, "image/png"));
    if (!blob) return;
    const file = new File([blob], "aurea-results.png", { type: "image/png" });
    if (navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], title: "My Facemetric-AI results" }).catch(() => {});
    } else {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "aurea-results.png";
      a.click();
    }
  }

  async function copyLink() {
    await navigator.clipboard.writeText(`${window.location.origin}/`).catch(() => {});
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="no-print fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div className="max-h-full w-full max-w-md overflow-auto rounded-3xl bg-background p-5" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-serif text-2xl">Share your results</h2>
          <button onClick={onClose} className="text-2xl leading-none text-muted" aria-label="Close">×</button>
        </div>
        <canvas ref={canvas} className="hidden" />
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt="Share card preview" className="w-full rounded-2xl border border-line" />
        ) : (
          <div className="aspect-[4/5] w-full animate-pulse rounded-2xl bg-line" />
        )}
        <label className="mt-4 flex items-center gap-2 text-sm">
          <input type="checkbox" checked={withPhoto} onChange={(e) => setWithPhoto(e.target.checked)} />
          Include my photo
        </label>
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button onClick={share} className="btn-primary !px-4">Share / save image</button>
          <button onClick={copyLink} className="btn-secondary !px-4">{copied ? "Link copied" : "Copy link"}</button>
        </div>
        <p className="mt-3 text-xs text-muted">Your photo is only included if you tick the box. The image is made on your device.</p>
      </div>
    </div>
  );
}
