import { useEffect, useState } from 'react';

/**
 * Light, dark, or follow the system.
 *
 * The attribute on <html> is set synchronously when the user clicks, not in an
 * effect. React runs child effects before parent effects, so a theme applied in
 * an effect up here would still be the old one when the map (a child) reads its
 * colours. index.html applies the saved choice before first paint for the same
 * reason: no flash of the wrong theme on load.
 */

export type ThemePref = 'system' | 'light' | 'dark';
const KEY = 'vayusetu-theme';

const readPref = (): ThemePref => {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
};

/**
 * Make every element re-read the theme tokens.
 *
 * Changing the attribute on <html> updates the custom properties, but in the
 * Chromium this was tested in, the properties that use them (background: var(...))
 * were not re-resolved: the body and every panel kept the old theme until
 * something forced a fresh style pass. A plain wait and a stylesheet re-parse did
 * not fix it; toggling display did. It costs one synchronous reflow on a click,
 * nothing paints in between, and the scroll position is put back.
 */
const restyle = () => {
  const { scrollX, scrollY } = window;
  const body = document.body;
  body.style.display = 'none';
  void body.offsetHeight;
  body.style.display = '';
  window.scrollTo(scrollX, scrollY);
};

const applyPref = (p: ThemePref) => {
  const root = document.documentElement;
  if (p === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', p);
  restyle();
  try {
    if (p === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, p);
  } catch {
    /* storage blocked: the choice lasts for this visit only */
  }
};

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>(readPref);
  const [systemDark, setSystemDark] = useState(
    () => window.matchMedia('(prefers-color-scheme: dark)').matches,
  );

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const cycle = () => {
    const next: ThemePref = pref === 'system' ? 'light' : pref === 'light' ? 'dark' : 'system';
    applyPref(next);
    setPref(next);
  };

  const resolved: 'light' | 'dark' = pref === 'system' ? (systemDark ? 'dark' : 'light') : pref;
  return { pref, resolved, cycle };
}

/** A CSS custom property's current value, for colours drawn outside CSS (map overlays). */
export const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
