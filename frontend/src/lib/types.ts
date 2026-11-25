export type Metric = {
  key: string;
  label: string;
  category: string;
  value: number;
  unit: string;
  ideal: number;
  tolerance: number;
  score: number;
  status: "ideal" | "near" | "outside";
  direction: "low" | "high" | "ok";
  description: string;
};

export type QualityIssue = { level: "error" | "warning"; code: string; message: string };

export type Quality = {
  ok: boolean;
  issues: QualityIssue[];
  pose: { yaw: number; pitch: number; roll: number };
  sharpness: number;
  brightness: number;
  fiqa?: number | null;
  colour_cast?: { b: number; g: number; r: number } | null;
};

export type Recommendation = { title: string; type: string; detail: string; cost: string; timeline: string };

export type Report = {
  headline: string;
  overview: string;
  strengths: string[];
  sections: { feature: string; based_on?: string[]; summary: string; observations: string[]; recommendations: Recommendation[] }[];
  priority_plan: string[];
  disclaimer: string;
};

export type Profile = {
  name: string;
  age: string;
  sex: string;
  ethnicity: string;
  goals: string[];
  budget: string;
  notes: string;
  skin_type: string;
  event?: { type: string; date: string };
  city?: string;
  hair?: HairAnswers;
  safety?: string[]; // pregnant | breastfeeding | isotretinoin | steroid_history | skin_condition | prescribed_skin_treatment
  sun?: "indoor" | "two_wheeler" | "outdoor";
  skin_signs?: string[]; // neck_dark (possible acanthosis nigricans)
};

export type HairAnswers = {
  fall?: "normal" | "more" | "lot" | "clumps";
  wash?: "under50" | "50to100" | "over100"; // hairs lost per wash (refined wash test)
  short_hairs?: boolean;
  flags?: string[];
  duration?: "weeks" | "months" | "long" | "years";
  pattern?: string[];
  triggers?: string[];
  family?: boolean;
  dandruff?: boolean;
  diet?: "veg" | "nonveg" | "vegan";
  periods?: boolean;
};

