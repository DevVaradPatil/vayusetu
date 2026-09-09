import { useEffect, useState } from 'react';
import { WarningCircle, SealCheck } from '@phosphor-icons/react';
import {
  fetchAdvisory, LANGS, TENANT,
  type Brief, type Evidence,
} from '../lib/data';

/**
 * The attribution brief.
 *
 * The cited-measurement chips are the point of this panel. Every one of them is a
 * field that exists in the evidence payload, checked in code before the brief was
 * allowed out of the API. A reader can see exactly which numbers the conclusion
 * rests on, which is the difference between an explanation and prose that happens
 * to sit next to data.
 */

const URGENCY: Record<string, { label: string; fg: string; bg: string }> = {
  immediate: { label: 'Immediate', fg: '#fecaca', bg: 'rgb(153 27 27 / 0.55)' },
  high:      { label: 'High',      fg: '#fed7aa', bg: 'rgb(194 65 12 / 0.42)' },
  medium:    { label: 'Medium',    fg: '#fde68a', bg: 'rgb(161 98 7 / 0.38)' },
  low:       { label: 'Low',       fg: '#c5c6d0', bg: 'rgb(120 120 130 / 0.28)' },
};

const titleCase = (s: string) =>
  s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

interface Props {
  brief: Brief | null;
  briefError?: string;
  ev: Evidence | null;
  ts: string;
  loading: boolean;
}

