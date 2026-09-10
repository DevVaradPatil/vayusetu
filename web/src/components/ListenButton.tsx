import { useEffect, useRef, useState } from 'react';
import { CircleNotch, SpeakerHigh, Stop } from '@phosphor-icons/react';
import { fetchAdvisory } from '../lib/data';

/**
 * Reads the advice aloud with Cloud Text-to-Speech, for people who will not, or
 * cannot, read a screen.
 *
 * Clips are kept per hour and language: the advice for a past hour never changes,
 * so it is fetched once. Failures are not kept, so a transient error is retried.
 */
const clips = new Map<string, string>();

interface Props {
  ts: string;
  lang: string;
  listen?: string;
  stop?: string;
  unavailable?: string;
}

export default function ListenButton({
  ts, lang, listen = 'Listen', stop = 'Stop', unavailable = 'Audio is not available right now.',
}: Props) {
  const [state, setState] = useState<'idle' | 'loading' | 'playing' | 'unavailable'>('idle');
  const audio = useRef<HTMLAudioElement | null>(null);
  const request = useRef(0);

  // A new hour or language is a different sentence: stop the old one, and make
  // any fetch still in flight for it land nowhere.
  useEffect(() => {
    request.current += 1;
    setState('idle');
    return () => {
      audio.current?.pause();
      audio.current = null;
    };
  }, [ts, lang]);

  const toggle = async () => {
    if (state === 'playing') {
      audio.current?.pause();
      audio.current = null;
      setState('idle');
      return;
    }

    const mine = ++request.current;
    const key = `${ts}|${lang}`;
    setState('loading');
    try {
      let src = clips.get(key);
      if (!src) {
        const d = await fetchAdvisory(ts, lang, true);
        if (d.audio_base64) {
          src = `data:audio/mpeg;base64,${d.audio_base64}`;
          clips.set(key, src);
        }
      }
      if (mine !== request.current) return;
      if (!src) { setState('unavailable'); return; }

      const a = new Audio(src);
      a.onended = () => {
        if (audio.current === a) { audio.current = null; setState('idle'); }
      };
      audio.current = a;
      await a.play();
      if (mine === request.current) setState('playing');
    } catch {
      if (mine === request.current) setState('unavailable');
    }
  };

  return (
    <span className="listen">
      <button type="button" className="btn btn--tonal" onClick={toggle} disabled={state === 'loading'}>
        {state === 'loading'
          ? <CircleNotch size={18} className="spin" />
          : state === 'playing'
            ? <Stop size={18} weight="fill" />
            : <SpeakerHigh size={18} weight="fill" />}
        {state === 'playing' ? stop : listen}
      </button>
      {state === 'unavailable' && <span className="note" role="status">{unavailable}</span>}
    </span>
  );
}
