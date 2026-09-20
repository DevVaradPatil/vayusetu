import { useEffect, useState } from 'react';
import { MapTrifold, Warning } from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import { fetchNational, fmtLong, type NationalLedger, type NationalState } from '../lib/data';
import { EXPLAIN } from '../lib/plain';

/**
 * The integrity gate, run over every CPCB monitor in the country.
 *
 * This is the part of VayuSetu useful to a board that will never look at Delhi. It is
 * also the honest test of our own method: the same four checks that caught our headline
 * hotspot, applied where we have no local knowledge to fall back on.
 */

const pct = (x: number) => `${Math.round(x * 100)}%`;

export default function National() {
  const [data, setData] = useState<NationalLedger | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetchNational().then(setData).catch(e => setErr(String(e.message ?? e)));
  }, []);

  const s = data?.summary;

  return (
    <section className="panel panel-pad" aria-labelledby="national-title">
      <h2 id="national-title" className="section-title">
        <MapTrifold size={20} /> Can India's monitors be trusted?
        <InfoTip label="How are monitors checked?">{EXPLAIN.integrity}</InfoTip>
      </h2>
      <p className="section-sub">
        Every state board runs a network it has little independent way of auditing, and every
        dashboard built on those numbers inherits the faults. These are the same four checks
        used on Delhi, run over every CPCB monitor for the same weeks.
      </p>

      {err && <div className="error-box" role="alert"><Warning size={20} /><span>{err}</span></div>}
      {!data && !err && <div className="skeleton" style={{ height: 220, marginTop: 14 }} />}

      {data && s && (
        <>
          <p className="mon-headline fade">
            <strong className="num">{s.untrusted}</strong> of <strong className="num">{s.monitors}</strong> monitors
            across <strong className="num">{s.states}</strong> states could not be trusted
            ({pct(s.untrusted_share)}) in the weeks to {fmtLong(data.window[1])}:{' '}
            <span className="num">{s.faulty}</span> reporting impossible values,{' '}
            <span className="num">{s.offline}</span> dark more than half the time.{' '}
            <span className="num">{s.suspect}</span> more read suspiciously clean.
          </p>

          <div className="ff-table-wrap">
            <table className="ff-table">
              <thead>
                <tr>
                  <th scope="col">State</th>
                  <th scope="col" className="num">Monitors</th>
                  <th scope="col" className="num">Not trustworthy</th>
                  <th scope="col" className="num">Faulty</th>
                  <th scope="col" className="num">Dark</th>
                  <th scope="col" className="num">Check siting</th>
                  <th scope="col">Worst monitors</th>
                </tr>
              </thead>
              <tbody>
                {data.states.map(st => (
                  <Row key={st.state} st={st} open={open === st.state}
                       onToggle={() => setOpen(o => (o === st.state ? null : st.state))} />
                ))}
              </tbody>
            </table>
          </div>

          <ul className="ff-caveats">
            {data.caveats.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </>
      )}
    </section>
  );
}

function Row({ st, open, onToggle }: { st: NationalState; open: boolean; onToggle: () => void }) {
  return (
    <>
      <tr className={st.untrusted_share >= 0.3 ? 'ff-row--hidden' : undefined}>
        <th scope="row">
          {st.state}
          {!st.peer_group && (
            <span className="ff-state-tag" title="Too few monitors reporting together to compare them; only stuck values and spikes are caught here">
              few monitors
            </span>
          )}
        </th>
        <td className="num">{st.monitors}</td>
        <td className="num">
          {st.untrusted}
          {st.monitors > 0 && <span className={`ff-factor${st.untrusted_share >= 0.3 ? ' ff-factor--big' : ''}`}>{pct(st.untrusted_share)}</span>}
        </td>
        <td className="num">{st.faulty}</td>
        <td className="num">{st.offline}</td>
        <td className="num">{st.suspect}</td>
        <td>
          {st.worst.length === 0 ? <span className="ff-na">—</span> : (
            <button type="button" className="btn btn--text" onClick={onToggle} aria-expanded={open}>
              {open ? 'Hide' : `Show ${st.worst.length}`}
            </button>
          )}
        </td>
      </tr>
      {open && st.worst.map(m => (
        <tr key={m.station_id} className="nat-detail">
          <td colSpan={7}>
            <div className={`mon-item mon-item--${m.status}`}>
              <div className="mon-top">
                <span className={`mon-status mon-status--${m.status}`}>{m.status}</span>
                <h3 className="mon-name">{m.name}</h3>
                <span className="mon-meta num">
                  {pct(m.uptime)} of hours reported{m.fault_rate > 0 && ` · ${pct(m.fault_rate)} faulty`}
                </span>
              </div>
              {m.example && (
                <div className="mon-evidence">
                  <span className="mon-ev-label">
                    {m.example.flags.join(', ').replace(/_/g, ' ')} at {fmtLong(m.example.at)}, and the 3 hours either side
                  </span>
                  <div className="mon-strip" role="table" aria-label="Readings against the state's middle value">
                    <div className="mon-strip-row" role="row">
                      <span className="mon-strip-head" role="rowheader">This monitor</span>
                      {m.example.readings.map((v, i) => (
                        <span key={i} role="cell" className={`num mon-cell${i === 3 ? ' mon-cell--at' : ''}`}>
                          {v == null ? '—' : Math.round(v)}
                        </span>
                      ))}
                    </div>
                    <div className="mon-strip-row" role="row">
                      <span className="mon-strip-head" role="rowheader">State middle</span>
                      {m.example.regional_median.map((v, i) => (
                        <span key={i} role="cell" className={`num mon-cell mon-cell--ref${i === 3 ? ' mon-cell--at' : ''}`}>
                          {v == null ? '—' : Math.round(v)}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </td>
        </tr>
      ))}
    </>
  );
}
