"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { evaluate, loadFaceLandmarker, measureLighting, type CheckKey, type GuideState, type Lighting } from "@/lib/faceGuide";

const CHECK_LABELS: Record<CheckKey, string> = { distance: "Distance", straight: "Straight", light: "Lighting", expression: "Neutral" };
const READY_HOLD_MS = 700;
const COUNTDOWN_S = 3;

function useCameraStream(facingMode: "user" | "environment") {
  const video = useRef<HTMLVideoElement>(null);
  const [status, setStatus] = useState<"idle" | "starting" | "on" | "error">("idle");

  const stop = useCallback(() => {
    (video.current?.srcObject as MediaStream | null)?.getTracks().forEach((t) => t.stop());
    if (video.current) video.current.srcObject = null;
  }, []);

  const start = useCallback(async () => {
    setStatus("starting");
    stop();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode, width: { ideal: 1920 }, height: { ideal: 1440 } },
        audio: false,
      });
      if (!video.current) return;
      video.current.srcObject = stream;
      await video.current.play();
      setStatus("on");
    } catch (e) {
      console.error("camera start failed", e);
      setStatus("error");
    }
  }, [facingMode, stop]);

  useEffect(() => stop, [stop]);
  return { video, status, start, stop };
}

function grabFrame(v: HTMLVideoElement, name: string): Promise<File | null> {
  const c = document.createElement("canvas");
  c.width = v.videoWidth;
  c.height = v.videoHeight;
  c.getContext("2d")!.drawImage(v, 0, 0); // un-mirrored, full resolution
  return new Promise((resolve) =>
    c.toBlob((b) => resolve(b ? new File([b], name, { type: "image/jpeg" }) : null), "image/jpeg", 0.95),
  );
}

function beep(freq = 880, ms = 120) {
  try {
    const ctx = new AudioContext();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    gain.gain.value = 0.08;
    osc.connect(gain).connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + ms / 1000);
    osc.onended = () => ctx.close();
  } catch {
    /* audio not available */
  }
}

/** Front camera with live face guidance and automatic capture. */
/** `frames`: landmarks (normalised x, y, z) from the steady frames just before capture, so the
 * server can take a per-point median and cut landmark jitter. */
export type LandmarkFrames = number[][][];
/** [time ms, eyeBlinkLeft, eyeBlinkRight] for the last few seconds - the server checks for one real blink. */
export type BlinkSamples = number[][];

const blinkScores = (r: { faceBlendshapes?: { categories: { categoryName: string; score: number }[] }[] }) => {
  const c = r.faceBlendshapes?.[0]?.categories ?? [];
  const get = (n: string) => c.find((x) => x.categoryName === n)?.score ?? 0;
  return [get("eyeBlinkLeft"), get("eyeBlinkRight")];
};

