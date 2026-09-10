import { useEffect, useState } from 'react';
import { SealCheck, Translate, WarningCircle } from '@phosphor-icons/react';
import InfoTip from './InfoTip';
import ListenButton from './ListenButton';
import { fetchAdvisory, LANGS, type Brief, type Evidence } from '../lib/data';
import { CAUSE_LABEL, citation, confidenceWord, EXPLAIN } from '../lib/plain';

/**
 * Why the air is bad, and what should be done.
 *
 * The measurement chips are the point of this panel. Each one is a field that
 * exists in the evidence, checked in code before the explanation was allowed out
 * of the API, shown the way a person would say it ("Air ceiling: 65 m") with the
 * raw data field one hover away for anyone auditing it.
 */

const URGENCY_LABEL: Record<string, string> = {
  immediate: 'Act now',
  high: 'High priority',
  medium: 'Medium priority',
  low: 'Low priority',
};

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
      <div className="brief" aria-busy="true">
        <div className="skeleton" style={{ height: 24, width: '50%' }} />
        <div className="skeleton" style={{ height: 70 }} />
        <div className="skeleton" style={{ height: 96 }} />
      </div>
    );
  }

  if (!brief) {
    return (
      <div className="error-box" role="alert">
        <WarningCircle size={24} />
        <div>
          <strong>No explanation for this hour</strong>
          <p>
            The AI explanation could not be checked against the measurements, so it is
            not shown. We never show an explanation we could not verify.
          </p>
          {briefError && <p className="note">{briefError}</p>}
        </div>
      </div>
    );
  }

  const conf = Math.round(brief.confidence * 100);

  return (
    <div className="brief rise">
      <div>
        <h2 className="section-title">Why is the air bad?</h2>
        <p className="section-sub">An AI explanation, checked against the measurements.</p>
        <div className="chip-row" style={{ marginTop: 12 }}>
          <span className="chip chip--primary">
            Main cause: {CAUSE_LABEL[brief.cause_category] ?? brief.cause_category}
          </span>
          <span className="chip chip--quiet">
            Confidence: {confidenceWord(brief.confidence)} <span className="num">({conf}%)</span>
            <InfoTip label="What does confidence mean?">{EXPLAIN.confidence}</InfoTip>
          </span>
          {brief.verified && (
            <span className="chip chip--success">
              <SealCheck size={15} weight="fill" /> Checked against data
              <InfoTip label="How was this checked?">{EXPLAIN.checked}</InfoTip>
            </span>
          )}
        </div>
        <p className="cause">{brief.cause}</p>
        <p className="narrative">{brief.narrative}</p>
      </div>

      <section>
        <h3 className="label">Based on these measurements</h3>
        <ul className="cite-list">
          {brief.evidence_cited.map(path => {
            const c = citation(path, ev);
            return (
              <li key={path} className="cite-chip" title={`Data field: ${path}`}>
                <span className="cite-label">{c.label}</span>
                <span className="num">{c.value}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h3 className="label">What should be done</h3>
        <ul className="actions">
          {brief.recommended_actions.map((a, i) => (
            <li key={i} className="action">
              <span className={`urgency urgency--${a.urgency}`}>{URGENCY_LABEL[a.urgency] ?? a.urgency}</span>
              <div>
                <strong>{a.actor}</strong>
                <p>{a.action}</p>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="label">Advice for the public</h3>
        <div className="lang-row" role="group" aria-label="Advice language">
          {LANGS.map(l => (
            <button
              key={l.code}
              type="button"
              lang={l.code}
              className="lang-chip"
              aria-pressed={lang === l.code}
              onClick={() => pick(l.code)}
            >
              {l.label}
            </button>
          ))}
        </div>
        <div className="advisory">
          {translating
            ? <span className="skeleton" style={{ display: 'block', height: 20, width: '80%' }} />
            : <p lang={advisory?.translated ? lang : 'en'}>{advisory?.text}</p>}
        </div>
        <div className="advisory-foot">
          <ListenButton ts={ts} lang={lang} />
          {!translating && lang !== 'en' && advisory?.translated && (
            <span className="note"><Translate size={15} /> Translated automatically</span>
          )}
          {!translating && lang !== 'en' && advisory && !advisory.translated && (
            <span className="note">Translation is not available right now, so this is in English.</span>
          )}
        </div>
      </section>

      {brief.caveats.length > 0 && (
        <details className="limits">
          <summary>Limits of this analysis</summary>
          <ul>{brief.caveats.map((c, i) => <li key={i}>{c}</li>)}</ul>
        </details>
      )}

      <p className="brief-foot">
        Explanation by <span className="num">{brief.model}</span>. Numbers from government air
        monitors, NASA fire satellites and weather records.
      </p>
    </div>
  );
}
