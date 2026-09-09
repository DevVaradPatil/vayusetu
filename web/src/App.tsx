import { useEffect, useState } from 'react';
import {
  Wind, MapPin, ClockCounterClockwise, Warning, Broadcast, Fire, Compass,
} from '@phosphor-icons/react';
import MapView, { type Layers } from './components/MapView';
import BriefPanel from './components/BriefPanel';
import Timeline from './components/Timeline';
import {
  band, compass, fetchEpisode, fetchMap, fetchTimeline, fmtIST, HERO_TS,
  type Day, type Episode, type MapData,
} from './lib/data';

/**
 * VayuSetu console.
 *
 * Shows what the data supports: what happened, why, and who should act. There is
 * deliberately no predicted-hotspot layer and no forecast. Both were tested against
 * simple baselines and lost (see TODO.md), so everything on this screen is observed
 * or is reasoning over something observed.
 */

export default function App() {
  const [days, setDays] = useState<Day[]>([]);
  const [ts, setTs] = useState(HERO_TS);
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [layers, setLayers] = useState<Layers>({ stations: true, fires: true, sector: true });

  useEffect(() => {
    fetchTimeline()
      .then(setDays)
      .catch(e => setErr(String(e)))
      .finally(() => setTimelineLoading(false));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    Promise.all([fetchEpisode(ts), fetchMap(ts)])
      .then(([ep, mp]) => {
        if (cancelled) return;
        setEpisode(ep);
        setMapData(mp);
      })
      .catch(e => !cancelled && setErr(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, [ts]);

  const ev = episode?.evidence ?? null;
  const toggle = (k: keyof Layers) => setLayers(l => ({ ...l, [k]: !l[k] }));

  return (
    <div style={shell}>
      <header className="app-bar" style={appBar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
          <Wind size={26} weight="fill" color="var(--primary)" />
          <div>
            <div style={wordmark}>VayuSetu</div>
            <div style={tagline}>Why the air is bad, and who can fix it</div>
          </div>
        </div>

        <div className="bar-meta" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={tenantChip}>
            <MapPin size={15} /> Delhi NCR
          </span>
          <span style={replayChip} title="Historical replay of a real episode, not live data">
            <ClockCounterClockwise size={15} />
            Replay <span className="num">{fmtIST(ts)}</span>
          </span>
        </div>
      </header>

      {err && (
        <div style={errorBar} role="alert">
          <Warning size={18} />
          <span>{err}</span>
          <button style={retryBtn} onClick={() => setTs(t => `${t}`)}>Retry</button>
        </div>
      )}

      <main className="app-grid">
        <section className="map-panel" style={{ ...panel, position: 'relative', overflow: 'hidden', minHeight: 420 }}>
          <MapView data={mapData} ev={ev} layers={layers} />

          <div className="map-controls" style={mapControls}>
            {([
              ['stations', Broadcast, 'Stations'],
              ['fires', Fire, 'Fires'],
              ['sector', Compass, 'Upwind sector'],
            ] as [keyof Layers, typeof Wind, string][]).map(([key, Icon, text]) => (
              <button
                key={key}
                onClick={() => toggle(key)}
                aria-pressed={layers[key]}
                style={{ ...layerBtn, ...(layers[key] ? layerBtnOn : {}) }}
              >
                <Icon size={16} weight={layers[key] ? 'fill' : 'regular'} />
                {text}
              </button>
            ))}
          </div>

          <div className="map-legend" style={legend}>
            {band(0) && [30, 60, 90, 120, 250, 400].map(v => (
              <span key={v} style={legendItem}>
                <i style={{ ...swatch, background: band(v).color }} />
                {band(v).name}
              </span>
            ))}
            <span style={{ ...legendItem, marginLeft: 4 }}>
              <i style={{ ...swatch, background: 'var(--fire)' }} />Fire
            </span>
          </div>

          {loading && <div style={mapLoading}><span style={spinner} />Loading episode</div>}
        </section>

        <section className="brief-panel" style={{ ...panel, padding: 20, overflowY: 'auto' }}>
          <StatStrip ev={ev} loading={loading} />
          <div style={{ height: 1, background: 'var(--outline-variant)', margin: '18px 0' }} />
          <BriefPanel
            brief={episode?.brief ?? null}
            briefError={episode?.brief_error}
            ev={ev}
            ts={ts}
            loading={loading}
          />
        </section>
      </main>

      <section style={{ ...panel, padding: '16px 20px 10px' }}>
        <div style={sectionHead}>
          <div>
            <h2 style={sectionTitle}>Daily PM2.5 and its drivers</h2>
            <p style={sectionSub}>
              Fire count correlates <span className="num">+0.55</span> with PM2.5 and boundary
              layer height <span className="num">-0.42</span>. Select a day to re-run the analysis.
            </p>
          </div>
        </div>
        <Timeline days={days} selected={ts} onSelect={setTs} loading={timelineLoading} />
      </section>

      <footer style={pageFooter}>
        CPCB stations via OpenAQ, NASA FIRMS fire detections, ERA5 meteorology, and MAIAC
        aerosol depth via Google Earth Engine. Attribution by Gemini over measured evidence.
      </footer>
    </div>
  );
}

function StatStrip({ ev, loading }: { ev: any; loading: boolean }) {
  if (loading || !ev) {
    return (
      <div style={statGrid}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} className="skeleton" style={{ height: 74, borderRadius: 'var(--r-small)' }} />
        ))}
      </div>
    );
  }

  const collapsed = (ev.boundary_layer_m ?? 999) < 200;
  const wind = ev.wind.from_bearing_deg;

  return (
    <div style={statGrid} className="fade">
      <Stat
        label="City PM2.5"
        value={ev.city_pm25.toFixed(1)}
        unit="ug/m3"
        color={band(ev.city_pm25).color}
        sub={`${ev.aqi_band} · ${ev.n_stations_reporting} stations`}
      />
      <Stat
        label="Worst station"
        value={ev.worst_station.pm25.toFixed(0)}
        unit="ug/m3"
        color={band(ev.worst_station.pm25).color}
        sub={ev.worst_station.name}
      />
      <Stat
        label="Boundary layer"
        value={ev.boundary_layer_m?.toFixed(0) ?? '-'}
        unit="m"
        color={collapsed ? 'var(--aqi-verypoor)' : 'var(--on-surface)'}
        sub={collapsed ? 'Collapsed, traps emissions' : 'Normal mixing depth'}
      />
      <Stat
        label="Upwind fires"
        value={String(ev.upwind_fires.count)}
        unit={`of ${ev.upwind_fires.total_fires_within_radius}`}
        color="var(--fire)"
        sub={wind != null
          ? `Wind from ${compass(wind)} ${wind.toFixed(0)} deg`
          : `Within ${ev.upwind_fires.radius_km} km`}
      />
    </div>
  );
}

