import { useCallback, useEffect, useState } from 'react';
import {
  Broadcast, Camera, CheckCircle, ClockCountdown, Crosshair, FolderOpen, MapPin, Warning, Wind, XCircle,
} from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import {
  acknowledgeCase, closeCase, fetchCases, fmtLong, previewCases, raiseCases,
  type Case, type CaseKind, type CasePreview, type CaseQueue, type ClosureResult,
} from '../lib/data';
import { EXPLAIN } from '../lib/plain';

/**
 * The case desk: who owns what, by when, and whether it was really fixed.
 *
 * India's air quality response does not usually fail at detection; it fails at
 * closure. Green Delhi took 84,765 complaints in 2024, 10,656 went overdue, and one
 * department had 99 of its 183 "resolved" complaints reopened. So the numbers at the
 * top are accountability numbers, and a case here closes only when a photo and the
 * measurements afterwards both check out — decided in code, shown with the evidence.
 *
 * Every agency and actor is a demo account (AGENTS.md R6). Opening cases is a button
 * press, never a side effect of loading the page.
 */

const KIND: Record<CaseKind, { label: string; Icon: typeof Warning }> = {
  local_event: { label: 'Local event', Icon: Crosshair },
  monitor_fault: { label: 'Monitor fault', Icon: Broadcast },
  regional_episode: { label: 'Region-wide', Icon: Wind },
};

const hoursText = (h: number) => {
  const a = Math.abs(h);
  return a < 1 ? `${Math.round(a * 60)} min` : a < 48 ? `${a.toFixed(a < 10 ? 1 : 0)} h` : `${Math.round(a / 24)} days`;
};

const words = (s: string) => s.replace(/_/g, ' ');

export default function CaseDesk({ ts }: { ts: string }) {
  const [queue, setQueue] = useState<CaseQueue | null>(null);
  const [preview, setPreview] = useState<CasePreview | null>(null);
  const [actor, setActor] = useState('mock_municipal');
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showClosed, setShowClosed] = useState(false);

  const load = useCallback(() => {
    fetchCases().then(setQueue).catch(e => setErr(String(e.message ?? e)));
  }, []);
  useEffect(load, [load]);

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    previewCases(ts).then(p => { if (!cancelled) setPreview(p); }).catch(() => { if (!cancelled) setPreview(null); });
    return () => { cancelled = true; };
  }, [ts]);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setErr(null);
    try {
      await fn();
      load();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const open = (queue?.cases ?? []).filter(c => !c.closed);
  const closed = (queue?.cases ?? []).filter(c => c.closed);
  const s = queue?.summary;

  return (
    <section className="panel panel-pad" aria-labelledby="cases-title">
      <h2 id="cases-title" className="section-title">
        <FolderOpen size={20} /> Cases
        <InfoTip label="How do cases work?">{EXPLAIN.cases}</InfoTip>
      </h2>
      <p className="section-sub">
        Work raised from trusted measurements, owned by a named agency, with a deadline. A case
        closes only when a site photo and the readings afterwards both show the problem is gone.
      </p>

      {s && (
        <div className="case-kpis fade" role="list" aria-label="Accountability">
          <Kpi label="Open" value={s.open} />
          <Kpi label="Overdue" value={s.overdue} tone={s.overdue ? 'bad' : undefined} />
          <Kpi label="Closed, verified" value={s.closed_verified} tone="good" />
          <Kpi label="Closed without proof" value={s.closed_unverified} tone={s.closed_unverified ? 'warn' : undefined} />
          <Kpi label="Closures refused" value={s.closure_rejections} hint="Closures the evidence did not support" />
        </div>
      )}

      {err && <div className="error-box" style={{ marginTop: 12 }} role="alert"><Warning size={20} /><span>{err}</span></div>}

      <div className="al-bar">
        {preview === null && <span className="al-quiet">Checking what this hour justifies…</span>}
        {preview && preview.candidates.length > 0 && (
          <>
            <span className="al-ready">
              This hour justifies {preview.candidates.length} case{preview.candidates.length === 1 ? '' : 's'}
              {' '}({summariseKinds(preview)}). Work already open is not duplicated.
            </span>
            <button type="button" className="btn btn--primary" disabled={busy === 'raise'}
                    onClick={() => run('raise', () => raiseCases(ts))}>
              {busy === 'raise' ? 'Opening…' : 'Open these cases'}
            </button>
          </>
        )}
        {preview && preview.candidates.length === 0 && (
          <span className="al-quiet">{preview.no_trigger_reason ?? 'Nothing this hour justifies a case.'}</span>
        )}
        <label className="al-actor">
          Acting as
          <select value={actor} onChange={e => setActor(e.target.value)}>
            {Object.entries(queue?.actors ?? { mock_municipal: 'Demo: municipal enforcement officer' }).map(([k, v]) => (
              <option key={k} value={k}>{v.replace('Demo: ', '')}</option>
            ))}
          </select>
        </label>
      </div>

      {!queue && !err && <div className="skeleton" style={{ height: 120, marginTop: 12 }} />}
      {queue && open.length === 0 && (
        <p className="al-quiet" style={{ marginTop: 14 }}>No open cases.</p>
      )}

      <ul className="case-list">
        {open.map(c => (
          <CaseRow key={c.case_id} c={c} actor={actor} busy={busy === c.case_id}
                   onAck={() => run(c.case_id, () => acknowledgeCase(c.case_id, actor))}
                   onClosed={load} />
        ))}
      </ul>

      {closed.length > 0 && (
        <details className="al-done" open={showClosed} onToggle={e => setShowClosed((e.target as HTMLDetailsElement).open)}>
          <summary>{closed.length} closed</summary>
          <ul className="case-list">
            {closed.map(c => <CaseRow key={c.case_id} c={c} actor={actor} busy={false} onAck={() => {}} onClosed={load} />)}
          </ul>
        </details>
      )}
    </section>
  );
}

