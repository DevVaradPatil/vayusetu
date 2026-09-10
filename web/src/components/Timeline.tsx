import { useMemo, useState, type KeyboardEvent } from 'react';
import { ChartBar } from '@phosphor-icons/react';
import { bandColor, istDate, type Day } from '../lib/data';

/**
 * Daily PM2.5 against the fires that explain it.
 *
 * The product's central argument in one picture: the tall bars line up with the
 * fire spikes. Each bar is an Indian calendar day, and picking one re-runs the
 * whole analysis for it, so a sceptical viewer can test the claim on a day we did
 * not choose. Bars are keyboard-operable, not only clickable.
 *
 * Hand-drawn SVG rather than a charting library: two series and one interaction.
 */

const W = 1000;
const H = 210;
const PAD = { top: 16, right: 46, bottom: 34, left: 42 };

const dayLabel = (iso: string) =>
  new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' })
    .format(new Date(`${iso}T00:00:00Z`));

interface Props {
  days: Day[];
  selected: string;
  onSelect: (isoDate: string) => void;
  loading: boolean;
}

export default function Timeline({ days, selected, onSelect, loading }: Props) {
  const [hover, setHover] = useState<number | null>(null);

  const { maxPm, maxFire, plotH, step } = useMemo(() => {
    const plotW = W - PAD.left - PAD.right;
    return {
      maxPm: Math.max(...days.map(d => d.pm25 ?? 0), 100),
      maxFire: Math.max(...days.map(d => d.upwind_fires), 1),
      plotH: H - PAD.top - PAD.bottom,
      step: plotW / Math.max(days.length, 1),
    };
  }, [days]);

  if (loading && !days.length) {
    return <div className="skeleton" style={{ height: H + 36, marginTop: 10 }} />;
  }
  if (!days.length) {
    return (
      <div className="chart-empty">
        <ChartBar size={26} />
        <span>No days to show</span>
      </div>
    );
  }

  const x = (i: number) => PAD.left + i * step + step / 2;
  const yPm = (v: number) => PAD.top + plotH - (v / maxPm) * plotH;
  const yFire = (v: number) => PAD.top + plotH - (v / maxFire) * plotH * 0.62;

  const firePath = days
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${yFire(d.upwind_fires).toFixed(1)}`)
    .join(' ');

  const selectedIdx = days.findIndex(d => d.date === istDate(selected));
  const active = hover ?? selectedIdx;
  const activeDay = active >= 0 ? days[active] : null;

  const onKey = (e: KeyboardEvent, date: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onSelect(date);
    }
  };

  return (
    <div className="chart">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="group"
        aria-label="Daily PM2.5 and fires upwind. Choose a day to see its explanation."
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75, 1].map(f => (
          <g key={f}>
            <line className="chart-grid" x1={PAD.left} x2={W - PAD.right} y1={yPm(maxPm * f)} y2={yPm(maxPm * f)} />
            <text className="chart-axis" x={PAD.left - 8} y={yPm(maxPm * f) + 4} textAnchor="end">
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
              className="chart-bar"
              role="button"
              tabIndex={0}
              aria-pressed={isSel}
              aria-label={`${dayLabel(d.date)}: PM2.5 ${v.toFixed(0)}, ${d.upwind_fires.toFixed(0)} fires upwind`}
              onMouseEnter={() => setHover(i)}
              onFocus={() => setHover(i)}
              onBlur={() => setHover(null)}
              onClick={() => onSelect(d.date)}
              onKeyDown={e => onKey(e, d.date)}
            >
              <rect
                x={PAD.left + i * step} y={PAD.top} width={step} height={plotH}
                fill="transparent" className={isSel ? 'chart-sel' : isHov ? 'chart-hov' : undefined}
              />
              <rect
                x={x(i) - step * 0.3} y={yPm(v)} width={step * 0.6} height={h} rx={3}
                fill={bandColor(v)} opacity={isSel || isHov ? 1 : 0.82}
              />
              {isSel && (
                <rect
                  className="chart-sel-ring"
                  x={x(i) - step * 0.3 - 2.5} y={yPm(v) - 2.5}
                  width={step * 0.6 + 5} height={h + 5} rx={5}
                />
              )}
            </g>
          );
        })}

        <path className="chart-fire-line" d={firePath} />
        {days.map((d, i) => (
          <circle key={d.date} className="chart-fire-dot" cx={x(i)} cy={yFire(d.upwind_fires)} r={i === active ? 4 : 2.2} />
        ))}

        {days.map((d, i) => {
          const newMonth = i === 0 || d.date.slice(5, 7) !== days[i - 1].date.slice(5, 7);
          return (
            <g key={d.date}>
              {(i % 2 === 0 || i === selectedIdx) && (
                <text
                  className={`chart-axis${i === selectedIdx ? ' chart-axis--sel' : ''}`}
                  x={x(i)} y={H - 18} textAnchor="middle"
                >
                  {Number(d.date.slice(8))}
                </text>
              )}
              {newMonth && (
                <text className="chart-axis" x={x(i)} y={H - 3} textAnchor="middle">
                  {dayLabel(d.date).split(' ')[1]}
                </text>
              )}
            </g>
          );
        })}

        <text className="chart-axis chart-axis--fire" x={W - PAD.right + 8} y={PAD.top + 8}>fires</text>
        <text className="chart-axis" x={PAD.left - 8} y={PAD.top - 5} textAnchor="end">µg/m³</text>
      </svg>

      {activeDay && (
        <div
          className="chart-tip"
          // Clamped so the first and last day's tooltip stays inside the panel.
          style={{ left: `${Math.min(Math.max(((active + 0.5) / days.length) * 100, 14), 86)}%` }}
        >
          <strong>{dayLabel(activeDay.date)}</strong>
          <span>PM2.5 <b className="num">{activeDay.pm25?.toFixed(0) ?? '-'}</b></span>
          <span>Fires <b className="num">{activeDay.upwind_fires.toFixed(0)}</b></span>
          <span>Air ceiling <b className="num">{activeDay.blh?.toFixed(0) ?? '-'}</b> m</span>
        </div>
      )}
    </div>
  );
}