function Stat({ label, value, unit, color, sub }: {
  label: string; value: string; unit: string; color: string; sub: string;
}) {
  return (
    <div style={statCard}>
      <div style={statLabel}>{label}</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4 }}>
        <span className="num" style={{ fontSize: 25, fontWeight: 500, color, lineHeight: 1.1 }}>
          {value}
        </span>
        <span style={{ fontSize: 11.5, color: 'var(--on-surface-dim)' }}>{unit}</span>
      </div>
      <div style={statSub} title={sub}>{sub}</div>
    </div>
  );
}

/* ── styles ─────────────────────────────────────────────────────────────── */

const shell: React.CSSProperties = {
  minHeight: '100dvh',
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  padding: 12,
  maxWidth: 1600,
  margin: '0 auto',
};
const appBar: React.CSSProperties = {
  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
  flexWrap: 'wrap', gap: 12,
  background: 'var(--surface-container-low)',
  border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-panel)',
  padding: '12px 18px',
  minHeight: 64,
};
const wordmark: React.CSSProperties = {
  fontSize: 19, fontWeight: 500, letterSpacing: '-0.015em', lineHeight: 1.2,
};
const tagline: React.CSSProperties = {
  fontSize: 12.5, color: 'var(--on-surface-variant)',
};
const chip: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6,
  borderRadius: 'var(--r-pill)', padding: '6px 13px', fontSize: 12.5, whiteSpace: 'nowrap',
};
const tenantChip: React.CSSProperties = {
  ...chip, background: 'var(--surface-container-high)', color: 'var(--on-surface-variant)',
};
const replayChip: React.CSSProperties = {
  ...chip, background: 'var(--primary-container)', color: 'var(--on-primary-container)',
  fontWeight: 500,
};
const panel: React.CSSProperties = {
  background: 'var(--surface-container-low)',
  border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-panel)',
};
const mapControls: React.CSSProperties = {
  position: 'absolute', top: 12, left: 12, display: 'flex', gap: 6, flexWrap: 'wrap', zIndex: 2,
};
const layerBtn: React.CSSProperties = {
  ...chip, cursor: 'pointer', font: 'inherit', fontSize: 12,
  background: 'rgb(18 19 23 / 0.82)', color: 'var(--on-surface-variant)',
  border: '1px solid var(--outline-variant)',
  backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
  transition: 'background var(--dur-short) var(--ease), color var(--dur-short) var(--ease)',
};
const layerBtnOn: React.CSSProperties = {
  background: 'var(--primary-container)', color: 'var(--on-primary-container)',
  borderColor: 'transparent', fontWeight: 500,
};
const legend: React.CSSProperties = {
  position: 'absolute', bottom: 12, left: 12, zIndex: 2,
  display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center',
  background: 'rgb(18 19 23 / 0.82)', border: '1px solid var(--outline-variant)',
  backdropFilter: 'blur(8px)', WebkitBackdropFilter: 'blur(8px)',
  borderRadius: 'var(--r-pill)', padding: '7px 14px', fontSize: 11.5,
  color: 'var(--on-surface-variant)',
};
const legendItem: React.CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 5 };
const swatch: React.CSSProperties = {
  width: 9, height: 9, borderRadius: '50%', display: 'inline-block',
};
const mapLoading: React.CSSProperties = {
  position: 'absolute', top: 12, right: 12, zIndex: 2,
  display: 'flex', alignItems: 'center', gap: 8,
  background: 'rgb(18 19 23 / 0.85)', border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-pill)', padding: '7px 14px', fontSize: 12,
  color: 'var(--on-surface-variant)',
};
const spinner: React.CSSProperties = {
  width: 13, height: 13, borderRadius: '50%',
  border: '2px solid var(--outline-variant)', borderTopColor: 'var(--primary)',
  animation: 'spin 0.8s linear infinite',
};
const statGrid: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10,
};
const statCard: React.CSSProperties = {
  background: 'var(--surface-container)', border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-small)', padding: '11px 13px', minWidth: 0,
};
const statLabel: React.CSSProperties = {
  fontSize: 11, color: 'var(--on-surface-dim)', marginBottom: 5,
  letterSpacing: '0.04em', textTransform: 'uppercase',
};
const statSub: React.CSSProperties = {
  fontSize: 11.5, color: 'var(--on-surface-variant)', marginTop: 4,
  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
};
const sectionHead: React.CSSProperties = { marginBottom: 6 };
const sectionTitle: React.CSSProperties = {
  margin: 0, fontSize: 15, fontWeight: 500, letterSpacing: '-0.005em',
};
const sectionSub: React.CSSProperties = {
  margin: '3px 0 0', fontSize: 12.5, color: 'var(--on-surface-variant)',
};
const errorBar: React.CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 10,
  background: 'var(--error-container)', color: '#ffdad6',
  borderRadius: 'var(--r-panel)', padding: '11px 16px', fontSize: 13,
};
const retryBtn: React.CSSProperties = {
  ...chip, marginLeft: 'auto', cursor: 'pointer', font: 'inherit', fontSize: 12.5,
  background: 'rgb(255 255 255 / 0.14)', color: '#ffdad6', border: 'none', fontWeight: 500,
};
const pageFooter: React.CSSProperties = {
  fontSize: 11.5, color: 'var(--on-surface-dim)', textAlign: 'center',
  padding: '4px 16px 10px', lineHeight: 1.6,
};
