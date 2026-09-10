import { Broadcast, CalendarBlank, Compass, Fire } from '@phosphor-icons/react';

/**
 * "How to read this page", for anyone who has never seen an air quality map.
 * Shown on first visit, dismissed once, and reachable again from the summary.
 */
export default function Guide({ onClose }: { onClose: () => void }) {
  return (
    <section className="panel guide rise" aria-labelledby="guide-title">
      <h2 id="guide-title" className="section-title">How to read this page</h2>
      <ul className="guide-items">
        <li className="guide-item">
          <span className="guide-icon"><Broadcast size={22} /></span>
          <div>
            <strong>Circles are air monitors</strong>
            <p>Colour shows how polluted the air is, from green for good to dark red for severe. Bigger circles mean higher readings. Tap one to see it.</p>
          </div>
        </li>
        <li className="guide-item">
          <span className="guide-icon"><Fire size={22} /></span>
          <div>
            <strong>Orange dots are fires</strong>
            <p>Spotted from space by NASA satellites over the last two days, mostly crop and waste burning.</p>
          </div>
        </li>
        <li className="guide-item">
          <span className="guide-icon"><Compass size={22} /></span>
          <div>
            <strong>The blue fan shows the wind</strong>
            <p>It points to where the wind is blowing from. Fires inside the fan can carry smoke towards the city.</p>
          </div>
        </li>
        <li className="guide-item">
          <span className="guide-icon"><CalendarBlank size={22} /></span>
          <div>
            <strong>Check any other day</strong>
            <p>The chart at the bottom covers four weeks. Pick a day to see what caused the pollution then.</p>
          </div>
        </li>
      </ul>
      <button type="button" className="btn btn--primary" onClick={onClose}>Got it</button>
    </section>
  );
}
