/**
 * Shared types, the CPCB scale, dates, and the API client.
 *
 * The AQI scale lives here alone. It is a public-health standard people already
 * read, so it must be identical on the map, in the summary, on the timeline and
 * in the resident view: one definition, every consumer.
 */

/**
 * Where the API is. A production build is served by the API itself (one Cloud Run
 * service), so it calls its own origin. The dev server runs separately on another
 * port, so development points at the local API. Keyed on the build mode rather than
 * on VITE_API_BASE because web/.env.local — which sets it to localhost for dev — is
 * also loaded by production builds, and a deployed site calling localhost fails for
 * every visitor while working on the machine that built it.
 */
const env = (import.meta as any).env ?? {};
export const API: string = env.PROD ? '' : (env.VITE_API_BASE ?? 'http://localhost:8080');
export const MAPS_KEY = (import.meta as any).env?.VITE_GOOGLE_MAPS_API_KEY ?? '';
export const TENANT = 'ncr';

/** The frozen hero episode: 01:30 IST on 12 Nov 2025, the peak of a real Delhi smog event. */
export const HERO_TS = '2025-11-11T20:00:00Z';

/** CPCB National AQI bands for PM2.5. */
export const BANDS: { max: number; name: string; color: string }[] = [
  { max: 30,       name: 'Good',         color: '#22c55e' },
  { max: 60,       name: 'Satisfactory', color: '#84cc16' },
  { max: 90,       name: 'Moderate',     color: '#eab308' },
  { max: 120,      name: 'Poor',         color: '#f97316' },
  { max: 250,      name: 'Very Poor',    color: '#dc2626' },
  { max: Infinity, name: 'Severe',       color: '#991b1b' },
];

export const band = (pm: number) => BANDS.find(b => pm <= b.max) ?? BANDS[5];
export const bandColor = (pm: number) => band(pm).color;

export interface Day {
  date: string;
  pm25: number | null;
  peak_pm25: number | null;
  upwind_fires: number;
  blh: number | null;
  aqi_band: string | null;
  n_stations: number;
}

export interface Station {
  station_id: string;
  name: string;
  lat: number;
  lon: number;
  pm25: number;
  aqi_band: string;
}

export interface Fire {
  lat: number;
  lon: number;
  frp: number;
  acq_ts: string;
  confidence?: string;
}

export interface MapData {
  stations: Station[];
  fires: Fire[];
}

export interface Action {
  actor: string;
  action: string;
  urgency: 'low' | 'medium' | 'high' | 'immediate';
}

export interface Brief {
  cause: string;
  cause_category: string;
  confidence: number;
  evidence_cited: string[];
  narrative: string;
  recommended_actions: Action[];
  caveats: string[];
  public_advisory: string;
  model: string;
  verified: boolean;
}

export interface Evidence {
  tenant: string;
  ts: string;
  city_pm25: number;
  aqi_band: string;
  n_stations_reporting: number;
  worst_station: { name: string; pm25: number; aqi_band: string; lat: number; lon: number };
  wind: { from_bearing_deg: number | null; speed_ms: number | null };
  boundary_layer_m: number | null;
  upwind_fires: {
    sector_deg: number;
    radius_km: number;
    window_h: number;
    count: number;
    total_frp_mw: number;
    nearest_km: number | null;
    farthest_km: number | null;
    transport_time_h: number | null;
    total_fires_within_radius: number;
  };
  comparison: { baseline_14d_mean_pm25: number | null; ratio_to_baseline: number | null };
  population_exposed: number | null;
  missing_fields: string[];
}

export interface Episode {
  evidence: Evidence;
  brief: Brief | null;
  brief_error?: string;
  cached: boolean;
}

/**
 * One monitor measured against the monitors around it.
 *
 * `is_hotspot` is the API's own judgement, not the website's: the rule lives in
 * `api/hotspots.py` and the numbers it judged on travel with the row, so the page
 * shows the evidence rather than re-deciding.
 */
export interface Hotspot {
  station_id: string;
  name: string;
  lat: number;
  lon: number;
  pm25: number;
  excess_over_median: number;
  times_regional: number | null;
  robust_z: number | null;
  population_in_cell: number | null;
  is_hotspot: boolean;
  /** The reading passed the integrity gate (api/integrity.py). */
  trusted?: boolean;
  integrity_flags?: string[];
  /** Consecutive trusted outlier hours; an event is confirmed at 2 or more. */
  persistent_hours?: number;
  confirmed?: boolean;
  /** Only on /hotspots/top, where each row is a different hour. */
  ts?: string;
  regional_median?: number;
  n_reporting?: number;
}

