import { useEffect, useState } from 'react';
import { CheckCircle, Crosshair, MapPin, Users } from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import { band, fetchTopEvents, fmtLong, type Hotspot, type HotspotHour } from '../lib/data';
import { EXPLAIN, inkOn } from '../lib/plain';

/**
 * Hyper-local events: one locality far above the monitors around it.
 *
 * The empty state carries as much meaning as the full one. During a regional
 * episode every monitor is severe together, so there is no local outlier and the
 * honest answer is "none" — but a reader seeing an empty table assumes the feature
 * is broken. So when nothing is flagged the panel says why, and offers the hours in
 * this window where events did happen, each one a button that moves the whole page
 * to that hour.
 */

interface Props {
  hours: HotspotHour | null;
  loading: boolean;
  onTs: (ts: string) => void;
}

/** '2025-11-16 06:00:00' (UTC, from the API) -> an ISO instant the page can use. */
const isoOf = (ts: string) => `${ts.replace(' ', 'T')}Z`;

export default function Hotspots({ hours, loading, onTs }: Props) {
  const [top, setTop] = useState<Hotspot[] | null>(null);
  const none = !loading && !!hours && hours.hotspots.length === 0;

  // Only fetched when the panel actually needs it: on an hour with events, the
  // window list is never shown.
  useEffect(() => {
    if (!none || top) return;
    // Confirmed events only, one per locality: the list is "where to look next", and six
    // rows of the same monitor on consecutive hours would bury every other place.
    fetchTopEvents(40)
      .then(d => {
        const seen = new Set<string>();
        setTop(d.events.filter(e => e.confirmed && !seen.has(e.station_id) && seen.add(e.station_id)).slice(0, 6));
      })
      .catch(() => setTop([]));
  }, [none, top]);

  return (
    <section className="panel panel-pad" aria-labelledby="hotspots-title">
      <h2 id="hotspots-title" className="section-title">
        <Crosshair size={20} /> Hyper-local events
        <InfoTip label="What is a hyper-local event?">{EXPLAIN.hotspot}</InfoTip>
      </h2>
      <p className="section-sub">
        A single locality breathing far worse air than everywhere around it. The city average
        hides these: one neighbourhood can sit at four times the number the region reports.
      </p>

      {loading && <div className="skeleton" style={{ height: 92 }} />}

      {!loading && hours && hours.hotspots.length > 0 && (
        <>
          <div className="hs-grid fade">
            {hours.hotspots.map(h => <Card key={h.station_id} h={h} />)}
          </div>
          <p className="chart-note">
            Compared against a regional middle of {hours.regional_median?.toFixed(0)} µg/m³ across{' '}
            {hours.n_reporting} monitors reporting this hour.
          </p>
        </>
      )}

      {!loading && hours && hours.excluded_as_sensor_fault.length > 0 && (
        <div className="hs-excluded fade">
          <strong>Not counted: {hours.excluded_as_sensor_fault.length === 1 ? 'one reading' : `${hours.excluded_as_sensor_fault.length} readings`} from a faulty monitor.</strong>{' '}
          {hours.excluded_as_sensor_fault.map(f => `${f.name.replace(/ - [A-Z]+$/, '')} read ${f.pm25.toFixed(0)}`).join('; ')}
          {' '}— but the instrument was misbehaving within three hours of that reading, so it raises no
          hotspot and no alert. See Monitors for the evidence.
        </div>
      )}

      {none && (
        <div className="hs-none fade">
          {(hours.regional_median ?? 0) >= 250 ? (
            <p>
              <strong>No local event this hour — the whole region is affected at once.</strong>{' '}
              All {hours.n_reporting} monitors read badly together, around{' '}
              {hours.regional_median?.toFixed(0)} µg/m³, so no single locality stands out. That
              needs a region-wide response, not an inspection team sent to one address.
            </p>
          ) : (
            <p>
              <strong>No local event this hour.</strong> No trusted monitor stands far above the
              regional middle of {hours.regional_median?.toFixed(0)} µg/m³.
            </p>
          )}
          {top === null && <div className="skeleton" style={{ height: 60, marginTop: 12 }} />}
          {top && top.length > 0 && (
            <>
              <h3 className="hs-sub">The sharpest confirmed local events in these four weeks</h3>
              <ul className="hs-list">
                {top.map(e => (
                  <li key={`${e.ts}-${e.station_id}`}>
                    <button type="button" className="hs-jump" onClick={() => onTs(isoOf(e.ts!))}>
                      <span className="hs-jump-where">
                        <MapPin size={15} /> {e.name.replace(/ - [A-Z]+$/, '')}
                      </span>
                      <span className="hs-jump-num num">{e.pm25.toFixed(0)}</span>
                      <span className="hs-jump-vs">
                        vs {e.regional_median?.toFixed(0)} around it · {e.times_regional}× · lasted{' '}
                        {e.persistent_hours} h · {fmtLong(isoOf(e.ts!))}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </section>
  );
}

function Card({ h }: { h: Hotspot }) {
  const b = band(h.pm25);
  return (
    <article className="hs-card">
      <div className="hs-card-head">
        <span className="band-pill" style={{ background: b.color, color: inkOn(b.color) }}>{b.name}</span>
        {h.times_regional && <span className="hs-mult num">{h.times_regional}× the area around it</span>}
        {h.confirmed ? (
          <span className="hs-confirm hs-confirm--yes"><CheckCircle size={14} weight="fill" /> Confirmed · {h.persistent_hours} h</span>
        ) : (
          <span className="hs-confirm hs-confirm--no">One hour only — not confirmed, no alert</span>
        )}
      </div>
      <h3 className="hs-name">{h.name.replace(/ - [A-Z]+$/, '')}</h3>
      <div className="hs-value">
        <span className="num">{h.pm25.toFixed(0)}</span>
        <span className="stat-unit">µg/m³ PM2.5</span>
      </div>
      <ul className="hs-facts">
        <li>
          <strong className="num">+{h.excess_over_median.toFixed(0)}</strong> µg/m³ above the
          monitors around it
        </li>
        {h.population_in_cell != null && (
          <li>
            <Users size={14} /> about <strong className="num">{h.population_in_cell.toLocaleString('en-IN')}</strong>{' '}
            people live in this square kilometre
          </li>
        )}
      </ul>
    </article>
  );
}
