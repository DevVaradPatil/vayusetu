import { useEffect, useMemo, useState } from 'react';
import { Fire, Warning } from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import { fetchFireLedger, type FireDistrict, type FireLedger } from '../lib/data';
import { EXPLAIN } from '../lib/plain';

/**
 * Farm fires: where satellite fire alerts undercount the burning.
 *
 * Fire counts come from satellites that pass over Punjab and Haryana around midday, and
 * farmers now burn after they have passed. Burn scars do not care what time a field
 * burned, so burned land per alert shows where counts have stopped meaning what they
 * used to. Each district is compared with its own 2020-21 seasons, not with a hectare
 * figure, because both satellite products have biases that a same-place ratio cancels.
 */

type Order = 'area' | 'alerts';
const fmt = (n: number) => n.toLocaleString('en-IN');

export default function FarmFires() {
  const [data, setData] = useState<FireLedger | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [order, setOrder] = useState<Order>('area');

  useEffect(() => {
    fetchFireLedger().then(setData).catch(e => setErr(String(e.message ?? e)));
  }, []);

  const rows = useMemo(() => {
    const all = (data?.districts ?? []).filter(d => d.burned_km2 > 0 || d.day_detections > 0);
    return [...all].sort((a, b) => order === 'area'
      ? a.rank_by_burned_area - b.rank_by_burned_area
      : a.rank_by_detections - b.rank_by_detections);
  }, [data, order]);

  const base = data?.baseline_seasons.join('–') ?? '';

  return (
    <section className="panel panel-pad" aria-labelledby="fires-title">
      <h2 id="fires-title" className="section-title">
        <Fire size={20} /> Are fire counts still telling the truth?
        <InfoTip label="How is this measured?">{EXPLAIN.fireLedger}</InfoTip>
      </h2>
      <p className="section-sub">
        Fire alerts come from satellites that pass over around midday. Burn scars show every field
        that burned, whatever the hour. Where the two drift apart, fire counts are sending
        inspectors to the wrong places.
      </p>

      {err && <div className="error-box" role="alert"><Warning size={20} /><span>{err}</span></div>}
      {!data && !err && <div className="skeleton" style={{ height: 200, marginTop: 14 }} />}

      {data && (
        <>
          <div className="ff-states fade">
            {Object.entries(data.trend).map(([state, seasons]) => <StateTrend key={state} state={state} seasons={seasons} base={data.baseline_seasons} />)}
          </div>

          <div className="ff-head">
            <h3 className="ff-sub">Districts, {data.season} season</h3>
            <div className="mon-counts" role="group" aria-label="Rank districts by">
              <button type="button" className="chip chip--toggle" aria-pressed={order === 'area'} onClick={() => setOrder('area')}>
                By land burned
              </button>
              <button type="button" className="chip chip--toggle" aria-pressed={order === 'alerts'} onClick={() => setOrder('alerts')}>
                By fire alerts
              </button>
            </div>
          </div>

          <div className="ff-table-wrap">
            <table className="ff-table">
              <thead>
                <tr>
                  <th scope="col">District</th>
                  <th scope="col" className="num">Land burned, km²</th>
                  <th scope="col" className="num">Daytime alerts</th>
                  <th scope="col" className="num">Rank by land / by alerts</th>
                  <th scope="col" className="num">km² per alert, {base} → {data.season}</th>
                  <th scope="col" className="num">Alerts at the {base} rate</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(d => <DistrictRow key={`${d.state}-${d.district}`} d={d} />)}
              </tbody>
            </table>
          </div>

          <ul className="ff-caveats">
            {data.caveats.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
          <p className="chart-note">
            Sources: {data.sources.burned_area}; {data.sources.detections}; {data.sources.boundaries}.
          </p>
        </>
      )}
    </section>
  );
}

function StateTrend({ state, seasons, base }: { state: string; seasons: FireLedger['trend'][string]; base: number[] }) {
  const b = seasons.filter(s => base.includes(s.season));
  const last = seasons[seasons.length - 1];
  const avg = (k: 'burned_km2' | 'day_detections') => b.reduce((t, s) => t + s[k], 0) / (b.length || 1);
  const alertsDrop = 1 - last.day_detections / avg('day_detections');
  const landDrop = 1 - last.burned_km2 / avg('burned_km2');
  const maxB = Math.max(...seasons.map(s => s.burned_km2));
  const maxD = Math.max(...seasons.map(s => s.day_detections));
  return (
    <div className="ff-state">
      <h3 className="ff-sub">{state}</h3>
      <p className="ff-lede">
        Since {base.join('–')}, fire alerts fell <strong className="num">{Math.round(alertsDrop * 100)}%</strong>;
        land burned fell <strong className="num">{Math.round(landDrop * 100)}%</strong>.
      </p>
      <div className="ff-bars" role="table" aria-label={`${state}: land burned and fire alerts by season`}>
        {seasons.map(s => (
          <div key={s.season} className="ff-bar-row" role="row">
            <span role="rowheader" className="num ff-year">{s.season}</span>
            <span role="cell" className="ff-bar-cell">
              <i className="ff-bar ff-bar--land" style={{ width: `${(s.burned_km2 / maxB) * 100}%` }} />
              <span className="num">{fmt(Math.round(s.burned_km2))} km²</span>
            </span>
            <span role="cell" className="ff-bar-cell">
              <i className="ff-bar ff-bar--alerts" style={{ width: `${(s.day_detections / maxD) * 100}%` }} />
              <span className="num">{fmt(s.day_detections)} alerts</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DistrictRow({ d }: { d: FireDistrict }) {
  const big = d.undercount_factor != null && d.undercount_factor >= 8;
  return (
    <tr className={big ? 'ff-row--hidden' : undefined}>
      <th scope="row">{d.district}<span className="ff-state-tag">{d.state}</span></th>
      <td className="num">{fmt(Math.round(d.burned_km2))}</td>
      <td className="num">{fmt(d.day_detections)}</td>
      <td className="num">#{d.rank_by_burned_area} / #{d.rank_by_detections}</td>
      <td className="num">
        {d.undercount_factor == null ? <span className="ff-na" title="Too few fires to compare">—</span> : (
          <>
            {d.baseline_km2_per_detection?.toFixed(2)} → {d.km2_per_detection?.toFixed(2)}{' '}
            <span className={`ff-factor${big ? ' ff-factor--big' : ''}`}>{d.undercount_factor}×</span>
          </>
        )}
      </td>
      <td className="num">{d.alerts_expected_at_baseline == null ? '—' : fmt(d.alerts_expected_at_baseline)}</td>
    </tr>
  );
}
