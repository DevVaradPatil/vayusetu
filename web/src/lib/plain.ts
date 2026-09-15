/**
 * Plain-language wording for the officials console.
 *
 * Someone who has never heard of a boundary layer should still be able to read
 * this page. Technical names stay available (tooltips, the data itself) but are
 * never the first thing a reader meets.
 */

import { compass, type Evidence } from './data';

export const CAUSE_LABEL: Record<string, string> = {
  crop_residue_burning: 'Crop stubble burning',
  waste_burning: 'Waste burning',
  construction_dust: 'Construction dust',
  industrial_plume: 'Factory smoke',
  vehicular_smoke: 'Vehicle exhaust',
  dust_storm: 'Dust storm',
  secondary_formation: 'Pollution forming in the air',
  meteorological_trapping: 'Weather trapping pollution',
  unknown: 'Not clear yet',
};

/** "north-northwest" for 338: a direction a reader can picture, not a number. */
export const compassWords = (deg: number) =>
  ['north', 'north-northeast', 'northeast', 'east-northeast', 'east', 'east-southeast',
   'southeast', 'south-southeast', 'south', 'south-southwest', 'southwest', 'west-southwest',
   'west', 'west-northwest', 'northwest', 'north-northwest'][Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];

export const confidenceWord =(c: number) => (c >= 0.75 ? 'High' : c >= 0.5 ? 'Medium' : 'Low');

/** Short explanations shown behind the (i) buttons. */
export const EXPLAIN = {
  pm25:
    'PM2.5 is fine dust and smoke, about 30 times thinner than a hair, small enough to reach deep ' +
    'into the lungs and blood. It is measured in micrograms per cubic metre. India’s ' +
    '24-hour safe limit is 60.',
  levels:
    'India’s official air quality scale from the Central Pollution Control Board. It runs ' +
    'from Good to Severe, and each level says who is at risk.',
  ceiling:
    'Pollution mixes into the layer of air nearest the ground. On cold, still nights this layer ' +
    'can sink below 200 metres, squeezing the same smoke into far less air. Readings shoot up ' +
    'without any new pollution.',
  fires:
    'Fires spotted by NASA satellites in the last 48 hours, up to 100 km away and inside the ' +
    'blue wind fan. Smoke from these could have reached the worst-affected monitor.',
  fan:
    'The blue fan points where the wind is coming from, 30 degrees either side. It is a simple ' +
    'direction check, not a full smoke-path model.',
  confidence: 'How strongly the measurements support this explanation.',
  checked:
    'Before this explanation was shown, every measurement it mentions was matched against the ' +
    'real data. An explanation that cited anything we did not measure would have been blocked.',
  replay:
    'A real smog episode from November 2025, replayed with the actual data. Delhi’s live ' +
    'monitor feed is patchy right now, so a complete past event shows the system best.',
  integrity:
    'Each hourly reading is checked for four patterns real air does not produce: the exact ' +
    'same value for 3 or more hours, zero while the region is polluted, a jump of hundreds ' +
    'that reverses within an hour, and a reading far cleaner than every neighbour during ' +
    'severe smog. The first three mean the instrument is faulty, and its readings are left ' +
    'out. The last is only a reason to inspect the site — a monitor can genuinely sit in a ' +
    'cleaner pocket. Thresholds were set from 35,602 real readings, not guessed.',
  fireLedger:
    'Two NASA satellite products, per district, 1 October to 30 November. Fire alerts are ' +
    'VIIRS detections, taken around 1:30 PM, the kind of count official fire tallies use. ' +
    'Land burned is MODIS burn scars, 500 m pixels, which stay visible whatever time the ' +
    'field burned. Each district is compared with its own 2020–21 seasons, so the numbers ' +
    'are a change against itself, not exact hectares. The alerts column shows how many ' +
    'alerts that much burning would have raised back then. Districts with too few fires to ' +
    'compare show a dash.',
  cases:
    'A case is raised only from trusted measurements: a confirmed local event, a broken or dark ' +
    'monitor, or the whole region in the Severe band. Each goes to the agency responsible, read ' +
    'from the monitor itself, with a deadline, and escalates to CAQM when overdue. To close it, ' +
    'the agency uploads a site photo; Gemini checks it is a real photo with no source still ' +
    'visible, and the readings afterwards must show the problem gone. If the numbers still show ' +
    'it, the closure is refused, however good the photo. Every agency here is a demo account.',
  hotspot:
    'One monitor reading far above the monitors around it in the same hour — a local source ' +
    'such as burning waste or a stalled traffic corridor, rather than a bad day everywhere. ' +
    'It is measured, never predicted: we compare each monitor with the middle reading of all ' +
    'the others, and flag it only if it is well clear of them and high enough to matter.',
};

const at = (obj: unknown, path: string): unknown =>
  path.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as any)[k] : undefined), obj);

const num = (v: unknown, digits = 0) => (typeof v === 'number' ? v.toFixed(digits) : String(v ?? '-'));

/**
 * A cited evidence path, as a person would say it. The raw path stays available
 * as a tooltip for anyone checking the brief against the API.
 */
export function citation(path: string, ev: Evidence | null): { label: string; value: string } {
  const root = path.split('=')[0].trim();
  const v = ev ? at(ev, root) : undefined;
  switch (root) {
    case 'city_pm25': return { label: 'City PM2.5', value: `${num(v, 1)} µg/m³` };
    case 'aqi_band': return { label: 'Air quality level', value: String(v ?? '-') };
    case 'n_stations_reporting': return { label: 'Monitors reporting', value: num(v) };
    case 'worst_station.pm25': return { label: 'Worst monitor', value: `${num(v)} µg/m³` };
    case 'worst_station.name': return { label: 'Worst monitor', value: String(v ?? '-') };
    case 'boundary_layer_m': return { label: 'Air ceiling', value: `${num(v)} m` };
    case 'upwind_fires.count': return { label: 'Fires upwind', value: num(v) };
    case 'upwind_fires.total_fires_within_radius': return { label: 'Fires within 100 km', value: num(v) };
    case 'upwind_fires.nearest_km': return { label: 'Nearest upwind fire', value: `${num(v, 1)} km` };
    case 'upwind_fires.farthest_km': return { label: 'Farthest upwind fire', value: `${num(v, 1)} km` };
    case 'upwind_fires.total_frp_mw': return { label: 'Fire heat output', value: `${num(v)} MW` };
    case 'upwind_fires.transport_time_h': return { label: 'Smoke travel time', value: `${num(v, 1)} h` };
    case 'wind.from_bearing_deg':
      return { label: 'Wind from', value: typeof v === 'number' ? `${compass(v)} (${v.toFixed(0)}°)` : '-' };
    case 'wind.speed_ms':
      return { label: 'Wind speed', value: typeof v === 'number' ? `${(v * 3.6).toFixed(0)} km/h` : '-' };
    case 'comparison.ratio_to_baseline': return { label: 'Compared with normal', value: `${num(v, 1)}×` };
    case 'comparison.baseline_14d_mean_pm25': return { label: 'Two-week average', value: `${num(v)} µg/m³` };
    case 'population_exposed': return { label: 'People nearby', value: num(v) };
    default: return { label: root, value: v === undefined ? '' : String(v) };
  }
}

/** Readable text colour on a band-coloured fill: dark on yellow and green, white on red. */
export function inkOn(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(c => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.35 ? '#1b1b1f' : '#ffffff';
}

export const bandKey = (name: string) => `band_${name.toLowerCase().replace(/ /g, '_')}`;
