/**
 * Shared types, the CPCB scale, and the API client.
 *
 * The AQI scale lives here alone. It is a public-health standard people already
 * read, so it must be identical on the map, in the stat strip and on the
 * timeline: one definition, three consumers.
 */

export const API = (import.meta as any).env?.VITE_API_BASE ?? 'http://localhost:8080';
export const MAPS_KEY = (import.meta as any).env?.VITE_GOOGLE_MAPS_API_KEY ?? '';
export const TENANT = 'ncr';

/** The frozen hero episode: the peak of the real November 2025 Delhi smog event. */
export const HERO_TS = '2025-11-11T20:00:00Z';

/** CPCB National AQI bands for PM2.5, with the token each band paints with. */
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

export const LANGS: { code: string; label: string }[] = [
  { code: 'en', label: 'English' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'pa', label: 'ਪੰਜਾਬੀ' },
  { code: 'bn', label: 'বাংলা' },
  { code: 'mr', label: 'मराठी' },
  { code: 'ta', label: 'தமிழ்' },
  { code: 'te', label: 'తెలుగు' },
  { code: 'gu', label: 'ગુજરાતી' },
];

const get = async <T>(path: string): Promise<T> => {
  const r = await fetch(`${API}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} on ${path}`);
  return r.json();
};

export const fetchTimeline = () =>
  get<{ series: Day[] }>(`/api/v1/${TENANT}/timeline`).then(d => d.series ?? []);

export const fetchEpisode = (ts: string) =>
  get<Episode>(`/api/v1/${TENANT}/episode?ts=${encodeURIComponent(ts)}`);

export const fetchMap = (ts: string) =>
  get<MapData>(`/api/v1/${TENANT}/map?ts=${encodeURIComponent(ts)}`);

export const fetchAdvisory = (ts: string, lang: string) =>
  get<{ text: string; lang: string; translated: boolean }>(
    `/api/v1/${TENANT}/advisory?ts=${encodeURIComponent(ts)}&lang=${lang}`,
  );

/** IST is the only clock an Indian official reads. UTC never reaches the screen. */
export const fmtIST = (iso: string, withTime = true) =>
  new Intl.DateTimeFormat('en-IN', {
    day: '2-digit',
    month: 'short',
    ...(withTime ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
    timeZone: 'Asia/Kolkata',
  }).format(new Date(iso)) + (withTime ? ' IST' : '');

/** Compass point for a bearing, so "from 338" reads as a direction, not a number. */
export const compass = (deg: number) =>
  ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
   'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'][Math.round(deg / 22.5) % 16];
