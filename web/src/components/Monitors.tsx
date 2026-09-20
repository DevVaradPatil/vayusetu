import { useEffect, useMemo, useState } from 'react';
import { Broadcast, CheckCircle, Warning, WifiSlash, Wrench } from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import {
  band, fetchLiveNow, fetchMonitorHealth, fmtLong, type LiveNow, type MonitorHealth,
  type MonitorStatus, type NetworkHealth,
} from '../lib/data';
import { EXPLAIN, inkOn } from '../lib/plain';

/**
 * Which air monitors can be trusted, and which need a technician.
 *
 * Every decision on this site starts from one monitor's number, so this is the first
 * thing an official should check — and it is useful on its own: a broken, dark or
 * implausibly clean monitor is work for the pollution control board. Our own first
 * hotspot headline turned out to be a broken sensor, and nationally only 270 of 562
 * real-time monitors gave stable data in 2025.
 *
 * Every claim that a government monitor is faulty comes with the raw readings next to
 * the regional middle value, so a reader can see the fault instead of trusting a label.
 */

const STATUS: Record<MonitorStatus, { label: string; Icon: typeof Warning; action: string }> = {
  faulty: { label: 'Faulty', Icon: Wrench, action: 'Send the maintenance contractor. Readings from it are not used.' },
  offline: { label: 'Offline', Icon: WifiSlash, action: 'The monitor is dark. Restore power or data link.' },
  suspect: { label: 'Check siting', Icon: Warning, action: 'Reads far cleaner than every neighbour in severe smog. Inspect what is around it.' },
  healthy: { label: 'Healthy', Icon: CheckCircle, action: '' },
};

const PROBLEM_WORDS: Record<string, string> = {
  stuck: 'repeats the exact same reading for hours, as if frozen',
  dead_zero: 'reports zero while the air around it is dirty',
  spike: 'jumps by hundreds and straight back within an hour',
  low_in_episode: 'reads far cleaner than its neighbours during severe smog',
};