export default function BriefPanel({ brief, briefError, ev, ts, loading }: Props) {
  const [lang, setLang] = useState('en');
  const [advisory, setAdvisory] = useState<{ text: string; translated: boolean } | null>(null);
  const [translating, setTranslating] = useState(false);

  useEffect(() => {
    setLang('en');
    setAdvisory(brief ? { text: brief.public_advisory, translated: false } : null);
  }, [brief]);

  const pick = async (code: string) => {
    setLang(code);
    if (code === 'en') {
      setAdvisory({ text: brief?.public_advisory ?? '', translated: false });
      return;
    }
    setTranslating(true);
    try {
      const d = await fetchAdvisory(ts, code);
      setAdvisory({ text: d.text, translated: d.translated });
    } catch {
      setAdvisory({ text: brief?.public_advisory ?? '', translated: false });
    } finally {
      setTranslating(false);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'grid', gap: 12 }}>
        <div className="skeleton" style={{ height: 22, width: '55%' }} />
        <div className="skeleton" style={{ height: 64 }} />
        <div className="skeleton" style={{ height: 90 }} />
      </div>
    );
  }

  if (!brief) {
    return (
      <div style={errBox}>
        <WarningCircle size={22} color="var(--error)" />
        <div>
          <div style={{ fontWeight: 500, marginBottom: 3 }}>No brief for this hour</div>
          <div style={{ color: 'var(--on-surface-variant)', fontSize: 13 }}>
            {briefError ?? 'The evidence did not pass verification.'}
          </div>
          <div style={{ color: 'var(--on-surface-dim)', fontSize: 12, marginTop: 8, lineHeight: 1.5 }}>
            A brief that cannot cite its evidence is withheld rather than shown with a
            fallback paragraph, which would be indistinguishable from a real one.
          </div>
        </div>
      </div>
    );
  }

  const conf = Math.round(brief.confidence * 100);

  return (
    <div className="rise" style={{ display: 'grid', gap: 18 }}>
      <div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          <span style={causeChip}>{titleCase(brief.cause_category)}</span>
          <span style={confChip}>
            <span className="num">{conf}%</span> confidence
          </span>
          {brief.verified && (
            <span style={verifiedChip}>
              <SealCheck size={14} weight="fill" /> evidence checked
            </span>
          )}
        </div>
        <p style={cause}>{brief.cause}</p>
        <p style={narrative}>{brief.narrative}</p>
      </div>

      <section>
        <h3 style={label}>Measurements cited</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {brief.evidence_cited.map(c => (
            <code key={c} style={citeChip}>{c}</code>
          ))}
        </div>
      </section>

      <section>
        <h3 style={label}>Recommended actions</h3>
        <div style={{ display: 'grid', gap: 8 }}>
          {brief.recommended_actions.map((a, i) => {
            const u = URGENCY[a.urgency] ?? URGENCY.low;
            return (
              <div key={i} style={actionRow}>
                <span style={{ ...urgencyPill, color: u.fg, background: u.bg }}>{u.label}</span>
                <div>
                  <div style={{ fontWeight: 500, marginBottom: 2 }}>{a.actor}</div>
                  <div style={{ color: 'var(--on-surface-variant)', fontSize: 13, lineHeight: 1.5 }}>
                    {a.action}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section>
        <h3 style={label}>Public advisory</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          {LANGS.map(l => (
            <button
              key={l.code}
              onClick={() => pick(l.code)}
              aria-pressed={lang === l.code}
              style={{ ...langChip, ...(lang === l.code ? langChipOn : {}) }}
            >
              {l.label}
            </button>
          ))}
        </div>
        <div style={advisoryBox}>
          {translating
            ? <span className="skeleton" style={{ display: 'block', height: 19, width: '80%' }} />
            : <span lang={lang}>{advisory?.text}</span>}
        </div>
        {advisory && lang !== 'en' && !advisory.translated && !translating && (
          <div style={note}>
            Translation unavailable, showing English. The advisory is never labelled as
            translated when it is not.
          </div>
        )}
      </section>

      {(brief.caveats.length > 0 || (ev?.missing_fields.length ?? 0) > 0) && (
        <section>
          <h3 style={label}>Caveats</h3>
          <ul style={caveatList}>
            {brief.caveats.map((c, i) => <li key={i} style={{ marginBottom: 4 }}>{c}</li>)}
          </ul>
        </section>
      )}

      <div style={footer}>
        Reasoning by <span className="num">{brief.model}</span> over measured evidence.
      </div>
    </div>
  );
}

const cause: React.CSSProperties = {
  margin: '0 0 10px', fontSize: 19, lineHeight: 1.35, fontWeight: 500, letterSpacing: '-0.01em',
};
const narrative: React.CSSProperties = {
  margin: 0, fontSize: 14, lineHeight: 1.62, color: 'var(--on-surface-variant)',
};
const label: React.CSSProperties = {
  margin: '0 0 8px', fontSize: 11, fontWeight: 500, letterSpacing: '0.08em',
  textTransform: 'uppercase', color: 'var(--on-surface-dim)',
};
const chipBase: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5,
  borderRadius: 'var(--r-pill)', padding: '5px 11px', fontSize: 12, lineHeight: 1.3,
};
const causeChip: React.CSSProperties = {
  ...chipBase, background: 'var(--primary-container)', color: 'var(--on-primary-container)',
  fontWeight: 500,
};
const confChip: React.CSSProperties = {
  ...chipBase, background: 'var(--surface-container-high)', color: 'var(--on-surface-variant)',
};
const verifiedChip: React.CSSProperties = {
  ...chipBase, background: 'rgb(34 197 94 / 0.14)', color: '#86efac',
};
const citeChip: React.CSSProperties = {
  fontFamily: 'var(--font-mono)', fontSize: 11.5,
  background: 'var(--surface-container-high)', color: 'var(--on-surface-variant)',
  border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-small)', padding: '3px 8px',
};
const actionRow: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 12, alignItems: 'start',
  background: 'var(--surface-container-low)', border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-small)', padding: '11px 13px',
};
const urgencyPill: React.CSSProperties = {
  ...chipBase, fontSize: 11, fontWeight: 500, padding: '3px 9px', whiteSpace: 'nowrap',
};
const langChip: React.CSSProperties = {
  ...chipBase, cursor: 'pointer', font: 'inherit', fontSize: 12.5,
  background: 'transparent', color: 'var(--on-surface-variant)',
  border: '1px solid var(--outline-variant)',
  transition: 'background var(--dur-short) var(--ease), color var(--dur-short) var(--ease)',
};
const langChipOn: React.CSSProperties = {
  background: 'var(--primary-container)', color: 'var(--on-primary-container)',
  borderColor: 'transparent', fontWeight: 500,
};
const advisoryBox: React.CSSProperties = {
  background: 'var(--surface-container-low)', border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-small)', padding: '13px 15px', fontSize: 15, lineHeight: 1.6,
  minHeight: 46,
};
const note: React.CSSProperties = {
  marginTop: 7, fontSize: 12, color: 'var(--on-surface-dim)', lineHeight: 1.5,
};
const caveatList: React.CSSProperties = {
  margin: 0, paddingLeft: 17, fontSize: 12.5, lineHeight: 1.55, color: 'var(--on-surface-dim)',
};
const footer: React.CSSProperties = {
  fontSize: 12, color: 'var(--on-surface-dim)', borderTop: '1px solid var(--outline-variant)',
  paddingTop: 12,
};
const errBox: React.CSSProperties = {
  display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 12, alignItems: 'start',
  background: 'var(--surface-container-low)', border: '1px solid var(--outline-variant)',
  borderRadius: 'var(--r-small)', padding: 16,
};
