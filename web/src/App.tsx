import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Flame, Wind, Layers, Volume2, Loader2, Info } from 'lucide-react';

// VayuSetu console — attribution-first.
//
// This shows what the data supports: what happened, why, and who should act.
// There is deliberately no predicted-hotspot layer; that claim was tested against
// interpolation and failed (see TODO.md). Everything drawn here is observed.

const API = (import.meta as any).env?.VITE_API_BASE ?? 'http://localhost:8080';
const TENANT = 'ncr';

// CPCB National AQI bands. Standardised — do not invent a palette for a
// public-health index people already recognise.
const BANDS: [number, string, string][] = [
  [30, 'Good', '#22c55e'],
  [60, 'Satisfactory', '#84cc16'],
  [90, 'Moderate', '#eab308'],
  [120, 'Poor', '#f97316'],
  [250, 'Very Poor', '#dc2626'],
  [Infinity, 'Severe', '#7f1d1d'],
];
const bandColor = (pm: number) => (BANDS.find(([t]) => pm <= t) ?? BANDS[5])[2];
const bandName = (pm: number) => (BANDS.find(([t]) => pm <= t) ?? BANDS[5])[1];

const LANGS: [string, string][] = [
  ['en', 'English'], ['hi', 'हिन्दी'], ['pa', 'ਪੰਜਾਬੀ'], ['bn', 'বাংলা'],
  ['mr', 'मराठी'], ['ta', 'தமிழ்'], ['te', 'తెలుగు'], ['gu', 'ગુજરાતી'],
];

interface Day {
  date: string; pm25: number | null; peak_pm25: number | null;
  upwind_fires: number; blh: number | null; aqi_band: string | null; n_stations: number;
}
interface Station { station_id: string; name: string; lat: number; lon: number; pm25: number; aqi_band: string; }
interface Fire { lat: number; lon: number; frp: number; acq_ts: string; }
interface MapData { stations: Station[]; fires: Fire[]; }
interface Brief {
  cause: string; cause_category: string; confidence: number;
  evidence_cited: string[]; narrative: string;
  recommended_actions: { actor: string; action: string; urgency: string }[];
  caveats: string[]; public_advisory: string; model: string; verified: boolean;
}
interface Episode { evidence: any; brief: Brief | null; brief_error?: string; cached: boolean; }

// The frozen hero episode: peak of the real Nov 2025 Delhi smog event.
const HERO_TS = '2025-11-11T20:00:00Z';

const fmtIST = (iso: string) => {
  const d = new Date(iso);
  return new Intl.DateTimeFormat('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
    timeZone: 'Asia/Kolkata', hour12: false,
  }).format(d) + ' IST';
};