/** "reports zero while the air around it is dirty (26 h) and jumps by hundreds…" */
function whatIsWrong(m: MonitorHealth): string {
  const parts = (Object.entries(m.flag_counts) as [string, number][])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${PROBLEM_WORDS[k]} (${n} h)`);
  if (m.status === 'offline') {
    parts.unshift(`reported only ${Math.round(m.uptime * 100)}% of hours`);
  }
  if (!parts.length) return '';
  const s = parts.join('; ');
  return s.charAt(0).toUpperCase() + s.slice(1) + '.';
}

const FILTERS: { key: 'problems' | MonitorStatus; label: string }[] = [
  { key: 'problems', label: 'Needs attention' },
  { key: 'faulty', label: 'Faulty' },
  { key: 'offline', label: 'Offline' },
  { key: 'suspect', label: 'Check siting' },
  { key: 'healthy', label: 'Healthy' },
];

export default function Monitors({ ts }: { ts: string }) {
  const [data, setData] = useState<NetworkHealth | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [filter, setFilter] = useState<'problems' | MonitorStatus>('problems');

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setErr(null);
    fetchMonitorHealth(ts, 7)
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setErr(String(e.message ?? e)); });
    return () => { cancelled = true; };
  }, [ts]);

  const shown = useMemo(() => {
    const all = data?.monitors ?? [];
    return filter === 'problems' ? all.filter(m => m.status !== 'healthy') : all.filter(m => m.status === filter);
  }, [data, filter]);

  const total = data?.monitors.length ?? 0;
  const untrusted = data ? data.summary.faulty + data.summary.offline : 0;

  return (
    <section className="panel panel-pad" aria-labelledby="monitors-title">
      <h2 id="monitors-title" className="section-title">
        <Broadcast size={20} /> Can the monitors be trusted?
        <InfoTip label="How are monitors checked?">{EXPLAIN.integrity}</InfoTip>
      </h2>
      <p className="section-sub">
        Every alert and hotspot on this site starts from one monitor's reading. Before any of it
        is used, each reading is checked for patterns real air does not produce.
      </p>

      <RightNow />

      {err && <div className="error-box" role="alert"><Warning size={20} /><span>{err}</span></div>}
      {!data && !err && <div className="skeleton" style={{ height: 160, marginTop: 14 }} />}

      {data && (
        <>
          <div className="mon-headline fade">
            <p>
              <strong className="num">{untrusted}</strong> of <strong className="num">{total}</strong>{' '}
              monitors could not be trusted in the week to {fmtLong(data.window[1])}.
              {data.summary.suspect > 0 && ` ${data.summary.suspect} more read suspiciously clean.`}
            </p>
            <div className="mon-counts" role="group" aria-label="Filter monitors">
              {FILTERS.map(f => {
                const n = f.key === 'problems' ? total - data.summary.healthy : data.summary[f.key];
                return (
                  <button
                    key={f.key}
                    type="button"
                    className={`chip chip--toggle mon-chip mon-chip--${f.key}`}
                    aria-pressed={filter === f.key}
                    onClick={() => setFilter(f.key)}
                  >
                    {f.label} <span className="num">{n}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {shown.length === 0 && (
            <p className="al-quiet" style={{ marginTop: 12 }}>No monitors in this group this week.</p>
          )}

          <ul className="mon-list">
            {shown.map(m => <Row key={m.station_id} m={m} />)}
          </ul>
        </>
      )}
    </section>
  );
}

/**
 * The live second opinion.
 *
 * Everything else here is a replay, because the CPCB-to-OpenAQ feed that supplies our
 * monitors is stalled. Google's Air Quality API is modelled rather than measured, so it
 * is current regardless — which makes it the right thing to show beside our own latest
 * reading and its age, and the wrong thing to feed into a hotspot or a case. Nothing
 * downstream reads it.
 */
function RightNow() {
  const [live, setLive] = useState<LiveNow | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchLiveNow().then(setLive).catch(() => setFailed(true));
  }, []);

  if (failed) return null;
  if (!live) return <div className="skeleton" style={{ height: 74, marginTop: 14 }} />;

  const m = live.modelled;
  const o = live.measured;
  const b = m.pm25 != null ? band(m.pm25) : null;
  const days = o.age_hours != null ? Math.round(o.age_hours / 24) : null;
  return (
    <div className="live-now fade">
      <div className="live-col">
        <span className="live-label">Right now, modelled</span>
        <span className="live-value num">
          {m.pm25 ?? '—'}<span className="live-unit">µg/m³ PM2.5</span>
        </span>
        <span className="live-sub">
          {b && <span className="band-pill" style={{ background: b.color, color: inkOn(b.color) }}>{b.name}</span>}
          {' '}NAQI {m.cpcb_aqi ?? '—'} · Google Air Quality, {fmtLong(m.at)}
        </span>
      </div>
      <div className="live-col">
        <span className="live-label">Our last measurement</span>
        <span className="live-value num">
          {o.median_pm25 ?? '—'}<span className="live-unit">µg/m³ median</span>
        </span>
        <span className="live-sub">
          {o.monitors} monitor{o.monitors === 1 ? '' : 's'} · {days != null ? `${days} days old` : 'no reading'}
        </span>
      </div>
      <p className="live-note">
        The CPCB feed we depend on is stalled, so our own numbers are a replay of
        October-November 2025. The modelled figure is shown for context only: hotspots,
        cases and the brief use measured readings, never a model.
      </p>
    </div>
  );
}

function Row({ m }: { m: MonitorHealth }) {
  const st = STATUS[m.status];
  const wrong = whatIsWrong(m);
  const ex = m.example;
  return (
    <li className={`mon-item mon-item--${m.status}`}>
      <div className="mon-top">
        <span className={`mon-status mon-status--${m.status}`}><st.Icon size={15} weight="fill" /> {st.label}</span>
        <h3 className="mon-name">{m.name}</h3>
        <span className="mon-meta num">
          {Math.round(m.uptime * 100)}% of hours reported
          {m.fault_rate > 0 && ` · ${Math.round(m.fault_rate * 100)}% faulty`}
        </span>
      </div>
      {wrong && <p className="mon-wrong">{wrong}</p>}
      {st.action && <p className="mon-action">{st.action}</p>}
      {ex && (
        <div className="mon-evidence">
          <span className="mon-ev-label">
            Evidence, {fmtLong(ex.at)} and the 3 hours either side
          </span>
          <div className="mon-strip" role="table" aria-label="Readings against the regional middle value">
            <div className="mon-strip-row" role="row">
              <span className="mon-strip-head" role="rowheader">This monitor</span>
              {ex.readings.map((v, i) => (
                <span key={i} role="cell" className={`num mon-cell${i === 3 ? ' mon-cell--at' : ''}`}>
                  {v == null ? '—' : Math.round(v)}
                </span>
              ))}
            </div>
            <div className="mon-strip-row" role="row">
              <span className="mon-strip-head" role="rowheader">Region middle</span>
              {ex.regional_median.map((v, i) => (
                <span key={i} role="cell" className={`num mon-cell mon-cell--ref${i === 3 ? ' mon-cell--at' : ''}`}>
                  {v == null ? '—' : Math.round(v)}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}
    </li>
  );
}