export type Analysis = {
  id: string;
  created_at: number;
  profile: Profile;
  metrics: Metric[];
  category_scores: Record<string, number>;
  harmony_score: number;
  quality: Quality;
  skin: {
    available: boolean;
    experimental?: boolean;
    score?: number;
    concerns?: { key: string; label: string; score: number; severity: "low" | "moderate" | "high"; detail: string }[];
    tone?: { ita: number | null; group: string; advice: string; spread: number };
    neck?: { available: boolean; finding?: "neck_darker" | "face_tan" | "even" | "reported"; detail?: string; reason?: string;
      see_doctor?: boolean; tests?: string[] };
    note?: string;
    image?: string;
  };
  report: Report;
  report_source: "claude" | "rules";
  annotated_image: string;
  paid: boolean;
  in_review?: boolean;
  review_status?: "pending" | "approved" | "not_required";
  reviewer_note?: string;
  three_quarter_image?: string;
  three_quarter_error?: string;
  plan?: "full" | "expert";
  price: {
    mode: "razorpay" | "stripe" | "dev";
    currency: string;
    plans: { id: "full" | "expert"; name: string; amount: number; features: string[] }[];
    razorpay_key_id: string | null;
  };
  locked?: {
    metrics: number; sections: number; plan_steps: number; feature_names: string[];
    previews?: number; routine?: boolean; remedies?: number; countdown_steps?: number; style?: number; hair?: number;
    mm_rows?: number; eyes?: number; diagrams?: number;
  };
  saved?: boolean;
  withheld_metrics?: string[];
  medical?: import("@/components/MedicalSection").Medical;
  preview_status?: { preview: string; offered: boolean; reason: string }[];
  goal_alignment?: { goal: string; status: "recommendations_available" | "general_recommendations_only" | "measurements_in_range" | "measurement_unavailable" | "partly_unavailable" | "no_specific_target"; supporting_metrics: string[] }[];
  validation?: {
    status: "complete" | "partial"; validator: string; measurement_version: string;
    suppressed: { item: string; label: string; reason: string }[];
    retake_tips?: string[];
    flagged: { item: string; reason: string }[];
    calibration: { status: "estimated" | "unavailable"; validated: boolean };
    reference_ranges?: { measurement_table_ranges: string; harmony_metric_references: string; eye_and_brow_thresholds: string };
  };
  anthropometry?: {
    rows: { key: string; label: string; group: string; value: number; unit: string; mean: number; range: [number, number];
      deviation_pct: number; status: "typical" | "above" | "below"; description: string }[];
    ratios: { key: string; label: string; value: number; unit: string; note: string }[];
    note: string;
    range_status?: string;
    calibration?: { method: string; reference_mm: number; mm_per_px: number; validated: boolean };
  };
  eyes?: {
    findings: string[]; advice: string[]; note: string; thresholds_status?: string; image?: string; eye_height_mm?: number; brow_height_mm?: number;
  };
  diagrams?: { measurements?: string; fifths?: string; thirds?: string; symmetry_right?: string; symmetry_left?: string };
  liveness?: { checked: boolean; passed: boolean; reason?: string | null };
  tryon?: {
    available: boolean; quota: number; used: number;
    consent?: { granted: boolean; provider: string | null; expires_at: number | null };
    disclosure?: {
      version: string; provider: string; provider_name: string; leaves_infrastructure: string; why: string;
      processing: string; retention: string; optional: string; duration: string;
    } | null;
  };
  tryons?: Record<string, TryOn>;
  routine_feedback?: { at: number; irritation: boolean; irritating: string[]; progress: string | null; consistency: string | null };
  style?: {
    shape: string; label: string; summary: string; confidence?: number; secondary?: string | null;
    hairstyles: string[]; avoid?: string[]; beard?: string[]; glasses?: string[]; notes?: string[];
  };
  hair?: {
    available: boolean;
    hairline?: {
      stage: number; label: string; score: number; height_ratio: number; temple_depth: number; detail: string;
      height_cm?: number; recession_cm?: number;
    } | null;
    hairline_note?: string; shedding_note?: string; hairline_limits?: string;
    analysis?: HairAnalysis;
    crown?: {
      scalp_pct: number; label: string; score: number; detail: string;
      parting?: { width_mm: number; widening: number; christmas_tree: boolean; label: string; score: number; detail: string } | null;
    } | null;
    score?: number | null;
    image?: string;
    top_image?: string;
    top_error?: string;
    see_doctor?: boolean;
    doctor_reasons?: string[];
    causes?: { key: string; title: string; why: string; actions: string[] }[];
    tests?: string[];
    plan?: string[];
    myths?: { name: string; verdict: "works" | "okay" | "myth" | "harmful"; why: string }[];
  };
  climate?: {
    city: string; zone_label: string; season: string; season_label: string; pollution: boolean;
    tips: string[]; upcoming: { season: string; label: string; tip: string } | null;
  } | null;
  routine?: {
    skin_type: string;
    tier: string;
    notes: string[];
    removals?: { status: string; stop_now: { item: string; why: string }[]; step_down: { item: string; when: string; why: string }[]; keep: string; note: string | null };
    disclaimer: string;
    am: RoutineStep[];
    pm: RoutineStep[];
  } | null;
  remedies?: { name: string; verdict: "works" | "okay" | "myth" | "harmful"; why: string }[];
  countdown?: {
    type: string; label: string; date: string; days_left: number;
    phases: { days_before: number; date: string; items: { title: string; detail: string }[] }[];
  } | null;
  previews?: { before: string; note: string; method?: string; items: { key: string; title: string; description: string; image: string }[] } | null;
  profile_image?: string;
  profile_notes?: string[];
  profile_error?: string;
};

export type TryOn = { image: string; identity: number; kind: "hair" | "beard" | "glasses"; style: string };

export type RoutineStep = {
  time: "AM" | "PM";
  step: string;
  kind?: string;
  why: string;
  how: string;
  products: { name: string; tier: string; price_band: string; swap: boolean; links: { nykaa: string; amazon: string } }[];
};

export type HairDensity = { status: string; score: number | null; scalp_visibility: number | null; confidence: number; text?: string; relative_to_front?: number };
export type HairTemple = { status: string; text: string; depth_normalized: number | null; angle_deg: number | null; density: HairDensity | null; confidence: number };
export type HairAnalysis = {
  engine: string; status: "complete" | "partial" | "inconclusive"; reason?: string; validation_status: string;
  hairline: {
    status: string; confidence: number; observation?: string; points: { u: number; v: number; confidence: number }[];
    shape: { label: string; text: string };
    symmetry: { score: number | null; left_right_difference: number | null; confidence: number; note?: string };
    ratios: { hairline_to_glabella_ratio: number; hairline_to_face_height_ratio: number; unit: string } | null;
  };
  temples: { left: HairTemple; right: HairTemple };
  frontal_density: HairDensity;
  crown: { status: "assessed" | "not_assessable" | "inconclusive"; reason?: string; scalp_visibility_pct?: number; confidence: number;
    density?: { score: number; text: string } | null; regional?: { central_scalp_pct: number; outer_scalp_pct: number } | null;
    parting?: { visible: boolean; relative_width_of_head?: number; widens_towards_one_end?: boolean; note?: string } };
  image_quality: { overall_score: number; confidence: number; hairline_visible: boolean; temples_visible: { left: boolean; right: boolean };
    crown_visible: boolean; flags: string[] };
  longitudinal: { status: string };
  capture: { front: boolean; top: boolean; angled_temples: string };
  guidance: string[]; limitations: string[]; image?: string;
};
