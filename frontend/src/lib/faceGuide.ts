import type { FaceLandmarker, FaceLandmarkerResult } from "@mediapipe/tasks-vision";

// Landmark indices (MediaPipe face mesh). Coordinates are from the raw, un-mirrored frame.
const NOSE_TIP = 1;
const R_CHEEK = 234; // subject's right = image left
const L_CHEEK = 454;
const R_EYE_OUT = 33;
const L_EYE_OUT = 263;

export type CheckKey = "distance" | "straight" | "light" | "expression";

export type GuideState = {
  ready: boolean; // every check passes and the face is steady
  message: string;
  checks: Record<CheckKey, boolean>;
  faceBox?: { x: number; y: number; w: number; h: number }; // normalised, raw frame
  distanceCm?: number; // camera-to-face distance estimated from iris size
};

const IRIS_MM = 11.7;
const F35 = 26; // typical front camera, 35mm-equivalent focal length

/** Camera distance from the iris (MediaPipe iris edge points 469/471 and 474/476). */
export function distanceCm(lm: { x: number; y: number }[], videoW: number, videoH: number): number | undefined {
  if (lm.length < 478 || !videoW) return undefined;
  const iris = (Math.hypot((lm[469].x - lm[471].x) * videoW, (lm[469].y - lm[471].y) * videoH) +
    Math.hypot((lm[474].x - lm[476].x) * videoW, (lm[474].y - lm[476].y) * videoH)) / 2;
  const fPx = (F35 / 36) * Math.max(videoW, videoH);
  return iris > 0 ? (fPx * IRIS_MM) / iris / 10 : undefined;
}

export type Lighting = { mean: number; leftRight: number };

let landmarkerPromise: Promise<FaceLandmarker> | null = null;

/** MediaPipe prints its harmless "INFO: Created TensorFlow Lite XNNPACK delegate for CPU." line through console.error,
 * which the Next.js dev overlay shows as an error. Drop only that exact informational line; every real error still shows. */
let infoFilterInstalled = false;
function hideMediapipeInfoLine() {
  if (infoFilterInstalled || typeof console === "undefined") return;
  infoFilterInstalled = true;
  const orig = console.error.bind(console);
  console.error = (...args: unknown[]) => {
    if (typeof args[0] === "string" && args[0].startsWith("INFO: Created TensorFlow Lite XNNPACK delegate")) return;
    orig(...args);
  };
}

export function loadFaceLandmarker(): Promise<FaceLandmarker> {
  hideMediapipeInfoLine();
  landmarkerPromise ??= (async () => {
    const { FaceLandmarker, FilesetResolver } = await import("@mediapipe/tasks-vision");
    const fileset = await FilesetResolver.forVisionTasks("/mediapipe/wasm");
    const create = (delegate: "GPU" | "CPU") =>
      FaceLandmarker.createFromOptions(fileset, {
        baseOptions: { modelAssetPath: "/mediapipe/face_landmarker.task", delegate },
        runningMode: "VIDEO",
        numFaces: 2,
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: true,
      });
    try {
      return await create("GPU");
    } catch {
      return create("CPU"); // no WebGL (older phones, some browsers)
    }
  })().catch((e) => {
    landmarkerPromise = null;
    throw e;
  });
  return landmarkerPromise;
}

/** Pitch magnitude (degrees) from MediaPipe's 4x4 transformation matrix. */
function pitchDegrees(data: number[]): number {
  // Element (row, col) of a column-major 4x4 matrix is data[col * 4 + row].
  const r = (row: number, col: number) => data[col * 4 + row];
  return Math.abs((Math.atan2(r(2, 1), r(2, 2)) * 180) / Math.PI);
}