export default function App() {
  const [days, setDays] = useState<Day[]>([]);
  const [ts, setTs] = useState(HERO_TS);
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [lang, setLang] = useState('en');
  const [advisory, setAdvisory] = useState<{ text: string; lang: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/api/v1/${TENANT}/timeline`)
      .then(r => r.json()).then(d => setDays(d.series ?? []))
      .catch(e => setErr(String(e)));
  }, []);

  useEffect(() => {
    setLoading(true); setErr(null); setAdvisory(null);
    Promise.all([
      fetch(`${API}/api/v1/${TENANT}/episode?ts=${encodeURIComponent(ts)}`).then(r => r.json()),
      fetch(`${API}/api/v1/${TENANT}/map?ts=${encodeURIComponent(ts)}`).then(r => r.json()),
    ]).then(([ep, mp]) => { setEpisode(ep); setMapData(mp); })
      .catch(e => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [ts]);

  const speak = async (code: string) => {
    setLang(code);
    if (code === 'en') {
      setAdvisory({ text: episode?.brief?.public_advisory ?? '', lang: 'en' });
      return;
    }
    const r = await fetch(`${API}/api/v1/${TENANT}/advisory?ts=${encodeURIComponent(ts)}&lang=${code}`);
    const d = await r.json();
    setAdvisory({ text: d.text, lang: d.lang });
  };

  const ev = episode?.evidence;
  const brief = episode?.brief;

  return (
    <div style={S.app}>
      <header style={S.header}>
        <div>
          <h1 style={S.h1}>VayuSetu</h1>
          <div style={S.sub}>Why the air is bad, and who can fix it — Delhi-NCR</div>
        </div>
        <div style={S.headerRight}>
          <span style={S.replayBadge}>
            REPLAY · {fmtIST(ts)}
          </span>
        </div>
      </header>

      {err && <div style={S.error}><AlertTriangle size={16} /> {err}</div>}

      <div style={S.main}>
        {/* ── Left: map ─────────────────────────────────────────────── */}
        <section style={S.panel}>
          <div style={S.panelHead}>
            <Layers size={15} /> Observed conditions
            {ev && <span style={S.dim}>{ev.n_stations_reporting} stations reporting</span>}
          </div>
          <SectorMap data={mapData} ev={ev} />
          {ev && (
            <div style={S.statRow}>
              <Stat label="City PM2.5" value={`${ev.city_pm25}`} unit="µg/m³"
                    color={bandColor(ev.city_pm25)} sub={ev.aqi_band} />
              <Stat label="Worst station" value={`${ev.worst_station.pm25}`} unit="µg/m³"
                    color={bandColor(ev.worst_station.pm25)} sub={ev.worst_station.name} />
              <Stat label="Boundary layer" value={`${ev.boundary_layer_m ?? '—'}`} unit="m"
                    color={(ev.boundary_layer_m ?? 999) < 200 ? '#dc2626' : '#64748b'}
                    sub={(ev.boundary_layer_m ?? 999) < 200 ? 'collapsed — traps emissions' : 'normal'} />
              <Stat label="Upwind fires" value={`${ev.upwind_fires.count}`} unit="48h"
                    color="#f97316"
                    sub={`of ${ev.upwind_fires.total_fires_within_radius} within ${ev.upwind_fires.radius_km}km`} />
            </div>
          )}
        </section>

        {/* ── Right: the brief ──────────────────────────────────────── */}
        <section style={S.panel}>
          <div style={S.panelHead}>
            <Info size={15} /> Attribution brief
            {brief && <span style={S.modelTag}>{brief.model}</span>}
          </div>

          {loading && <div style={S.loading}><Loader2 size={18} className="spin" /> Assembling evidence…</div>}

          {!loading && episode?.brief_error && (
            <div style={S.error}>Brief unavailable: {episode.brief_error}</div>
          )}

          {!loading && brief && (
            <div style={S.briefBody}>
              <div style={S.cause}>{brief.cause}</div>
              <div style={S.confRow}>
                <span style={S.catTag}>{brief.cause_category.replace(/_/g, ' ')}</span>
                <span style={S.dim}>confidence {(brief.confidence * 100).toFixed(0)}%</span>
                {brief.verified && <span style={S.verified}>✓ evidence-checked</span>}
              </div>

              <p style={S.narrative}>{brief.narrative}</p>

              <div style={S.label}>Cited measurements</div>
              <div style={S.chips}>
                {brief.evidence_cited.map(c => <span key={c} style={S.chip}>{c}</span>)}
              </div>

              <div style={S.label}>Recommended actions</div>
              {brief.recommended_actions.map((a, i) => (
                <div key={i} style={S.action}>
                  <span style={{ ...S.urgency, background: urgencyColor(a.urgency) }}>{a.urgency}</span>
                  <div>
                    <div style={S.actor}>{a.actor}</div>
                    <div style={S.actionText}>{a.action}</div>
                  </div>
                </div>
              ))}

              {brief.caveats.length > 0 && (
                <>
                  <div style={S.label}>Caveats</div>
                  <ul style={S.caveats}>{brief.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
                </>
              )}

              <div style={S.label}>Public advisory</div>
              <div style={S.langRow}>
                {LANGS.map(([code, name]) => (
                  <button key={code} onClick={() => speak(code)}
                          style={{ ...S.langBtn, ...(lang === code ? S.langBtnOn : {}) }}>
                    {name}
                  </button>
                ))}
              </div>
              <div style={S.advisory}>
                <Volume2 size={15} style={{ flexShrink: 0, marginTop: 2 }} />
                <span>{advisory?.text ?? brief.public_advisory}</span>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* ── Timeline ────────────────────────────────────────────────── */}
      <Timeline days={days} ts={ts} onPick={setTs} />

      <footer style={S.footer}>
        Real observations: CPCB/OpenAQ stations · NASA FIRMS fires · ERA5 meteorology ·
        MAIAC AOD via Google Earth Engine. Attribution by Gemini over measured evidence.
        Replay of the November 2025 Delhi episode.
      </footer>
    </div>
  );
}

const urgencyColor = (u: string) =>
  ({ immediate: '#7f1d1d', high: '#dc2626', medium: '#f97316', low: '#64748b' } as any)[u] ?? '#64748b';

/** Simple projected map. SVG rather than a tile layer: no key, no referrer
 *  restrictions, and it renders identically in a recorded demo. */
function SectorMap({ data, ev }: { data: MapData | null; ev: any }) {
  const W = 560, H = 380;
  const B = { latMin: 28.0, latMax: 30.4, lonMin: 75.2, lonMax: 78.2 };
  const px = (lon: number) => ((lon - B.lonMin) / (B.lonMax - B.lonMin)) * W;
  const py = (lat: number) => H - ((lat - B.latMin) / (B.latMax - B.latMin)) * H;

  if (!data) return <div style={{ ...S.mapBox, height: H }} />;

  // Wind comes from the evidence, not the map payload: it is the same bearing that
  // selected the upwind fires and that the brief cites. Drawing the cone from a
  // city-average bearing put a different number on screen than the one the analysis
  // used.
  const wind = ev.wind.from_bearing_deg;
  const ws = ev?.worst_station;

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={S.mapBox} role="img"
         aria-label="Stations, upwind fires and wind direction">
      <rect width={W} height={H} fill="#0b1220" />
      {[0.25, 0.5, 0.75].map(f => (
        <g key={f} stroke="#1e293b" strokeWidth={1}>
          <line x1={W * f} y1={0} x2={W * f} y2={H} />
          <line x1={0} y1={H * f} x2={W} y2={H * f} />
        </g>
      ))}

      {/* Fires: orange, sized by radiative power */}
      {data.fires.map((f, i) => (
        <circle key={i} cx={px(f.lon)} cy={py(f.lat)} r={Math.min(5, 1.5 + f.frp / 4)}
                fill="#f97316" opacity={0.55} />
      ))}

      {/* Upwind cone from the worst-affected station */}
      {ws && wind !== null && (
        <g transform={`translate(${px(ws.lon)} ${py(ws.lat)}) rotate(${wind})`} opacity={0.16}>
          <path d={`M 0 0 L ${-90 * Math.tan(Math.PI / 6)} -180 L ${90 * Math.tan(Math.PI / 6)} -180 Z`}
                fill="#38bdf8" />
        </g>
      )}

      {/* Stations, coloured by CPCB band */}
      {data.stations.map(s => (
        <circle key={s.station_id} cx={px(s.lon)} cy={py(s.lat)} r={4.5}
                fill={bandColor(s.pm25)} stroke="#0b1220" strokeWidth={1}>
          <title>{s.name}: {s.pm25} µg/m³ ({s.aqi_band})</title>
        </circle>
      ))}

      {/* Worst station highlighted */}
      {ws && (
        <g>
          <circle cx={px(ws.lon)} cy={py(ws.lat)} r={11} fill="none" stroke="#f87171" strokeWidth={2} />
          <text x={px(ws.lon) + 15} y={py(ws.lat) + 4} fill="#fca5a5" fontSize={11}>
            {ws.pm25} µg/m³
          </text>
        </g>
      )}

      {wind !== null && (
        <g transform={`translate(${W - 62} 40)`}>
          <circle r={24} fill="#0f172a" stroke="#334155" />
          <g transform={`rotate(${wind + 180})`}>
            <path d="M 0 14 L 0 -14 M -5 -8 L 0 -14 L 5 -8" stroke="#38bdf8" strokeWidth={2} fill="none" />
          </g>
          <text y={40} textAnchor="middle" fill="#64748b" fontSize={9}>
            from {wind.toFixed(0)}°
          </text>
        </g>
      )}
      <text x={10} y={H - 10} fill="#475569" fontSize={10}>
        Delhi-NCR + 200 km · {data.fires.length} fire detections (48h)
      </text>
    </svg>
  );
}

function Timeline({ days, ts, onPick }: { days: Day[]; ts: string; onPick: (t: string) => void }) {
  const max = useMemo(() => Math.max(...days.map(d => d.pm25 ?? 0), 1), [days]);
  const maxFire = useMemo(() => Math.max(...days.map(d => d.upwind_fires), 1), [days]);
  const active = ts.slice(0, 10);

  return (
    <div style={S.timeline}>
      <div style={S.panelHead}>
        <Flame size={15} /> Daily PM2.5 and its drivers
        <span style={S.dim}>fires r=+0.55 · boundary layer r=−0.42 · click a day</span>
      </div>
      <div style={S.bars}>
        {days.map(d => {
          const h = ((d.pm25 ?? 0) / max) * 100;
          const fh = (d.upwind_fires / maxFire) * 100;
          const on = d.date === active;
          return (
            <button key={d.date} onClick={() => onPick(`${d.date}T20:00:00Z`)}
                    title={`${d.date}  PM2.5 ${d.pm25}  fires ${d.upwind_fires}  BLH ${d.blh}m`}
                    style={{ ...S.barCol, ...(on ? S.barColOn : {}) }}>
              <div style={S.barWrap}>
                <div style={{ ...S.fireLine, height: `${fh}%` }} />
                <div style={{ height: `${h}%`, background: bandColor(d.pm25 ?? 0), ...S.bar }} />
              </div>
              <span style={S.barLabel}>{d.date.slice(8)}</span>
            </button>
          );
        })}
      </div>
      <div style={S.legend}>
        <span><i style={{ ...S.dot, background: '#dc2626' }} /> PM2.5 (CPCB band colour)</span>
        <span><i style={{ ...S.dot, background: '#f97316', opacity: 0.6 }} /> upwind fire count</span>
      </div>
    </div>
  );
}

function Stat({ label, value, unit, color, sub }: any) {
  return (
    <div style={S.stat}>
      <div style={S.statLabel}>{label}</div>
      <div style={{ ...S.statValue, color }}>{value}<span style={S.statUnit}>{unit}</span></div>
      <div style={S.statSub} title={sub}>{sub}</div>
    </div>
  );
}

const S: Record<string, React.CSSProperties> = {
  app: { minHeight: '100vh', background: '#020617', color: '#e2e8f0',
         fontFamily: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif' },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center',
            padding: '14px 22px', borderBottom: '1px solid #1e293b' },
  h1: { margin: 0, fontSize: 20, fontWeight: 650, letterSpacing: '-0.01em' },
  sub: { fontSize: 12, color: '#64748b', marginTop: 2 },
  headerRight: { display: 'flex', gap: 10, alignItems: 'center' },
  replayBadge: { fontSize: 11, letterSpacing: '0.06em', color: '#38bdf8',
                 border: '1px solid #0c4a6e', background: '#082f49',
                 padding: '5px 10px', borderRadius: 4 },
  main: { display: 'grid', gridTemplateColumns: 'minmax(0,1.05fr) minmax(0,1fr)',
          gap: 14, padding: 14 },
  panel: { background: '#0b1220', border: '1px solid #1e293b', borderRadius: 8, padding: 14 },
  panelHead: { display: 'flex', alignItems: 'center', gap: 7, fontSize: 12.5,
               fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase',
               letterSpacing: '0.05em', marginBottom: 12 },
  dim: { color: '#475569', fontWeight: 400, textTransform: 'none',
         letterSpacing: 0, marginLeft: 'auto', fontSize: 11 },
  modelTag: { marginLeft: 'auto', fontSize: 10, color: '#38bdf8', background: '#082f49',
              padding: '3px 7px', borderRadius: 3, textTransform: 'none', letterSpacing: 0 },
  mapBox: { width: '100%', borderRadius: 6, border: '1px solid #1e293b', display: 'block' },
  statRow: { display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 12 },
  stat: { background: '#0f172a', borderRadius: 6, padding: '9px 10px', minWidth: 0 },
  statLabel: { fontSize: 10, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em' },
  statValue: { fontSize: 21, fontWeight: 600, marginTop: 3, lineHeight: 1.1 },
  statUnit: { fontSize: 11, color: '#475569', marginLeft: 3, fontWeight: 400 },
  statSub: { fontSize: 10.5, color: '#64748b', marginTop: 3, whiteSpace: 'nowrap',
             overflow: 'hidden', textOverflow: 'ellipsis' },
  briefBody: { fontSize: 13.5 },
  cause: { fontSize: 16, fontWeight: 600, lineHeight: 1.35, color: '#f1f5f9' },
  confRow: { display: 'flex', gap: 9, alignItems: 'center', margin: '9px 0 14px' },
  catTag: { fontSize: 11, background: '#7c2d12', color: '#fdba74',
            padding: '3px 8px', borderRadius: 3, textTransform: 'capitalize' },
  verified: { fontSize: 11, color: '#4ade80' },
  narrative: { lineHeight: 1.6, color: '#cbd5e1', margin: '0 0 16px' },
  label: { fontSize: 10.5, color: '#64748b', textTransform: 'uppercase',
           letterSpacing: '0.06em', margin: '16px 0 7px' },
  chips: { display: 'flex', flexWrap: 'wrap', gap: 5 },
  chip: { fontSize: 10.5, fontFamily: 'ui-monospace, monospace', background: '#0f172a',
          border: '1px solid #1e293b', color: '#7dd3fc', padding: '3px 7px', borderRadius: 3 },
  action: { display: 'flex', gap: 9, marginBottom: 9, alignItems: 'flex-start' },
  urgency: { fontSize: 9.5, textTransform: 'uppercase', letterSpacing: '0.05em',
             color: '#fff', padding: '3px 6px', borderRadius: 3, flexShrink: 0, marginTop: 1 },
  actor: { fontWeight: 600, fontSize: 12.5, color: '#e2e8f0' },
  actionText: { fontSize: 12.5, color: '#94a3b8', lineHeight: 1.45 },
  caveats: { margin: 0, paddingLeft: 17, color: '#94a3b8', fontSize: 12, lineHeight: 1.5 },
  langRow: { display: 'flex', flexWrap: 'wrap', gap: 5, marginBottom: 9 },
  langBtn: { fontSize: 11.5, background: '#0f172a', border: '1px solid #1e293b',
             color: '#94a3b8', padding: '4px 9px', borderRadius: 4, cursor: 'pointer' },
  langBtnOn: { background: '#082f49', borderColor: '#0c4a6e', color: '#7dd3fc' },
  advisory: { display: 'flex', gap: 9, background: '#0f172a', border: '1px solid #1e293b',
              borderRadius: 6, padding: '11px 12px', lineHeight: 1.5, color: '#e2e8f0' },
  timeline: { margin: '0 14px 14px', background: '#0b1220',
              border: '1px solid #1e293b', borderRadius: 8, padding: 14 },
  bars: { display: 'flex', gap: 3, height: 110, alignItems: 'flex-end' },
  barCol: { flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center',
            background: 'none', border: 'none', cursor: 'pointer', padding: 0, minWidth: 0 },
  barColOn: { background: '#0f172a', borderRadius: 4, outline: '1px solid #0c4a6e' },
  barWrap: { position: 'relative', width: '100%', height: 90,
             display: 'flex', alignItems: 'flex-end', justifyContent: 'center' },
  bar: { width: '78%', borderRadius: '2px 2px 0 0' },
  fireLine: { position: 'absolute', bottom: 0, width: '30%', background: '#f97316',
              opacity: 0.55, borderRadius: '2px 2px 0 0' },
  barLabel: { fontSize: 9.5, color: '#475569', marginTop: 4 },
  legend: { display: 'flex', gap: 16, fontSize: 11, color: '#64748b', marginTop: 9 },
  dot: { display: 'inline-block', width: 8, height: 8, borderRadius: 2, marginRight: 5 },
  loading: { display: 'flex', gap: 9, alignItems: 'center', color: '#64748b',
             padding: '28px 0', fontSize: 13 },
  error: { display: 'flex', gap: 8, alignItems: 'center', background: '#450a0a',
           border: '1px solid #7f1d1d', color: '#fca5a5', padding: '9px 12px',
           borderRadius: 6, margin: '0 14px 10px', fontSize: 12.5 },
  footer: { padding: '14px 22px', borderTop: '1px solid #1e293b',
            fontSize: 11, color: '#475569', lineHeight: 1.6 },
};
