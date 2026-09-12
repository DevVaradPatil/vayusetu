import { useCallback, useEffect, useState } from 'react';
import { BellRinging, Check, CheckCircle, PaperPlaneTilt, Warning } from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import {
  ACTORS, actOnAlert, dispatchAlerts, fetchAlerts, fmtLong, previewAlerts,
  type Alert, type AlertPreview,
} from '../lib/data';
import { EXPLAIN } from '../lib/plain';

/**
 * The alert inbox: who was told, whether they picked it up, and whether it is done.
 *
 * Three things here are deliberate.
 *
 * **Nothing is raised by loading the page.** The panel previews what the hour would
 * raise; a person presses the button to raise it. Every recipient in this system is a
 * demo account, so nobody could be paged either way — but a page load that dispatches
 * is one wiring change away from paging a real official, and that change should have
 * to be visible.
 *
 * **"Nothing to raise" is shown with its reason.** An empty inbox during a clean hour
 * is the correct output, and a reader cannot tell a correct empty from a broken one.
 *
 * **You act as somebody.** Acknowledging asks which demo account you are, because an
 * alert nobody is accountable for is the failure mode this whole panel exists to
 * prevent. The audit trail records it.
 */

const SEV_ICON = {
  emergency: Warning,
  warning: BellRinging,
  watch: BellRinging,
} as const;

interface Props {
  ts: string;
  /** Bumped when the hour's data reloads, so the preview follows the page. */
  reloadKey: number;
}

export default function AlertInbox({ ts, reloadKey }: Props) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [preview, setPreview] = useState<AlertPreview | null>(null);
  const [actor, setActor] = useState(ACTORS[0].key);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchAlerts().then(setAlerts).catch(e => setErr(String(e.message ?? e)));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    let cancelled = false;
    setPreview(null);
    previewAlerts(ts)
      .then(p => { if (!cancelled) setPreview(p); })
      .catch(() => { if (!cancelled) setPreview(null); });
    return () => { cancelled = true; };
  }, [ts, reloadKey]);

  const act = async (id: string, action: 'acknowledge' | 'resolve') => {
    setBusy(id);
    setErr(null);
    try {
      await actOnAlert(id, action, actor);
      load();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const raise = async () => {
    setBusy('dispatch');
    setErr(null);
    try {
      await dispatchAlerts(ts);
      load();
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };

  const open = (alerts ?? []).filter(a => a.state === 'open');
  const done = (alerts ?? []).filter(a => a.state !== 'open');
  const already = new Set((alerts ?? []).map(a => a.headline));
  const fresh = (preview?.candidates ?? []).filter(c => !already.has(c.headline));

  return (
    <section className="panel panel-pad" aria-labelledby="alerts-title">
      <h2 id="alerts-title" className="section-title">
        <BellRinging size={20} /> Alerts
        <InfoTip label="How do alerts work?">{EXPLAIN.alerts}</InfoTip>
      </h2>
      <p className="section-sub">
        Raised from what the monitors measured this hour — never from a prediction. Every
        recipient is a demo account: this system holds no real official's contact details.
      </p>

      {err && (
        <div className="error-box" style={{ marginTop: 12 }} role="alert">
          <Warning size={20} />
          <span>{err}</span>
        </div>
      )}

      <div className="al-bar">
        {preview === null && <span className="al-quiet">Checking this hour…</span>}

        {preview && fresh.length > 0 && (
          <>
            <span className="al-ready">
              {fresh.length === 1 ? '1 alert' : `${fresh.length} alerts`} ready to raise for{' '}
              {fmtLong(ts)}
            </span>
            <button type="button" className="btn btn--primary" onClick={raise} disabled={busy === 'dispatch'}>
              <PaperPlaneTilt size={17} />
              {busy === 'dispatch' ? 'Raising…' : 'Raise to the mock inbox'}
            </button>
          </>
        )}

        {preview && fresh.length === 0 && (
          <span className="al-quiet">
            {preview.no_trigger_reason
              ?? 'Everything this hour would raise has already been raised.'}
          </span>
        )}

        <label className="al-actor">
          Acting as
          <select value={actor} onChange={e => setActor(e.target.value)}>
            {ACTORS.map(a => <option key={a.key} value={a.key}>{a.label.replace('Demo: ', '')}</option>)}
          </select>
        </label>
      </div>

      {alerts === null && <div className="skeleton" style={{ height: 80, marginTop: 12 }} />}

      {alerts !== null && alerts.length === 0 && (
        <p className="al-quiet" style={{ marginTop: 14 }}>
          The inbox is empty. Nothing has been raised yet.
        </p>
      )}

      {open.length > 0 && (
        <ul className="al-list">
          {open.map(a => <Row key={a.alert_id} a={a} busy={busy === a.alert_id} onAct={act} />)}
        </ul>
      )}

      {done.length > 0 && (
        <details className="al-done">
          <summary>{done.length} handled</summary>
          <ul className="al-list">
            {done.map(a => <Row key={a.alert_id} a={a} busy={busy === a.alert_id} onAct={act} />)}
          </ul>
        </details>
      )}
    </section>
  );
}

function Row({ a, busy, onAct }: {
  a: Alert;
  busy: boolean;
  onAct: (id: string, action: 'acknowledge' | 'resolve') => void;
}) {
  const Icon = SEV_ICON[a.severity] ?? BellRinging;
  return (
    <li className={`al-item al-item--${a.severity} al-item--${a.state}`}>
      <span className={`al-sev al-sev--${a.severity}`}>
        <Icon size={15} weight="fill" /> {a.severity}
      </span>

      <div className="al-body">
        <p className="al-head">{a.headline}</p>
        <p className="al-meta">
          {a.trigger_kind === 'hyper_local_event' ? 'One locality' : 'The whole region'} ·{' '}
          {a.ts_hour ? fmtLong(a.ts_hour) : '—'}
          {a.population_exposed != null
            && ` · about ${a.population_exposed.toLocaleString('en-IN')} people in that square kilometre`}
        </p>
        <p className="al-meta">Sent to {a.recipients.join(', ')}</p>
        {a.state !== 'open' && (
          <p className="al-trail">
            <Check size={14} /> Acknowledged by {a.acknowledged_by?.replace(/^mock_/, '').replace(/_/g, ' ')}
            {a.resolved_by && ` · resolved by ${a.resolved_by.replace(/^mock_/, '').replace(/_/g, ' ')}`}
          </p>
        )}
      </div>

      <div className="al-actions">
        {a.state === 'open' && (
          <button type="button" className="btn btn--tonal" disabled={busy}
                  onClick={() => onAct(a.alert_id, 'acknowledge')}>
            <Check size={16} /> Acknowledge
          </button>
        )}
        {a.state !== 'resolved' && (
          <button type="button" className="btn btn--text" disabled={busy}
                  onClick={() => onAct(a.alert_id, 'resolve')}>
            <CheckCircle size={16} /> Resolve
          </button>
        )}
        {a.state === 'resolved' && <span className="al-closed">Closed</span>}
      </div>
    </li>
  );
}