export function GuidedFrontCamera({ onCapture }: { onCapture: (f: File, frames?: LandmarkFrames, blinks?: BlinkSamples) => void }) {
  const { video, status, start, stop } = useCameraStream("user");
  const [guide, setGuide] = useState<GuideState | null>(null);
  const [modelError, setModelError] = useState(false);
  const [count, setCount] = useState<number | null>(null);
  const lightCanvas = useRef<HTMLCanvasElement | null>(null);
  const frames = useRef<LandmarkFrames>([]);
  const blinks = useRef<BlinkSamples>([]);
  const onCaptureRef = useRef(onCapture);
  useEffect(() => {
    onCaptureRef.current = onCapture;
  }, [onCapture]);

  const capture = useCallback(async () => {
    const v = video.current;
    if (!v) return;
    const file = await grabFrame(v, "front.jpg");
    beep(1320, 180);
    stop();
    if (file) onCaptureRef.current(file, frames.current.length >= 5 ? frames.current.slice() : undefined, blinks.current.slice());
  }, [stop, video]);

  // Detection loop
  useEffect(() => {
    if (status !== "on") return;
    let raf = 0;
    let cancelled = false;
    let lastTs = 0;
    let frame = 0;
    let lighting: Lighting | null = null;
    let readySince: number | null = null;
    let countdownStart: number | null = null;
    let lastCount: number | null = null;
    const centres: { x: number; y: number }[] = [];
    // Liveness: a printed photo or a still on a screen can't blink, so we wait for one blink.
    let closedSeen = false;
    let blinked = false;
    blinks.current = [];
    lightCanvas.current ??= document.createElement("canvas");

    loadFaceLandmarker()
      .then((landmarker) => {
        const loop = () => {
          if (cancelled) return;
          raf = requestAnimationFrame(loop);
          const v = video.current;
          const now = performance.now();
          if (!v || v.readyState < 2 || now - lastTs < 70) return;
          lastTs = now;
          const result = landmarker.detectForVideo(v, now);

          const box = result.faceLandmarks[0]
            ? (() => {
                const xs = result.faceLandmarks[0].map((p) => p.x);
                const ys = result.faceLandmarks[0].map((p) => p.y);
                return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
              })()
            : undefined;
          if (box && frame++ % 4 === 0) lighting = measureLighting(v, box, lightCanvas.current!);
          if (box) {
            centres.push({ x: box.x + box.w / 2, y: box.y + box.h / 2 });
            if (centres.length > 8) centres.shift();
          } else centres.length = 0;
          const steady =
            centres.length >= 6 &&
            Math.max(...centres.map((c) => Math.hypot(c.x - centres[0].x, c.y - centres[0].y))) < 0.02;

          let g = evaluate(result, lighting, steady, v.videoWidth / v.videoHeight, v.videoWidth, v.videoHeight);
          if (result.faceLandmarks[0]) {
            const [bl, br] = blinkScores(result);
            blinks.current.push([Math.round(now), Math.round(bl * 1000) / 1000, Math.round(br * 1000) / 1000]);
            if (blinks.current.length > 120) blinks.current.shift();
            if (Math.min(bl, br) > 0.5) closedSeen = true;
            else if (closedSeen && Math.max(bl, br) < 0.35) blinked = true;
          }
          if (g.ready && !blinked) g = { ...g, ready: false, message: "Now blink once — so we know it's really you" };
          setGuide(g);
          if (g.ready && result.faceLandmarks[0]) {
            const r4 = (n: number) => Math.round(n * 1e4) / 1e4;
            frames.current.push(result.faceLandmarks[0].map((p) => [r4(p.x), r4(p.y), r4(p.z)]));
            if (frames.current.length > 24) frames.current.shift();
          } else if (!g.ready) frames.current = [];

          // Auto-capture: stay ready briefly, then count down while still ready.
          if (g.ready) {
            readySince ??= now;
            if (countdownStart === null && now - readySince > READY_HOLD_MS) {
              countdownStart = now;
              beep();
            }
          } else {
            readySince = null;
            countdownStart = null;
            if (lastCount !== null) setCount(null);
            lastCount = null;
          }
          if (countdownStart !== null) {
            const left = COUNTDOWN_S - Math.floor((now - countdownStart) / 1000);
            if (left !== lastCount) {
              if (lastCount !== null && left > 0) beep();
              lastCount = left;
              setCount(left);
            }
            if (left <= 0) {
              cancelled = true;
              cancelAnimationFrame(raf);
              capture();
            }
          }
        };
        loop();
      })
      .catch(() => setModelError(true));

    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
    };
  }, [status, capture, video]);

  const ok = guide?.ready;
  return (
    <div className="relative flex h-full w-full items-center justify-center bg-foreground/5">
      <video ref={video} playsInline muted className={`h-full w-full scale-x-[-1] object-cover ${status === "on" ? "" : "hidden"}`} />

      {status === "on" && (
        <>
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 133" preserveAspectRatio="none">
            <defs>
              <mask id="oval-cut">
                <rect width="100" height="133" fill="white" />
                <ellipse cx="50" cy="62" rx="31" ry="42" fill="black" />
              </mask>
            </defs>
            <rect width="100" height="133" fill="rgba(0,0,0,0.35)" mask="url(#oval-cut)" />
            <ellipse cx="50" cy="62" rx="31" ry="42" fill="none" strokeWidth="0.8"
              stroke={ok ? "#5fd08a" : "white"} strokeDasharray={ok ? "0" : "2 2"} />
          </svg>

          <div className="absolute left-3 right-3 top-3 flex justify-center">
            <span className={`rounded-full px-4 py-1.5 text-center text-sm font-medium shadow ${ok ? "bg-good text-white" : "bg-white/95 text-foreground"}`}>
              {modelError ? "Guide unavailable — take the photo manually" : guide?.message ?? "Starting face guide…"}
            </span>
          </div>

          {count !== null && count > 0 && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="font-serif text-8xl text-white drop-shadow-lg">{count}</span>
            </div>
          )}

          {guide?.distanceCm !== undefined && (
            <span className="absolute right-3 top-14 rounded-full bg-black/50 px-2.5 py-1 text-[11px] text-white">
              ~{Math.round(guide.distanceCm)} cm away
            </span>
          )}
          <div className="absolute bottom-16 left-0 right-0 flex justify-center gap-1.5 px-2">
            {(Object.keys(CHECK_LABELS) as CheckKey[]).map((k) => (
              <span key={k} className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${guide?.checks[k] ? "bg-good text-white" : "bg-black/50 text-white/80"}`}>
                {guide?.checks[k] ? "✓ " : ""}{CHECK_LABELS[k]}
              </span>
            ))}
          </div>

          <button onClick={capture} className="absolute bottom-3 rounded-full bg-white px-5 py-2 text-sm font-medium shadow">
            Take photo now
          </button>
        </>
      )}

      {status !== "on" && (
        <div className="p-6 text-center">
          <button onClick={start} className="btn-secondary" disabled={status === "starting"}>
            {status === "starting" ? "Starting camera…" : "Use guided camera"}
          </button>
          <p className="mt-3 text-xs text-muted">We guide your pose and lighting, then take the photo automatically.</p>
          {status === "error" && <p className="mt-3 text-sm text-bad">Camera unavailable — upload a photo instead.</p>}
        </div>
      )}
    </div>
  );
}

/** Side-profile camera with a self-timer (you can't see the screen while side-on). */
export function SideTimerCamera({ onCapture, prompt = "Turn side-on now and hold still" }: { onCapture: (f: File) => void; prompt?: string }) {
  const [facing, setFacing] = useState<"user" | "environment">("user");
  const { video, status, start, stop } = useCameraStream(facing);
  const [count, setCount] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCaptureRef = useRef(onCapture);
  useEffect(() => {
    onCaptureRef.current = onCapture;
  }, [onCapture]);

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);
  useEffect(() => {
    if (status === "on") start(); // restart stream when switching cameras
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facing]);

  function startTimer() {
    let left = 5;
    setCount(left);
    beep();
    timer.current = setInterval(async () => {
      left -= 1;
      if (left > 0) {
        setCount(left);
        beep();
        return;
      }
      clearInterval(timer.current!);
      setCount(null);
      const v = video.current;
      if (!v) return;
      const file = await grabFrame(v, "side.jpg");
      beep(1320, 180);
      stop();
      if (file) onCaptureRef.current(file);
    }, 1000);
  }

  return (
    <div className="relative flex h-full w-full items-center justify-center bg-foreground/5">
      <video ref={video} playsInline muted
        className={`h-full w-full object-cover ${facing === "user" ? "scale-x-[-1]" : ""} ${status === "on" ? "" : "hidden"}`} />
      {status === "on" && (
        <>
          <svg className="pointer-events-none absolute inset-0 h-full w-full text-white/80" viewBox="0 0 120 160" preserveAspectRatio="xMidYMid meet" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="3 2">
            <path d="M70 20c-22 0-36 16-36 38 0 10 3 18 3 26 0 14 6 26 18 30v26h30v-30c6-2 10-8 10-14l6-2-6-10 2-6-6-4c2-30-6-54-21-54z" />
          </svg>
          <p className="absolute left-3 right-3 top-3 rounded-full bg-white/95 px-4 py-1.5 text-center text-sm font-medium shadow">
            {count ? prompt : "Prop up your phone, then start the timer"}
          </p>
          {count !== null && (
            <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
              <span className="font-serif text-8xl text-white drop-shadow-lg">{count}</span>
            </div>
          )}
          {count === null && (
            <div className="absolute bottom-3 flex gap-2">
              <button onClick={startTimer} className="rounded-full bg-white px-5 py-2 text-sm font-medium shadow">5-second timer</button>
              <button onClick={() => setFacing((f) => (f === "user" ? "environment" : "user"))}
                className="rounded-full bg-white/80 px-4 py-2 text-sm shadow">
                Switch camera
              </button>
            </div>
          )}
        </>
      )}
      {status !== "on" && (
        <div className="p-6 text-center">
          <button onClick={start} className="btn-secondary" disabled={status === "starting"}>
            {status === "starting" ? "Starting camera…" : "Use camera with timer"}
          </button>
          <p className="mt-3 text-xs text-muted">Prop your phone up, start the timer, then turn side-on. Beeps count you down.</p>
          {status === "error" && <p className="mt-3 text-sm text-bad">Camera unavailable — upload a photo instead.</p>}
        </div>
      )}
    </div>
  );
}
