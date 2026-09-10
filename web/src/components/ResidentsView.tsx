import { useEffect, useMemo, useState, type ChangeEvent } from 'react';
import {
  ArrowCounterClockwise, Camera, CheckCircle, CircleNotch, ClockCounterClockwise,
  Crosshair, MapPin, Translate, WarningCircle,
} from '@phosphor-icons/react';
import ListenButton from './ListenButton';
import {
  band, fetchMap, fetchResidents, fmtLong, LANGS, postReport,
  type PhotoAnalysis, type Residents, type Station,
} from '../lib/data';
import { bandKey, inkOn } from '../lib/plain';

/**
 * The resident view.
 *
 * Built for someone who has never heard of PM2.5: how bad the air is, what to do,
 * and why, in their own language, with the advice read aloud for anyone who would
 * rather listen. Every word comes from /residents, translated in one batch, so a
 * Hindi speaker never meets an English heading.
 *
 * The photo report is corroborating evidence only, and the page says so. A
 * resident should know their photo cannot change a reading or trigger an alert.
 */

const LANG_KEY = 'vayusetu-lang';
const DEMO_SPOT = { lat: 28.6315, lon: 77.2167 }; // Connaught Place, central Delhi
const NEAR_KM = 25;

type Spot = { lat: number; lon: number; demo: boolean };
type Report =
  | { step: 'idle' }
  | { step: 'checking' }
  | { step: 'ok'; analysis: PhotoAnalysis }
  | { step: 'bad'; message: string; detail?: string };

const initialLang = () => {
  try {
    const saved = localStorage.getItem(LANG_KEY);
    if (saved && LANGS.some(l => l.code === saved)) return saved;
  } catch { /* storage blocked */ }
  const device = (navigator.language || 'en').slice(0, 2);
  return LANGS.some(l => l.code === device) ? device : 'en';
};

const sessionId = () => {
  try {
    let id = sessionStorage.getItem('vayusetu-session');
    if (!id) {
      id = crypto.randomUUID();
      sessionStorage.setItem('vayusetu-session', id);
    }
    return id;
  } catch {
    return `anon-${Date.now()}`;
  }
};

const distanceKm = (a: { lat: number; lon: number }, b: { lat: number; lon: number }) => {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 12742 * Math.asin(Math.sqrt(h));
};

/**
 * Shrink to 1600 px and re-encode as JPEG. A smaller upload on a phone connection,
 * and re-encoding through a canvas drops EXIF, so the photo carries no hidden GPS
 * position or device details.
 */
async function shrink(file: File): Promise<Blob> {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bmp.width * scale);
  canvas.height = Math.round(bmp.height * scale);
  canvas.getContext('2d')!.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  bmp.close();
  return new Promise((resolve, reject) =>
    canvas.toBlob(b => (b ? resolve(b) : reject(new Error('encode failed'))), 'image/jpeg', 0.85));
}