/** `aspect` = video width / height; face size is judged against the frame's shorter side. */
export function evaluate(result: FaceLandmarkerResult, lighting: Lighting | null, steady: boolean, aspect = 1, videoW = 0, videoH = 0): GuideState {
  const checks: Record<CheckKey, boolean> = { distance: false, straight: false, light: false, expression: false };
  const faces = result.faceLandmarks;
  if (!faces.length) return { ready: false, message: "Position your face inside the oval", checks };
  if (faces.length > 1) return { ready: false, message: "Make sure only you are in the frame", checks };

  const lm = faces[0];
  const xs = lm.map((p) => p.x);
  const ys = lm.map((p) => p.y);
  const box = { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs), h: Math.max(...ys) - Math.min(...ys) };
  const cx = box.x + box.w / 2;
  const cy = box.y + box.h / 2;

  // Distance and centring
  const width = Math.abs(lm[L_CHEEK].x - lm[R_CHEEK].x) * Math.max(1, aspect);
  // Close selfies (~30 cm) make the nose look up to 30% wider, so we enforce arm's length.
  const dist = distanceCm(lm, videoW, videoH);
  let message = "";
  if (width < 0.18) message = "Move a little closer";
  else if ((dist !== undefined && dist < 30) || width > 0.68) message = "Hold the phone a little further away";
  else if (cx < 0.3 || cx > 0.7 || cy < 0.25 || cy > 0.72) message = "Centre your face in the oval";
  else checks.distance = true;

  // Head pose. yaw > 0: nose points to the image's right, i.e. the user turned to their left.
  const span = lm[L_CHEEK].x - lm[R_CHEEK].x;
  const yaw = (lm[NOSE_TIP].x - (lm[R_CHEEK].x + lm[L_CHEEK].x) / 2) / span;
  const roll = (Math.atan2(lm[L_EYE_OUT].y - lm[R_EYE_OUT].y, lm[L_EYE_OUT].x - lm[R_EYE_OUT].x) * 180) / Math.PI;
  const matrix = result.facialTransformationMatrixes?.[0]?.data;
  const pitch = matrix ? pitchDegrees(matrix) : 0;
  let poseMsg = "";
  // Comfortable limits: the server corrects small turns (yaw) and tilts (roll) before measuring.
  if (yaw > 0.1) poseMsg = "Turn your head slightly to your right";
  else if (yaw < -0.1) poseMsg = "Turn your head slightly to your left";
  else if (Math.abs(roll) > 10) poseMsg = "Keep your head level — don't tilt it";
  else if (pitch > 16) poseMsg = "Raise the phone a little so it's at eye level";
  else checks.straight = true;

  // Lighting
  let lightMsg = "";
  if (!lighting) lightMsg = "";
  else if (lighting.mean < 70) lightMsg = "Too dark — face a window or a lamp";
  else if (lighting.mean > 215) lightMsg = "Too bright — avoid direct harsh light";
  else if (lighting.leftRight > 45) lightMsg = "Uneven light — face the light source directly";
  checks.light = !!lighting && !lightMsg;

  // Expression
  const b = Object.fromEntries((result.faceBlendshapes?.[0]?.categories ?? []).map((c) => [c.categoryName, c.score]));
  let exprMsg = "";
  if ((b.jawOpen ?? 0) > 0.25) exprMsg = "Relax and close your mouth";
  else if (Math.max(b.mouthSmileLeft ?? 0, b.mouthSmileRight ?? 0) > 0.45) exprMsg = "Neutral expression — no smile";
  else if (Math.max(b.eyeBlinkLeft ?? 0, b.eyeBlinkRight ?? 0) > 0.55) exprMsg = "Keep your eyes open";
  else checks.expression = true;

  message = message || poseMsg || lightMsg || exprMsg;
  const allOk = Object.values(checks).every(Boolean);
  if (allOk && !steady) message = "Hold still…";
  return { ready: allOk && steady, message: message || "Perfect — hold still", checks, faceBox: box, distanceCm: dist };
}

/** Mean brightness of the face region and the difference between its left and right halves. */
export function measureLighting(video: HTMLVideoElement, box: GuideState["faceBox"], canvas: HTMLCanvasElement): Lighting | null {
  if (!box || !video.videoWidth) return null;
  const size = 48;
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  if (!ctx) return null;
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  ctx.drawImage(video, box.x * vw, box.y * vh, box.w * vw, box.h * vh, 0, 0, size, size);
  const { data } = ctx.getImageData(0, 0, size, size);
  let total = 0, left = 0, right = 0;
  for (let i = 0; i < data.length; i += 4) {
    const luma = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    total += luma;
    if ((i / 4) % size < size / 2) left += luma;
    else right += luma;
  }
  const n = data.length / 4;
  return { mean: total / n, leftRight: Math.abs(left - right) / (n / 2) };
}