export type MonitorStatus = 'faulty' | 'offline' | 'suspect' | 'healthy';

/** One monitor's trustworthiness over a window, with raw readings as evidence. */
export interface MonitorHealth {
  station_id: string;
  name: string;
  lat: number;
  lon: number;
  status: MonitorStatus;
  uptime: number;
  fault_rate: number;
  hours_expected: number;
  hours_reported: number;
  dark_during_severe_hours: number;
  severe_hours: number;
  flag_counts: { stuck: number; dead_zero: number; spike: number; low_in_episode: number };
  example: {
    at: string;
    flags: string[];
    /** The monitor's readings from 3 hours before to 3 hours after `at`. */
    readings: (number | null)[];
    regional_median: (number | null)[];
  } | null;
}

export interface NetworkHealth {
  window: [string, string];
  method: string;
  summary: Record<MonitorStatus, number>;
  monitors: MonitorHealth[];
}

export interface HotspotHour {
  ts: string;
  regional_median: number | null;
  spread_mad: number | null;
  n_reporting: number;
  method: string;
  hotspots: Hotspot[];
  /** Outliers the integrity gate refused: the reading looks extreme but the monitor is misbehaving. */
  excluded_as_sensor_fault: Hotspot[];
  field: Hotspot[];
}

export type CaseKind = 'local_event' | 'monitor_fault' | 'regional_episode';
export type CaseStatus = 'open' | 'in_progress' | 'closed_verified' | 'closed_unverified';

/** One stretch of what the measurements showed after the event, used to verify closure. */
export interface OutcomeHour {
  at: string;
  value?: number | null;
  regional_median?: number | null;
  trusted?: boolean;
  elevated?: boolean;
  faults?: string[];
}

export interface ClosureResult {
  result: 'closed_verified' | 'closed_unverified' | 'rejected';
  reasons: string[];
  outcome: 'resolved' | 'persisting' | 'unknown';
  outcome_summary: string;
  outcome_hours: OutcomeHour[];
  outcome_basis: string;
  photo: {
    is_genuine_site_photo: boolean;
    rejection_reason: string | null;
    active_sources_visible: string[];
    remediation_visible: string[];
    shows_monitoring_equipment: boolean;
    notes: string;
  } | null;
  upload_distance_km: number | null;
  location_source: 'device' | 'demo_case_location';
}

/**
 * Work for a named agency, with a deadline, that closes only when a photo and the
 * measurements both check out (api/cases.py). Agencies are demo accounts (R6).
 */
export interface Case {
  case_id: string;
  kind: CaseKind;
  status: CaseStatus;
  severity: string;
  title: string;
  detail: string;
  station_id: string | null;
  location_name: string;
  lat: number | null;
  lon: number | null;
  event_hour: string;
  owner: string;
  copied: string[];
  escalates_to: string;
  opened_at: string;
  due_at: string;
  closure: ClosureResult | null;
  closed_at: string | null;
  events: { at: string; actor: string | null; action: string; note: string }[];
  closed: boolean;
  overdue: boolean;
  hours_left: number;
  escalated: boolean;
}

export interface CaseQueue {
  summary: { open: number; overdue: number; closed_verified: number; closed_unverified: number; closure_rejections: number };
  actors: Record<string, string>;
  cases: Case[];
}

export interface CasePreview {
  ts: string;
  candidates: { kind: CaseKind; severity: string; title: string; owner: string }[];
  no_trigger_reason: string | null;
}

/** The resident page's words, already translated by /residents. */
export interface Residents {
  lang: string;
  translated: boolean;
  ui: Record<string, string>;
  health: Record<string, string>;
  tips: Record<string, string[]>;
  why: string[];
  advisory: string | null;
  reading: { city_pm25: number; aqi_band: string; n_stations: number; ts: string };
}

export interface PhotoAnalysis {
  is_valid_outdoor_photo: boolean;
  rejection_reason: string | null;
  estimated_visibility_km: number | null;
  haze_severity: number | null;
  visible_sources: string[];
  sky_condition: string | null;
  confidence: number;
  notes: string;
}

export interface ReportResult {
  is_valid: boolean;
  rejection_reason?: string | null;
  gemini_analysis?: PhotoAnalysis | null;
}

