import { useMemo, useState } from 'react';
import { ChartBar } from '@phosphor-icons/react';
import { bandColor, type Day } from '../lib/data';

/**
 * Daily PM2.5 against the two drivers that explain it.
 *
 * This chart is the product's central argument in one picture: the tall bars line
 * up with the fire spikes and with the boundary layer collapsing. Clicking a day
 * re-runs the whole analysis for it, so a sceptical viewer can test the claim on a
 * day we did not choose.
 *
 * Hand-drawn SVG rather than a charting library: two series, one interaction, and
 * a dependency would cost more than it saves.
 */

const W = 1000;
const H = 210;
const PAD = { top: 16, right: 44, bottom: 26, left: 40 };

interface Props {
  days: Day[];
  selected: string;
  onSelect: (isoDate: string) => void;
  loading: boolean;
}

export default function Timeline({ days, selected, onSelect, loading }: Props) {
  const [hover, setHover] = useState<number | null>(null);

  const { maxPm, maxFire, plotW, plotH, step } = useMemo(() => {
    const maxPm = Math.max(...days.map(d => d.pm25 ?? 0), 100);
    const maxFire = Math.max(...days.map(d => d.upwind_fires), 1);
    const plotW = W - PAD.left - PAD.right;
    const plotH = H - PAD.top - PAD.bottom;
    return { maxPm, maxFire, plotW, plotH, step: plotW / Math.max(days.length, 1) };
  }, [days]);

  if (loading && !days.length) {
    return <div className="skeleton" style={{ height: H, borderRadius: 'var(--r-small)' }} />;
  }
  if (!days.length) {
    return (
      <div style={empty}>
        <ChartBar size={26} color="var(--on-surface-dim)" />
        <div style={{ marginTop: 8 }}>No days in this window</div>
      </div>
    );
  }

  const x = (i: number) => PAD.left + i * step + step / 2;
  const yPm = (v: number) => PAD.top + plotH - (v / maxPm) * plotH;
  const yFire = (v: number) => PAD.top + plotH - (v / maxFire) * plotH * 0.62;

  const firePath = days
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${yFire(d.upwind_fires).toFixed(1)}`)
    .join(' ');

  const selectedIdx = days.findIndex(d => selected.startsWith(d.date));
  const active = hover ?? selectedIdx;
  const activeDay = active >= 0 ? days[active] : null;

  return (
    <div style={{ position: 'relative', paddingTop: 28 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: H, display: 'block', overflow: 'visible' }}
        role="img"
        aria-label="Daily mean PM2.5 with upwind fire count, one bar per day"
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75, 1].map(f => (
          <g key={f}>
            <line
              x1={PAD.left} x2={W - PAD.right}
              y1={yPm(maxPm * f)} y2={yPm(maxPm * f)}
              stroke="var(--outline-variant)" strokeWidth={1}
            />
            <text
              x={PAD.left - 8} y={yPm(maxPm * f) + 4}
              textAnchor="end" fontSize={10} fill="var(--on-surface-dim)" className="num"
            >
              {Math.round(maxPm * f)}
            </text>
          </g>
        ))}

        {days.map((d, i) => {
          const v = d.pm25 ?? 0;
          const h = Math.max((v / maxPm) * plotH, 2);
          const isSel = i === selectedIdx;
          const isHov = i === hover;
          return (
            <g
              key={d.date}
              onMouseEnter={() => setHover(i)}
              onClick={() => onSelect(`${d.date}T20:00:00Z`)}
              style={{ cursor: 'pointer' }}
            >
              <rect
                x={PAD.left + i * step} y={PAD.top}
                width={step} height={plotH}
                fill={isSel ? 'rgb(168 199 250 / 0.1)' : isHov ? 'rgb(255 255 255 / 0.04)' : 'transparent'}
              />
              <rect
                x={x(i) - step * 0.3} y={yPm(v)}
                width={step * 0.6} height={h}
                rx={3}
                fill={bandColor(v)}
                opacity={isSel || isHov ? 1 : 0.78}
                style={{ transition: 'opacity var(--dur-short) var(--ease)' }}
              />
              {isSel && (
                <rect
                  x={x(i) - step * 0.3 - 2} y={yPm(v) - 2}
                  width={step * 0.6 + 4} height={h + 4}
                  rx={5} fill="none" stroke="var(--primary)" strokeWidth={1.5}
                />
              )}
            </g>
          );
        })}

        <path d={firePath} fill="none" stroke="var(--fire)" strokeWidth={1.75}
              strokeLinejoin="round" opacity={0.85} />
        {days.map((d, i) => (
          <circle key={d.date} cx={x(i)} cy={yFire(d.upwind_fires)} r={i === active ? 3.5 : 2}
                  fill="var(--fire)" />
        ))}

        {days.map((d, i) => (
          i % 2 === 0 && (
            <text key={d.date} x={x(i)} y={H - 8} textAnchor="middle" fontSize={10}
                  fill={i === selectedIdx ? 'var(--primary)' : 'var(--on-surface-dim)'} className="num">
              {d.date.slice(8)}
            </text>
          )
        ))}

        <text x={W - PAD.right + 8} y={PAD.top + 8} fontSize={10} fill="var(--fire)">fires</text>
        <text x={PAD.left - 8} y={PAD.top - 4} textAnchor="end" fontSize={10}
              fill="var(--on-surface-dim)">ug/m3</text>
      </svg>

      {activeDay && (
        <div
          style={{
            ...tip,
            // Clamped so the tooltip for the first and last day stays on screen
            // instead of hanging off the edge of the panel.
            left: `${Math.min(Math.max(((active + 0.5) / days.length) * 100, 12), 88)}%`,
          }}
        >
          <strong className="num">{activeDay.date}</strong>
          <span>PM2.5 <b className="num" style={{ color: bandColor(activeDay.pm25 ?? 0) }}>
            {activeDay.pm25?.toFixed(0) ?? '-'}</b></span>
          <span>fires <b className="num" style={{ color: 'var(--fire)' }}>
            {activeDay.upwind_fires.toFixed(0)}</b></span>
          <span>layer <b className="num">{activeDay.blh?.toFixed(0) ?? '-'}</b> m</span>
        </div>
      )}
    </div>
  );
}

const tip: React.CSSProperties = {
  position: 'absolute',
  top: 0,
  transform: 'translateX(-50%)',
  display: 'flex',
  gap: 12,
  alignItems: 'baseline',
  background: 'var(--surface-container-highest)',
  border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-small)',
  padding: '6px 10px',
  fontSize: 12,
  whiteSpace: 'nowrap',
  pointerEvents: 'none',
  color: 'var(--on-surface-variant)',
  boxShadow: '0 6px 20px rgb(0 0 0 / 0.45)',
};

const empty: React.CSSProperties = {
  height: H,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  color: 'var(--on-surface-variant)',
};
