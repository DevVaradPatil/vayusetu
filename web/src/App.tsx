import { useEffect, useState } from 'react';
import { Buildings, Monitor, Moon, Sun, UsersThree, Wind } from '@phosphor-icons/react';
import OfficialsView from './components/OfficialsView';
import ResidentsView from './components/ResidentsView';
import { HERO_TS } from './lib/data';
import { useTheme } from './lib/theme';

/**
 * VayuSetu.
 *
 * Two views of the same hour. Officials get the evidence, the explanation, and who
 * should act. Residents get how bad it is, what to do, and why, in their own
 * language.
 *
 * Each view is mounted the first time it is opened and then kept, hidden, rather
 * than rebuilt on every switch: every new Google map is a billed map load, and a
 * resident's half-finished photo report should survive a look at the map.
 */

type View = 'officials' | 'residents';
const readView = (): View => (window.location.hash.startsWith('#/residents') ? 'residents' : 'officials');

const THEME_LABEL = {
  system: 'Theme follows your device',
  light: 'Light theme',
  dark: 'Dark theme',
};

export default function App() {
  const [view, setView] = useState<View>(readView);
  const [opened, setOpened] = useState<Record<View, boolean>>(() => ({
    officials: readView() === 'officials',
    residents: readView() === 'residents',
  }));
  const [ts, setTs] = useState(HERO_TS);
  const theme = useTheme();

  useEffect(() => {
    const onHash = () => {
      const v = readView();
      setView(v);
      setOpened(o => (o[v] ? o : { ...o, [v]: true }));
      window.scrollTo({ top: 0 });
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const ThemeIcon = theme.pref === 'system' ? Monitor : theme.pref === 'light' ? Sun : Moon;

  return (
    <div className="shell">
      <header className="app-bar">
        <a className="brand" href="#/">
          <span className="brand-mark"><Wind size={30} weight="bold" /></span>
          <span>
            <span className="brand-name">VayuSetu</span>
            <span className="brand-tag">Why the air is bad, and who can fix it</span>
          </span>
        </a>

        <nav className="tabs" aria-label="Views">
          <a className="tab" href="#/" aria-current={view === 'officials' ? 'page' : undefined}>
            <Buildings size={18} /> For officials
          </a>
          <a className="tab" href="#/residents" aria-current={view === 'residents' ? 'page' : undefined}>
            <UsersThree size={18} /> For residents
          </a>
        </nav>

        <button
          type="button"
          className="icon-btn"
          onClick={theme.cycle}
          aria-label={`${THEME_LABEL[theme.pref]}. Change theme.`}
          title={THEME_LABEL[theme.pref]}
        >
          <ThemeIcon size={20} />
        </button>
      </header>

      {opened.officials && (
        <div className="view" hidden={view !== 'officials'}>
          <OfficialsView ts={ts} onTs={setTs} theme={theme.resolved} />
        </div>
      )}
      {opened.residents && (
        <div className="view" hidden={view !== 'residents'}>
          <ResidentsView ts={ts} />
        </div>
      )}
    </div>
  );
}