/** The ten languages the API translates and speaks, each written in its own script. */
export const LANGS: { code: string; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'bn', label: 'বাংলা' },
  { code: 'mr', label: 'मराठी' },
  { code: 'te', label: 'తెలుగు' },
  { code: 'ta', label: 'தமிழ்' },
  { code: 'gu', label: 'ગુજરાતી' },
  { code: 'kn', label: 'ಕನ್ನಡ' },
  { code: 'ml', label: 'മലയാളം' },
  { code: 'pa', label: 'ਪੰਜਾਬੀ' },
];

const get = async <T>(path: string): Promise<T> => {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return r.json();
};

const q = (ts: string) => `ts=${encodeURIComponent(ts)}`;

export const fetchTimeline = () =>
  get<{ series: Day[] }>(`/api/v1/${TENANT}/timeline`).then(d => d.series ?? []);

export const fetchEpisode = (ts: string) => get<Episode>(`/api/v1/${TENANT}/episode?${q(ts)}`);

export const fetchMap = (ts: string) => get<MapData>(`/api/v1/${TENANT}/map?${q(ts)}`);

export const fetchHotspots = (ts: string) =>
  get<HotspotHour>(`/api/v1/${TENANT}/hotspots?${q(ts)}`);

export const fetchTopEvents = (limit = 8) =>
  get<{ method: string; events: Hotspot[]; trusted_events: number; excluded_as_sensor_fault: number }>(
    `/api/v1/${TENANT}/hotspots/top?limit=${limit}`,
  );

/** Monitor health over the `days` before the selected hour. */
export const fetchMonitorHealth = (ts: string, days = 7) =>
  get<NetworkHealth>(`/api/v1/${TENANT}/monitors/health?${q(ts)}&days=${days}`);

export const fetchCases = () => get<CaseQueue>(`/api/v1/${TENANT}/cases`);

export const previewCases = (ts: string) => get<CasePreview>(`/api/v1/${TENANT}/cases/preview?${q(ts)}`);

const post = async <T>(path: string, body?: FormData): Promise<T> => {
  const r = await fetch(`${API}${path}`, { method: 'POST', body });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not JSON */ }
    throw new Error(`${r.status}: ${detail}`);
  }
  return r.json();
};

/** Opening cases is a deliberate POST, never something a page load can do. */
export const raiseCases = (ts: string) => post<{ opened: number }>(`/api/v1/${TENANT}/cases/raise?${q(ts)}`);

export const acknowledgeCase = (id: string, actor: string, note = '') =>
  post<{ status: string }>(`/api/v1/${TENANT}/cases/${id}/acknowledge?actor=${encodeURIComponent(actor)}&note=${encodeURIComponent(note)}`);

/** A refused closure is a normal 200 with result 'rejected' and the reasons. */
export const closeCase = (id: string, form: FormData) =>
  post<ClosureResult & { status: string }>(`/api/v1/${TENANT}/cases/${id}/close`, form);

export const fetchAdvisory = (ts: string, lang: string, audio = false) =>
  get<{ text: string; lang: string; translated: boolean; audio_base64?: string | null }>(
    `/api/v1/${TENANT}/advisory?${q(ts)}&lang=${lang}${audio ? '&audio=true' : ''}`,
  );

export const fetchResidents = (ts: string, lang: string) =>
  get<Residents>(`/api/v1/${TENANT}/residents?${q(ts)}&lang=${lang}`);

/** Photo report. Returns the status too: a 503 means "try again", not "bad photo". */
export async function postReport(form: FormData): Promise<{ status: number; body: ReportResult | null }> {
  const r = await fetch(`${API}/api/v1/${TENANT}/reports`, { method: 'POST', body: form });
  let body: ReportResult | null = null;
  try { body = await r.json(); } catch { /* non-JSON error page */ }
  return { status: r.status, body };
}

/** "12 November 2025 at 1:30 am", in India time and the reader's language. */
export const fmtLong = (iso: string, lang = 'en') =>
  new Intl.DateTimeFormat(`${lang}-IN`, {
    dateStyle: 'long', timeStyle: 'short', timeZone: 'Asia/Kolkata',
  }).format(new Date(iso));

/** The calendar date in India for a timestamp, as YYYY-MM-DD. */
export const istDate = (iso: string) =>
  new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date(iso));

/**
 * 01:30 India time on a given Indian date, as a UTC hour. Night hours are when a
 * collapsed air ceiling traps smoke, so a picked day is shown at 01:30; that is
 * 20:00 UTC on the previous date.
 */
export const tsForIstDay = (isoDate: string) => {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return `${d.toISOString().slice(0, 10)}T20:00:00Z`;
};

/** Short compass point for a bearing, used where space is tight. */
export const compass = (deg: number) =>
  ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][Math.round(deg / 22.5) % 16];