export default function ResidentsView({ ts }: { ts: string }) {
  const [lang, setLang] = useState(initialLang);
  const [data, setData] = useState<Residents | null>(null);
  const [pending, setPending] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [stations, setStations] = useState<Station[]>([]);
  const [spot, setSpot] = useState<Spot | null>(null);
  const [locating, setLocating] = useState(false);
  const [report, setReport] = useState<Report>({ step: 'idle' });

  useEffect(() => {
    try { localStorage.setItem(LANG_KEY, lang); } catch { /* kept for this visit */ }
  }, [lang]);

  useEffect(() => {
    let cancelled = false;
    setPending(true);
    setErr(null);
    fetchResidents(ts, lang)
      .then(d => { if (!cancelled) setData(d); })
      .catch(e => { if (!cancelled) setErr(String(e?.message ?? e)); })
      .finally(() => { if (!cancelled) setPending(false); });
    return () => { cancelled = true; };
  }, [ts, lang, retry]);

  useEffect(() => {
    let cancelled = false;
    fetchMap(ts)
      .then(m => { if (!cancelled) setStations(m.stations); })
      .catch(() => { /* the nearest monitor is a nicety; the city average still shows */ });
    return () => { cancelled = true; };
  }, [ts]);

  const nearest = useMemo(() => {
    if (!spot || !stations.length) return null;
    let best: Station | null = null;
    let bestKm = Infinity;
    for (const s of stations) {
      const d = distanceKm(spot, s);
      if (d < bestKm) { best = s; bestKm = d; }
    }
    return best && bestKm <= NEAR_KM ? { station: best, km: bestKm } : null;
  }, [spot, stations]);

  if (!data) {
    if (err) {
      return (
        <div className="res">
          <div className="res-card" role="alert">
            <strong className="res-title"><WarningCircle size={24} /> Air quality could not be loaded</strong>
            <p className="note">{err}</p>
            <button type="button" className="btn btn--tonal" onClick={() => setRetry(r => r + 1)}>Try again</button>
          </div>
        </div>
      );
    }
    return (
      <div className="res" aria-busy="true">
        <div className="skeleton" style={{ height: 42, width: '80%', borderRadius: 999 }} />
        <div className="skeleton" style={{ height: 300, borderRadius: 16 }} />
        <div className="skeleton" style={{ height: 200, borderRadius: 16 }} />
      </div>
    );
  }

  const t = (key: string) => data.ui[key] ?? key;
  const value = nearest ? nearest.station.pm25 : data.reading.city_pm25;
  const b = band(value);
  const ink = inkOn(b.color);

  const locate = () => {
    if (!('geolocation' in navigator)) {
      setReport({ step: 'bad', message: t('location_denied') });
      return;
    }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      p => {
        setLocating(false);
        setReport({ step: 'idle' });
        setSpot({ lat: p.coords.latitude, lon: p.coords.longitude, demo: false });
      },
      () => {
        setLocating(false);
        setReport({ step: 'bad', message: t('location_denied') });
      },
      { timeout: 10000, maximumAge: 300000 },
    );
  };

  const onPhoto = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // so choosing the same file again still triggers
    if (!file || !spot) return;
    setReport({ step: 'checking' });

    let blob: Blob;
    try {
      blob = await shrink(file);
    } catch {
      setReport({ step: 'bad', message: t('bad_file') }); // not a decodable image
      return;
    }

    const form = new FormData();
    form.append('lat', String(spot.lat));
    form.append('lon', String(spot.lon));
    form.append('session_id', sessionId());
    form.append('file', blob, 'photo.jpg');

    let res: { status: number; body: Awaited<ReturnType<typeof postReport>>['body'] };
    try {
      res = await postReport(form);
    } catch {
      setReport({ step: 'bad', message: t('busy') }); // network failure, not a bad photo
      return;
    }

    const { status, body } = res;
    if (status >= 500 || !body) {
      setReport({ step: 'bad', message: t('busy') });
      return;
    }
    if (!body.is_valid) {
      const r = body.rejection_reason ?? '';
      setReport({
        step: 'bad',
        message: r === 'geotag_outside_bbox' ? t('outside_area')
          : r.includes('rate_limit') ? t('rate_limited')
          : r === 'file_too_large' || r === 'invalid_content_type' ? t('bad_file')
          : t('not_used'),
      });
      return;
    }
    const a = body.gemini_analysis;
    if (!a) {
      setReport({ step: 'bad', message: t('busy') });
      return;
    }
    if (!a.is_valid_outdoor_photo) {
      setReport({ step: 'bad', message: t('not_used'), detail: t(`rejected_${a.rejection_reason ?? 'other'}`) });
      return;
    }
    setReport({ step: 'ok', analysis: a });
  };

  return (
    <div className="res" lang={data.lang}>
      <div className="res-langs" role="group" aria-label="Language">
        <Translate size={22} aria-hidden="true" />
        {LANGS.map(l => (
          <button
            key={l.code}
            type="button"
            lang={l.code}
            className="lang-chip"
            aria-pressed={lang === l.code}
            onClick={() => setLang(l.code)}
          >
            {l.label}
          </button>
        ))}
        {pending && <CircleNotch size={20} className="spin" aria-hidden="true" />}
      </div>

      <section className="res-card res-hero fade" style={{ background: b.color, color: ink }} aria-labelledby="res-level">
        <p className="res-kicker"><ClockCounterClockwise size={16} /> {t('past_event')}: {fmtLong(ts, data.lang)}</p>
        <p className="res-eyebrow">{t('air_now')}</p>
        <h1 id="res-level" className="res-band">{t(bandKey(b.name))}</h1>
        <p className="res-number"><span className="num">{value.toFixed(0)}</span> µg/m³ PM2.5</p>
        <p className="res-place">
          <MapPin size={17} />
          {nearest
            ? `${t('nearest_monitor')}: ${nearest.station.name} (${nearest.km.toFixed(1)} km)`
            : t('city_average')}
        </p>
        <p className="res-health"><strong>{t('health')}:</strong> {data.health[b.name]}</p>
        {data.translated && <p className="res-translated"><Translate size={15} /> {t('translated_note')}</p>}
      </section>

      <section className="res-card" aria-labelledby="res-do">
        <h2 id="res-do" className="res-title">{t('what_to_do')}</h2>
        {data.advisory && <p className="res-advice">{data.advisory}</p>}
        <div>
          <ListenButton ts={ts} lang={data.lang} listen={t('listen')} stop={t('stop')} unavailable={t('audio_unavailable')} />
        </div>
        <ul className="res-tips">
          {(data.tips[b.name] ?? []).map((tip, i) => (
            <li key={i}><CheckCircle size={22} weight="fill" />{tip}</li>
          ))}
        </ul>
      </section>

      <section className="res-card" aria-labelledby="res-why">
        <h2 id="res-why" className="res-title">{t('why')}</h2>
        <ul className="res-why">
          {data.why.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
        <p className="note">{t('why_note')}</p>
      </section>

      <section className="res-card" aria-labelledby="res-report">
        <h2 id="res-report" className="res-title"><Camera size={24} /> {t('report_title')}</h2>
        <p className="res-body">{t('report_body')}</p>
        <p className="note">{t('report_privacy')}</p>

        <div aria-live="polite">
          {report.step === 'checking' && (
            <div className="res-result">
              <strong><CircleNotch size={20} className="spin" /> {t('checking')}</strong>
            </div>
          )}

          {report.step === 'ok' && (
            <div className="res-result res-result--ok">
              <strong><CheckCircle size={22} weight="fill" /> {t('thanks')}</strong>
              <dl className="res-facts">
                {report.analysis.sky_condition && (
                  <>
                    <dt>{t('haze_level')}</dt>
                    <dd>
                      {t(`sky_${report.analysis.sky_condition}`)}
                      {report.analysis.haze_severity != null && (
                        <span className="num"> ({report.analysis.haze_severity}/5)</span>
                      )}
                    </dd>
                  </>
                )}
                {report.analysis.estimated_visibility_km != null && (
                  <>
                    <dt>{t('visibility')}</dt>
                    <dd><span className="num">{report.analysis.estimated_visibility_km.toFixed(1)}</span> km</dd>
                  </>
                )}
                {report.analysis.visible_sources.length > 0 && (
                  <>
                    <dt>{t('sources_seen')}</dt>
                    <dd>{report.analysis.visible_sources.map(s => t(`src_${s}`)).join(', ')}</dd>
                  </>
                )}
              </dl>
              <p>{t('adds_weight')}</p>
              <button type="button" className="btn btn--tonal" onClick={() => setReport({ step: 'idle' })}>
                <ArrowCounterClockwise size={18} /> {t('try_another')}
              </button>
            </div>
          )}

          {report.step === 'bad' && (
            <div className="res-result res-result--bad">
              <strong><WarningCircle size={22} weight="fill" /> {report.message}</strong>
              {report.detail && <p>{report.detail}</p>}
              <button type="button" className="btn btn--tonal" onClick={() => setReport({ step: 'idle' })}>
                <ArrowCounterClockwise size={18} /> {t('try_another')}
              </button>
            </div>
          )}

          {report.step === 'idle' && !spot && (
            <div className="res-actions">
              <button type="button" className="btn btn--tonal" onClick={locate} disabled={locating}>
                {locating ? <CircleNotch size={18} className="spin" /> : <Crosshair size={18} />}
                {t('use_my_location')}
              </button>
              <button type="button" className="btn btn--tonal" onClick={() => setSpot({ ...DEMO_SPOT, demo: true })}>
                <MapPin size={18} /> {t('use_demo_location')}
              </button>
              <p className="note">{t('location_note')}</p>
            </div>
          )}

          {report.step === 'idle' && spot && (
            <div className="res-actions">
              <label className="btn btn--primary file-btn">
                <Camera size={20} /> {t('choose_photo')}
                <input type="file" accept="image/*" className="sr-only" onChange={onPhoto} />
              </label>
              <span className="note">
                <MapPin size={15} /> {spot.demo ? t('location_demo_set') : t('location_mine_set')}
              </span>
              <button type="button" className="btn btn--text" onClick={() => setSpot(null)}>
                {t('change_location')}
              </button>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
