import { useEffect, useRef, useState } from 'react';
import { MapTrifold } from '@phosphor-icons/react';
import { band, MAPS_KEY, type Evidence, type MapData } from '../lib/data';
import { inkOn } from '../lib/plain';
import { token } from '../lib/theme';

/**
 * The real map.
 *
 * Everything drawn here is observed: monitors where they physically stand, fire
 * detections where NASA saw them, and the wind fan as true geodesic geometry
 * rather than a triangle drawn in screen space. That matters, because the fan is
 * the claim the explanation rests on: these fires, and not those, could have
 * reached this monitor.
 *
 * The Maps JS API is loaded directly. Every overlay is a raw google.maps object,
 * so a React wrapper would only add script loading and a container div.
 *
 * Overlays are vector Circles and Polygons, not markers: 65 monitors plus 464
 * fires as DOM markers would repaint on every pan. Their colours come from the
 * theme tokens and are redrawn when the theme changes, along with the basemap.
 */

const DARK_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: 'geometry', stylers: [{ color: '#16171c' }] },
  { elementType: 'labels.icon', stylers: [{ visibility: 'off' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#9aa0aa' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#16171c' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#4a4d57' }] },
  { featureType: 'administrative.country', elementType: 'geometry.stroke', stylers: [{ color: '#6b6f7a' }] },
  { featureType: 'administrative.province', elementType: 'geometry.stroke', stylers: [{ color: '#585c66' }] },
  { featureType: 'administrative.locality', elementType: 'labels.text.fill', stylers: [{ color: '#b9bec8' }] },
  { featureType: 'poi', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#22242a' }] },
  { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#2c2f36' }] },
  { featureType: 'transit', stylers: [{ visibility: 'off' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#0e1013' }] },
  { featureType: 'landscape.natural', elementType: 'geometry', stylers: [{ color: '#191a1f' }] },
];

// Muted, so the AQI colours and the fires are what the eye lands on.
const LIGHT_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: 'geometry', stylers: [{ color: '#f1f2f4' }] },
  { elementType: 'labels.icon', stylers: [{ visibility: 'off' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#5f6368' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#f5f5f5' }] },
  { featureType: 'administrative', elementType: 'geometry.stroke', stylers: [{ color: '#c4c7cc' }] },
  { featureType: 'administrative.country', elementType: 'geometry.stroke', stylers: [{ color: '#8a9096' }] },
  { featureType: 'administrative.province', elementType: 'geometry.stroke', stylers: [{ color: '#a4a9af' }] },
  { featureType: 'administrative.locality', elementType: 'labels.text.fill', stylers: [{ color: '#3c4043' }] },
  { featureType: 'poi', stylers: [{ visibility: 'off' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#ffffff' }] },
  { featureType: 'road', elementType: 'labels', stylers: [{ visibility: 'off' }] },
  { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#e3e5e8' }] },
  { featureType: 'transit', stylers: [{ visibility: 'off' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#c9dcef' }] },
  { featureType: 'landscape.natural', elementType: 'geometry', stylers: [{ color: '#eceef1' }] },
];

export type Layers = { stations: boolean; fires: boolean; sector: boolean };

interface Props {
  data: MapData | null;
  ev: Evidence | null;
  layers: Layers;
  theme: 'light' | 'dark';
  /** Names of monitors the API flagged as hyper-local events, drawn with a ring. */
  hotspots?: Set<string>;
}

/**
 * Loads the Maps JS API once per page and resolves only when it is actually usable.
 *
 * The script's onload is NOT that moment: under `loading=async` the bootstrap
 * returns before the API has attached its constructors, so resolving there gives
 * "google.maps.Map is not a constructor". The `callback` parameter is the one
 * signal Google fires only once the API is genuinely usable.
 */
let loader: Promise<void> | null = null;
function loadMaps(key: string): Promise<void> {
  if (loader) return loader;
  loader = new Promise<void>((resolve, reject) => {
    if ((window as any).google?.maps?.Map) return resolve();
    const cb = '__vayusetuMapsReady';
    (window as any)[cb] = () => resolve();
    const s = document.createElement('script');
    s.src = `https://maps.googleapis.com/maps/api/js?key=${key}`
          + `&libraries=geometry&v=weekly&loading=async&callback=${cb}`;
    s.async = true;
    s.onerror = () => reject(new Error('Google Maps script failed to load'));
    document.head.appendChild(s);
  });
  return loader;
}

/** Radius in metres for a monitor bubble. Bigger reading, bigger footprint. */
const stationRadius = (pm: number) => 1400 + Math.min(pm, 800) * 5.5;

/** Monitor names come from an external feed and are put into HTML: escape them. */
const esc = (s: string) =>
  s.replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

const styleFor = (theme: 'light' | 'dark') => (theme === 'dark' ? DARK_STYLE : LIGHT_STYLE);

export default function MapView({ data, ev, layers, theme, hotspots }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<google.maps.Map | null>(null);
  const shapes = useRef<{ setMap: (m: google.maps.Map | null) => void }[]>([]);
  const info = useRef<google.maps.InfoWindow | null>(null);
  const themeNow = useRef(theme);
  themeNow.current = theme;
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!MAPS_KEY || !el) return;
    let cancelled = false;

    const create = () => {
      // Only once the container has pixels. A map constructed in a zero-sized
      // element keeps an invalid viewport; this panel's height arrives after mount.
      if (cancelled || map.current || !el.clientWidth || !el.clientHeight) return;
      loadMaps(MAPS_KEY)
        .then(() => {
          if (cancelled || map.current || !el.clientWidth) return;
          const m = new google.maps.Map(el, {
            center: { lat: 28.65, lng: 77.1 },
            zoom: 9,
            disableDefaultUI: true,
            zoomControl: true,
            clickableIcons: false,
            gestureHandling: 'greedy',
            styles: styleFor(themeNow.current),
          });
          info.current = new google.maps.InfoWindow();
          m.addListener('click', () => info.current?.close());
          map.current = m;
          setReady(true);
        })
        .catch(e => !cancelled && setFailed(String(e?.message ?? e)));
    };

    // Also covers the view being hidden and shown again, and the layout stacking
    // at a breakpoint: the panel changes size without the window doing so.
    const ro = new ResizeObserver(() => {
      create();
      if (map.current) google.maps.event.trigger(map.current, 'resize');
    });
    ro.observe(el);
    create();

    return () => { cancelled = true; ro.disconnect(); };
  }, []);

  useEffect(() => {
    if (ready && map.current) map.current.setOptions({ styles: styleFor(theme) });
  }, [ready, theme]);

  // Draw the hour. Rebuilt wholesale: a new hour or theme changes every overlay.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;

    shapes.current.forEach(s => s.setMap(null));
    shapes.current = [];
    info.current?.close();

    const cone = token('--cone') || '#0b57d0';
    const fire = token('--fire') || '#ea580c';
    const ring = token('--worst-ring') || '#1a1c21';

    const add = <T extends { setMap: (m: google.maps.Map | null) => void }>(s: T) => {
      shapes.current.push(s);
      return s;
    };
    const openInfo = (position: google.maps.LatLngLiteral, html: string) => {
      info.current!.setContent(html);
      info.current!.setPosition(position);
      info.current!.open({ map: m });
    };

    // --- The wind fan, in real geodesic geometry -----------------------------
    if (layers.sector && ev?.wind.from_bearing_deg != null) {
      const origin = new google.maps.LatLng(ev.worst_station.lat, ev.worst_station.lon);
      const bearing = ev.wind.from_bearing_deg;
      const half = ev.upwind_fires.sector_deg;
      const metres = ev.upwind_fires.radius_km * 1000;
      const offset = google.maps.geometry.spherical.computeOffset;

      const arc: google.maps.LatLng[] = [origin];
      for (let a = -half; a <= half; a += 2) arc.push(offset(origin, metres, bearing + a));

      add(new google.maps.Polygon({
        paths: arc, map: m,
        strokeColor: cone, strokeOpacity: 0.6, strokeWeight: 1.5,
        fillColor: cone, fillOpacity: 0.1,
        clickable: false, zIndex: 1,
      }));

      add(new google.maps.Polyline({
        path: [origin, offset(origin, metres, bearing)], map: m,
        strokeColor: cone, strokeOpacity: 0.55, strokeWeight: 1,
        clickable: false, zIndex: 2,
        icons: [{
          icon: { path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW, scale: 2.6, strokeColor: cone },
          offset: '0%', repeat: '120px',
        }],
      }));
    }

    // --- Fires ---------------------------------------------------------------
    if (layers.fires) {
      for (const f of data?.fires ?? []) {
        const c = add(new google.maps.Circle({
          map: m, center: { lat: f.lat, lng: f.lon },
          radius: 700 + Math.min(f.frp, 60) * 22,
          strokeColor: fire, strokeOpacity: 0.6, strokeWeight: 1,
          fillColor: fire, fillOpacity: 0.4, zIndex: 3,
        }));
        c.addListener('click', () => openInfo({ lat: f.lat, lng: f.lon }, `
          <div class="iw">
            <div class="iw-kicker">Fire spotted by satellite</div>
            <div class="iw-row"><span class="iw-value num">${f.frp.toFixed(1)}</span>
              <span class="iw-unit">MW of heat</span></div>
            <div class="iw-sub">NASA FIRMS, last 48 hours</div>
          </div>`));
      }
    }

    // --- Monitors ------------------------------------------------------------
    if (layers.stations) {
      for (const s of data?.stations ?? []) {
        const hot = !!hotspots?.has(s.name);
        const worst = hot || (!!ev && s.name === ev.worst_station.name);
        const b = band(s.pm25);
        const c = add(new google.maps.Circle({
          map: m, center: { lat: s.lat, lng: s.lon },
          radius: stationRadius(s.pm25),
          strokeColor: worst ? ring : b.color,
          strokeOpacity: worst ? 0.95 : 0.75,
          strokeWeight: worst ? 2.5 : 1,
          fillColor: b.color, fillOpacity: 0.55,
          zIndex: worst ? 6 : 5,
        }));
        c.addListener('click', () => openInfo({ lat: s.lat, lng: s.lon }, `
          <div class="iw">
            <div class="iw-kicker">${hot ? 'Hyper-local event'
              : worst ? 'Worst reading in the city' : 'Air monitor'}</div>
            <div class="iw-title">${esc(s.name)}</div>
            <div class="iw-row"><span class="iw-value num">${s.pm25.toFixed(0)}</span>
              <span class="iw-unit">µg/m³ PM2.5</span></div>
            <span class="iw-pill" style="background:${b.color};color:${inkOn(b.color)}">${b.name}</span>
          </div>`));
      }
    }
  }, [ready, data, ev, layers, theme, hotspots]);

  // Frame the episode when the hour changes: the analysis moved, so the view follows.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m || !ev) return;
    const bounds = new google.maps.LatLngBounds();
    const origin = new google.maps.LatLng(ev.worst_station.lat, ev.worst_station.lon);
    bounds.extend(origin);
    (data?.stations ?? []).forEach(s => bounds.extend({ lat: s.lat, lng: s.lon }));
    if (ev.wind.from_bearing_deg != null) {
      const metres = ev.upwind_fires.radius_km * 1000;
      [-ev.upwind_fires.sector_deg, 0, ev.upwind_fires.sector_deg].forEach(a =>
        bounds.extend(google.maps.geometry.spherical.computeOffset(
          origin, metres, ev.wind.from_bearing_deg! + a)));
    }
    m.fitBounds(bounds, { top: 64, right: 56, bottom: 64, left: 56 });
  }, [ready, ev?.ts]);

  if (!MAPS_KEY || failed) {
    return (
      <div className="map-fallback">
        <MapTrifold size={32} color="var(--on-surface-dim)" />
        <strong>{failed ? 'The map could not load' : 'Map key not configured'}</strong>
        <span className="note">
          {failed ?? 'Set VITE_GOOGLE_MAPS_API_KEY in web/.env.local, then restart the dev server.'}
        </span>
      </div>
    );
  }

  return <div ref={host} className="map-host" />;
}
