import { useEffect, useState, type ReactNode } from 'react';
import { Broadcast, ClockCounterClockwise, Compass, Fire, Question, Warning } from '@phosphor-icons/react';
import BriefPanel from './BriefPanel';
import Guide from './Guide';
import InfoTip from './InfoTip';
import MapView, { type Layers } from './MapView';
import Timeline from './Timeline';
import {
  band, BANDS, fetchEpisode, fetchMap, fetchResidents, fetchTimeline, fmtLong, tsForIstDay,
  type Day, type Episode, type Evidence, type MapData, type Residents,
} from '../lib/data';
import { compassWords, EXPLAIN, inkOn } from '../lib/plain';

/**
 * The officials view: what happened, why, and who should act.
 *
 * It opens with a plain-language summary so someone who has never seen an air
 * quality map knows the answer before reading any of the detail. The summary's
 * reasons come from /residents, the same deterministic, measurement-built
 * sentences residents see, so both audiences are told the same thing.
 *
 * There is deliberately no predicted-hotspot layer and no forecast: both lost to
 * simple baselines (TODO.md). Everything here is observed, or is reasoning checked
 * against something observed.
 */

const GUIDE_KEY = 'vayusetu-guide-hidden';
const guideHidden = () => {
  try { return localStorage.getItem(GUIDE_KEY) === '1'; } catch { return false; }
};

const friendly = (e: unknown) => {
  const m = String((e as any)?.message ?? e);
  if (m.startsWith('404')) return 'There is no monitor data for that time. Try another day.';
  if (m.includes('Failed to fetch') || m.includes('NetworkError')) {
    return 'Cannot reach the VayuSetu server. Check that the API is running on port 8080.';
  }
  return m;
};

const LAYERS = [
  { key: 'stations', Icon: Broadcast, text: 'Air monitors' },
  { key: 'fires', Icon: Fire, text: 'Fires' },
  { key: 'sector', Icon: Compass, text: 'Wind fan' },
] as const;

interface Props {
  ts: string;
  onTs: (ts: string) => void;
  theme: 'light' | 'dark';
}