function summariseKinds(p: CasePreview) {
  const n = (k: CaseKind) => p.candidates.filter(c => c.kind === k).length;
  return [
    n('local_event') && `${n('local_event')} local event`,
    n('regional_episode') && 'region-wide Severe',
    n('monitor_fault') && `${n('monitor_fault')} monitor fault${n('monitor_fault') === 1 ? '' : 's'}`,
  ].filter(Boolean).join(', ');
}

function Kpi({ label, value, tone, hint }: { label: string; value: number; tone?: 'good' | 'bad' | 'warn'; hint?: string }) {
  return (
    <div className={`case-kpi${tone ? ` case-kpi--${tone}` : ''}`} role="listitem" title={hint}>
      <span className="case-kpi-value num">{value}</span>
      <span className="case-kpi-label">{label}</span>
    </div>
  );
}

function CaseRow({ c, actor, busy, onAck, onClosed }: {
  c: Case; actor: string; busy: boolean; onAck: () => void; onClosed: () => void;
}) {
  const k = KIND[c.kind];
  const [closing, setClosing] = useState(false);
  const lastRejection = [...c.events].reverse().find(e => e.action === 'closure_rejected');

  return (
    <li className={`case-item case-item--${c.closed ? 'closed' : c.overdue ? 'overdue' : c.severity}`}>
      <div className="case-head">
        <span className="case-kind"><k.Icon size={15} weight="fill" /> {k.label}</span>
        <span className={`al-sev al-sev--${c.severity}`}>{c.severity}</span>
        <StatusChip c={c} />
      </div>
      <h3 className="case-title">{c.title}</h3>
      <p className="case-detail">{c.detail}</p>
      <p className="al-meta">
        Owner <strong>{c.owner.replace('Demo: ', '')}</strong>
        {c.copied.length > 0 && <> · copied to {c.copied.map(x => x.replace('Demo: ', '')).join(', ')}</>}
        {' '}· measured {fmtLong(c.event_hour)}
      </p>

      {c.closure && <ClosureView r={c.closure} />}
      {!c.closed && lastRejection && (
        <p className="case-rejected"><XCircle size={15} weight="fill" /> Last closure refused: {lastRejection.note}</p>
      )}

      {!c.closed && (
        <div className="al-actions">
          {c.status === 'open' && (
            <button type="button" className="btn btn--tonal" disabled={busy} onClick={onAck}>
              <CheckCircle size={16} /> Take ownership
            </button>
          )}
          <button type="button" className="btn btn--text" onClick={() => setClosing(v => !v)} aria-expanded={closing}>
            <Camera size={16} /> {closing ? 'Cancel' : 'Submit closure'}
          </button>
        </div>
      )}
      {closing && !c.closed && <CloseForm c={c} actor={actor} onDone={() => { setClosing(false); onClosed(); }} />}

      {c.events.length > 0 && (
        <details className="case-log">
          <summary>Audit trail ({c.events.length})</summary>
          <ol>
            {c.events.map((e, i) => (
              <li key={i}>
                <span className="num">{new Date(e.at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</span>
                {' '}<strong>{words(e.action)}</strong>
                {e.actor && <> by {e.actor.replace('Demo: ', '')}</>}
                {e.note && <> — {e.note}</>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </li>
  );
}

function StatusChip({ c }: { c: Case }) {
  if (c.status === 'closed_verified') return <span className="case-status case-status--good"><CheckCircle size={14} weight="fill" /> Closed, verified</span>;
  if (c.status === 'closed_unverified') return <span className="case-status case-status--warn">Closed without proof</span>;
  if (c.overdue) {
    return (
      <span className="case-status case-status--bad">
        <ClockCountdown size={14} weight="fill" /> Overdue {hoursText(c.hours_left)} · escalated to {c.escalates_to.replace('Demo: ', '')}
      </span>
    );
  }
  return (
    <span className="case-status">
      <ClockCountdown size={14} /> {c.status === 'in_progress' ? 'In progress' : 'Unassigned'} · due in {hoursText(c.hours_left)}
    </span>
  );
}

function CloseForm({ c, actor, onDone }: { c: Case; actor: string; onDone: () => void }) {
  const [note, setNote] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [demoLocation, setDemoLocation] = useState(false);
  const [coords, setCoords] = useState<{ lat: number; lon: number } | null>(null);
  const [locErr, setLocErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ClosureResult | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const needsPhoto = c.kind !== 'regional_episode';

  const locate = () => {
    setLocErr(null);
    navigator.geolocation?.getCurrentPosition(
      p => setCoords({ lat: p.coords.latitude, lon: p.coords.longitude }),
      e => setLocErr(e.message || 'Location unavailable'),
      { enableHighAccuracy: true, timeout: 10000 },
    );
  };

  const submit = async () => {
    setBusy(true);
    setErr(null);
    const f = new FormData();
    f.append('actor', actor);
    f.append('note', note);
    if (photo) f.append('photo', photo);
    f.append('location_source', demoLocation ? 'demo_case_location' : 'device');
    if (!demoLocation && coords) {
      f.append('lat', String(coords.lat));
      f.append('lon', String(coords.lon));
    }
    try {
      const r = await closeCase(c.case_id, f);
      setResult(r);
      if (r.result !== 'rejected') setTimeout(onDone, 2500);
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="case-close">
      <label className="case-field">
        <span>{needsPhoto ? 'What was done (optional)' : 'Measures taken'}</span>
        <textarea rows={2} value={note} onChange={e => setNote(e.target.value)}
                  placeholder={needsPhoto ? 'e.g. Garbage fire extinguished, site cleared' : 'e.g. GRAP stage III enforced: construction halted, trucks diverted'} />
      </label>
      {needsPhoto && (
        <>
          <label className="case-field">
            <span>Photo of the site{c.kind === 'monitor_fault' ? ', showing the monitor' : ''}</span>
            <input type="file" accept="image/*" capture="environment" onChange={e => setPhoto(e.target.files?.[0] ?? null)} />
          </label>
          <div className="case-loc">
            <button type="button" className="btn btn--text" onClick={locate} disabled={demoLocation}>
              <MapPin size={16} /> {coords ? `Located (${coords.lat.toFixed(4)}, ${coords.lon.toFixed(4)})` : 'Use my location'}
            </button>
            <label className="case-demo">
              <input type="checkbox" checked={demoLocation} onChange={e => setDemoLocation(e.target.checked)} />
              Demo: use the case's location (recorded as "not a field visit")
            </label>
          </div>
          {locErr && <p className="al-meta">{locErr}</p>}
        </>
      )}
      <button type="button" className="btn btn--primary" onClick={submit} disabled={busy}>
        {busy ? 'Checking evidence…' : 'Check evidence and close'}
      </button>
      {err && <div className="error-box" role="alert"><Warning size={20} /><span>{err}</span></div>}
      {result && <ClosureView r={result} />}
    </div>
  );
}

function ClosureView({ r }: { r: ClosureResult }) {
  const ok = r.result === 'closed_verified';
  const cls = ok ? 'good' : r.result === 'closed_unverified' ? 'warn' : 'bad';
  const hours = r.outcome_hours ?? [];
  return (
    <div className={`case-verdict case-verdict--${cls}`} aria-live="polite">
      <p className="case-verdict-head">
        {ok ? <CheckCircle size={18} weight="fill" /> : r.result === 'rejected' ? <XCircle size={18} weight="fill" /> : <Warning size={18} weight="fill" />}
        {ok ? 'Closed — the evidence and the measurements agree' : r.result === 'rejected' ? 'Closure refused' : 'Closed without proof'}
      </p>
      <ul>{r.reasons.map((x, i) => <li key={i}>{x}</li>)}</ul>
      {r.photo && (
        <p className="al-meta">
          Photo: {r.photo.is_genuine_site_photo ? 'genuine site photo' : `rejected (${words(r.photo.rejection_reason ?? 'not a site photo')})`}
          {r.photo.active_sources_visible.length > 0 && ` · still visible: ${r.photo.active_sources_visible.map(words).join(', ')}`}
          {r.photo.remediation_visible.length > 0 && ` · remediation seen: ${r.photo.remediation_visible.map(words).join(', ')}`}
          {r.upload_distance_km != null && ` · ${r.upload_distance_km} km from the site`}
          {r.location_source === 'demo_case_location' && ' (demo location, not a field visit)'}
        </p>
      )}
      {hours.length > 0 && (
        <div className="case-outcome">
          <span className="mon-ev-label">What the measurements showed afterwards ({r.outcome_basis})</span>
          <div className="case-spark" role="img" aria-label={r.outcome_summary}>
            {hours.map((h, i) => {
              const v = h.value ?? h.regional_median ?? null;
              const top = Math.max(1, ...hours.map(x => x.value ?? x.regional_median ?? 0));
              const bad = h.elevated || (h.faults && h.faults.length > 0) || (h.value == null && h.regional_median == null);
              return (
                <span key={i} className={`case-bar${bad ? ' case-bar--bad' : ''}`}
                      style={{ height: `${v == null ? 6 : Math.max(6, (v / top) * 100)}%` }}
                      title={`${new Date(h.at).toLocaleString('en-IN', { timeStyle: 'short', dateStyle: 'short' })}: ${v ?? 'no reading'}`} />
              );
            })}
          </div>
          <span className="al-meta">{r.outcome_summary}</span>
        </div>
      )}
    </div>
  );
}