export default function OfficialsView({ ts, onTs, theme }: Props) {
  const [days, setDays] = useState<Day[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [episode, setEpisode] = useState<Episode | null>(null);
  const [mapData, setMapData] = useState<MapData | null>(null);
  const [plain, setPlain] = useState<Residents | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [layers, setLayers] = useState<Layers>({ stations: true, fires: true, sector: true });
  const [showGuide, setShowGuide] = useState(() => !guideHidden());

  useEffect(() => {
    fetchTimeline()
      .then(setDays)
      .catch(e => setErr(friendly(e)))
      .finally(() => setTimelineLoading(false));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    Promise.all([fetchEpisode(ts), fetchMap(ts), fetchResidents(ts, 'en')])
      .then(([ep, mp, pl]) => {
        if (cancelled) return;
        setEpisode(ep);
        setMapData(mp);
        setPlain(pl);
      })
      .catch(e => { if (!cancelled) setErr(friendly(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [ts, retry]);

  const hideGuide = () => {
    setShowGuide(false);
    try { localStorage.setItem(GUIDE_KEY, '1'); } catch { /* shows again next visit */ }
  };

  const ev = episode?.evidence ?? null;

  return (
    <>
      {err && (
        <div className="error-bar" role="alert">
          <Warning size={20} />
          <span>{err}</span>
          <button type="button" className="btn btn--text" onClick={() => setRetry(r => r + 1)}>Try again</button>
        </div>
      )}

      <Summary ev={ev} plain={plain} ts={ts} loading={loading} onHowTo={() => setShowGuide(true)} />
      {showGuide && <Guide onClose={hideGuide} />}

      <main className="app-grid">
        <section className="panel map-panel" aria-label="Map of air monitors, fires and wind">
          <MapView data={mapData} ev={ev} layers={layers} theme={theme} />

          <div className="map-overlay map-controls" role="group" aria-label="Show on map">
            {LAYERS.map(({ key, Icon, text }) => (
              <button
                key={key}
                type="button"
                className="chip chip--toggle"
                aria-pressed={layers[key]}
                onClick={() => setLayers(l => ({ ...l, [key]: !l[key] }))}
              >
                <Icon size={16} weight={layers[key] ? 'fill' : 'regular'} />
                {text}
              </button>
            ))}
            <InfoTip label="What is the wind fan?">{EXPLAIN.fan}</InfoTip>
          </div>

          <div className="map-overlay map-legend" aria-label="Map key">
            {BANDS.map(b => (
              <span key={b.name} className="legend-item">
                <i className="swatch" style={{ background: b.color }} />{b.name}
              </span>
            ))}
            <span className="legend-item"><i className="swatch" style={{ background: 'var(--fire)' }} />Fire</span>
            <span className="legend-item"><i className="swatch swatch--fan" />Wind fan</span>
          </div>

          {loading && (
            <div className="map-overlay map-loading" role="status">
              <span className="spinner" /> Loading
            </div>
          )}
        </section>

        <section className="panel brief-panel" aria-label="Measurements and explanation">
          <StatStrip ev={ev} loading={loading} />
          <hr className="divider" />
          <BriefPanel
            brief={episode?.brief ?? null}
            briefError={episode?.brief_error}
            ev={ev}
            ts={ts}
            loading={loading}
          />
        </section>
      </main>

      <section className="panel panel-pad" aria-labelledby="timeline-title">
        <h2 id="timeline-title" className="section-title">Four weeks of air quality, and what drove it</h2>
        <p className="section-sub">
          Each bar is one day: taller means dirtier air. The orange line counts fires upwind of
          the city. Pick a day to see its explanation.
        </p>
        <Timeline days={days} selected={ts} onSelect={d => onTs(tsForIstDay(d))} loading={timelineLoading} />
        <p className="chart-note">
          Across these 26 days, more fires upwind went with dirtier air (correlation +0.58), and
          a lower air ceiling did too (correlation -0.48). A correlation of 1 would mean they
          always move together.
        </p>
      </section>

      <footer className="page-foot">
        Data from 70 government air monitors (CPCB, via OpenAQ), NASA FIRMS fire satellites, ERA5
        weather records and Google Earth Engine. Explanations by Gemini, checked against the
        measurements before they are shown.
      </footer>
    </>
  );
}

function Summary({ ev, plain, ts, loading, onHowTo }: {
  ev: Evidence | null;
  plain: Residents | null;
  ts: string;
  loading: boolean;
  onHowTo: () => void;
}) {
  if (loading || !ev || !plain) {
    return (
      <section className="panel summary" aria-busy="true">
        <div className="skeleton" style={{ width: 150, height: 104 }} />
        <div style={{ display: 'grid', gap: 10 }}>
          <div className="skeleton" style={{ height: 26, width: '65%' }} />
          <div className="skeleton" style={{ height: 18, width: '90%' }} />
          <div className="skeleton" style={{ height: 18, width: '75%' }} />
        </div>
      </section>
    );
  }

  const b = band(ev.city_pm25);
  return (
    <section className="panel summary fade" aria-live="polite">
      <div className="summary-band" style={{ background: b.color, color: inkOn(b.color) }}>
        <span className="summary-band-name">{b.name}</span>
        <span className="summary-band-value num">{ev.city_pm25.toFixed(0)}</span>
        <span className="summary-band-unit">µg/m³ PM2.5, city average</span>
      </div>
      <div className="summary-text">
        <p className="summary-headline">
          Air across Delhi NCR was <strong>{b.name}</strong> on {fmtLong(ts)}, India time.
          <InfoTip label="What is PM2.5?">{EXPLAIN.pm25}</InfoTip>
        </p>
        <ul className="summary-why">
          {plain.why.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
        <p className="summary-health">
          <strong>Health:</strong> {plain.health[b.name]}
          <InfoTip label="What do the air quality levels mean?">{EXPLAIN.levels}</InfoTip>
        </p>
        <div className="summary-meta">
          <span className="chip chip--quiet">
            <ClockCounterClockwise size={15} /> Replay of a real event
            <InfoTip label="Why is this a replay?">{EXPLAIN.replay}</InfoTip>
          </span>
          <button type="button" className="btn btn--text" onClick={onHowTo}>
            <Question size={17} /> How to read this page
          </button>
        </div>
      </div>
    </section>
  );
}

function StatStrip({ ev, loading }: { ev: Evidence | null; loading: boolean }) {
  if (loading || !ev) {
    return (
      <div className="stat-grid" aria-busy="true">
        {[0, 1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 96 }} />)}
      </div>
    );
  }

  const city = band(ev.city_pm25);
  const worst = band(ev.worst_station.pm25);
  const low = ev.boundary_layer_m != null && ev.boundary_layer_m < 200;
  const wind = ev.wind.from_bearing_deg;

  return (
    <div className="stat-grid fade">
      <Stat
        label="City average"
        tip={<InfoTip label="What is PM2.5?">{EXPLAIN.pm25}</InfoTip>}
        value={ev.city_pm25.toFixed(0)}
        unit="µg/m³"
        extra={<span className="band-pill" style={{ background: city.color, color: inkOn(city.color) }}>{city.name}</span>}
        sub={`${ev.n_stations_reporting} monitors reporting`}
      />
      <Stat
        label="Worst monitor"
        value={ev.worst_station.pm25.toFixed(0)}
        unit="µg/m³"
        extra={<span className="band-pill" style={{ background: worst.color, color: inkOn(worst.color) }}>{worst.name}</span>}
        sub={ev.worst_station.name}
      />
      <Stat
        label="Air ceiling"
        tip={<InfoTip label="What is the air ceiling?">{EXPLAIN.ceiling}</InfoTip>}
        value={ev.boundary_layer_m?.toFixed(0) ?? '-'}
        unit="m"
        extra={low ? <span className="flag">Very low, traps smoke</span> : undefined}
        sub={low ? undefined : 'Normal mixing'}
      />
      <Stat
        label="Fires upwind"
        tip={<InfoTip label="What are fires upwind?">{EXPLAIN.fires}</InfoTip>}
        value={String(ev.upwind_fires.count)}
        unit={`of ${ev.upwind_fires.total_fires_within_radius} nearby`}
        sub={wind != null ? `Wind from the ${compassWords(wind)}` : `Within ${ev.upwind_fires.radius_km} km`}
      />
    </div>
  );
}

function Stat({ label, tip, value, unit, extra, sub }: {
  label: string;
  tip?: ReactNode;
  value: string;
  unit: string;
  extra?: ReactNode;
  sub?: string;
}) {
  return (
    <div className="stat">
      <div className="stat-label">{label}{tip}</div>
      <div className="stat-value">
        <span className="num">{value}</span>
        <span className="stat-unit">{unit}</span>
      </div>
      {extra}
      {sub && <div className="stat-sub" title={sub}>{sub}</div>}
    </div>
  );
}
