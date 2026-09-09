import { useEffect, useRef, useState } from 'react';
import { MapTrifold } from '@phosphor-icons/react';
import { bandColor, MAPS_KEY, type Evidence, type MapData } from '../lib/data';

/**
 * The real map.
 *
 * Everything drawn here is observed: stations where they physically stand, fire
 * detections where NASA saw them, and the upwind sector as true geodesic geometry
 * rather than a triangle drawn in screen space. That distinction matters, because
 * the cone is the claim the whole brief rests on: these fires, and not those, could
 * have reached this station.
 *
 * The Maps JS API is loaded directly rather than through a React wrapper. Every
 * overlay below is a raw google.maps object anyway, so a wrapper would only have
 * been script loading plus a container div, and the one we tried never attached a
 * map instance. Thirty lines here replace the dependency and the failure mode.
 *
 * Overlays are vector Circles and Polygons, not markers. 65 stations plus 464 fires
 * as DOM markers would repaint on every pan; as vector shapes the map draws them.
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

export type Layers = { stations: boolean; fires: boolean; sector: boolean };

interface Props {
  data: MapData | null;
  ev: Evidence | null;
  layers: Layers;
}

/**
 * Loads the Maps JS API once per page and resolves only when it is actually usable.
 *
 * The script's onload is NOT that moment: under `loading=async` the bootstrap
 * returns before the API has attached its constructors, so resolving there gives
 * "google.maps.Map is not a constructor", and importLibrary is not attached yet
 * either. The `callback` parameter is the one signal Google fires only once the
 * API is genuinely usable.
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

/** Radius in metres for a station bubble. Bigger reading, bigger footprint. */
const stationRadius = (pm: number) => 1400 + Math.min(pm, 800) * 5.5;

export default function MapView({ data, ev, layers }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<google.maps.Map | null>(null);
  const shapes = useRef<any[]>([]);
  const info = useRef<google.maps.InfoWindow | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    const el = host.current;
    if (!MAPS_KEY || !el) return;
    let cancelled = false;

    const create = () => {
      // Only once the container actually has pixels. A map constructed in a
      // zero-sized element keeps an invalid viewport and never requests a single
      // tile: it renders as a blank beige panel until something resizes it. This
      // panel is laid out by grid, so its height arrives after mount.
      if (cancelled || map.current || !el.clientWidth || !el.clientHeight) return;
      loadMaps(MAPS_KEY)
        .then(() => {
          if (cancelled || map.current || !el.clientWidth) return;
          map.current = new google.maps.Map(el, {
            center: { lat: 28.65, lng: 77.1 },
            zoom: 9,
            disableDefaultUI: true,
            zoomControl: true,
            clickableIcons: false,
            gestureHandling: 'greedy',
            styles: DARK_STYLE,
          });
          info.current = new google.maps.InfoWindow();
          setReady(true);
        })
        .catch(e => !cancelled && setFailed(String(e?.message ?? e)));
    };

    // Also covers the responsive breakpoint: when the grid stacks, the panel
    // changes size without the window doing so, and the map needs telling.
    const ro = new ResizeObserver(() => {
      create();
      if (map.current) google.maps.event.trigger(map.current, 'resize');
    });
    ro.observe(el);
    create();

    return () => { cancelled = true; ro.disconnect(); };
  }, []);

  // Draw the hour. Overlays are rebuilt wholesale because a new hour changes every
  // one of them; there is nothing worth diffing.
  useEffect(() => {
    const m = map.current;
    if (!ready || !m) return;

    shapes.current.forEach(s => s.setMap(null));
    shapes.current = [];
    info.current?.close();

    const add = <T extends { setMap: (m: google.maps.Map | null) => void }>(s: T) => {
      shapes.current.push(s);
      return s;
    };
    const openInfo = (position: google.maps.LatLngLiteral, html: string) => {
      info.current!.setContent(html);
      info.current!.setPosition(position);
      info.current!.open({ map: m });
    };

    // --- The upwind sector, in real geodesic geometry ------------------------
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
        strokeColor: '#a8c7fa', strokeOpacity: 0.55, strokeWeight: 1.5,
        fillColor: '#a8c7fa', fillOpacity: 0.1,
        clickable: false, zIndex: 1,
      }));

      add(new google.maps.Polyline({
        path: [origin, offset(origin, metres, bearing)], map: m,
        strokeColor: '#a8c7fa', strokeOpacity: 0.5, strokeWeight: 1,
        clickable: false, zIndex: 2,
        icons: [{
          icon: { path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW, scale: 2.6, strokeColor: '#a8c7fa' },
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
          strokeColor: '#fb923c', strokeOpacity: 0.5, strokeWeight: 1,
          fillColor: '#fb923c', fillOpacity: 0.35, zIndex: 3,
        }));
        c.addListener('click', () => openInfo({ lat: f.lat, lng: f.lon }, `
          <div style="font:400 13px Roboto,sans-serif;color:#e4e2e6;padding:12px 14px;min-width:150px">
            <div style="color:#fb923c;font-weight:500;margin-bottom:4px">Fire detection</div>
            <div style="color:#c5c6d0">Radiative power
              <span style="font-family:'Roboto Mono',monospace">${f.frp.toFixed(1)} MW</span></div>
            <div style="color:#8e909a;font-size:12px;margin-top:4px">NASA FIRMS (VIIRS)</div>
          </div>`));
      }
    }

    // --- Stations ------------------------------------------------------------
    if (layers.stations) {
      for (const s of data?.stations ?? []) {
        const worst = ev && s.name === ev.worst_station.name;
        const c = add(new google.maps.Circle({
          map: m, center: { lat: s.lat, lng: s.lon },
          radius: stationRadius(s.pm25),
          strokeColor: worst ? '#ffffff' : bandColor(s.pm25),
          strokeOpacity: worst ? 0.95 : 0.7,
          strokeWeight: worst ? 2.5 : 1,
          fillColor: bandColor(s.pm25), fillOpacity: 0.5,
          zIndex: worst ? 6 : 5,
        }));
        c.addListener('click', () => openInfo({ lat: s.lat, lng: s.lon }, `
          <div style="font:400 13px Roboto,sans-serif;color:#e4e2e6;padding:12px 14px;max-width:230px">
            <div style="font-weight:500;margin-bottom:6px;line-height:1.35">${s.name}</div>
            <div style="display:flex;align-items:baseline;gap:6px">
              <span style="font-family:'Roboto Mono',monospace;font-size:22px;color:${bandColor(s.pm25)}">
                ${s.pm25.toFixed(1)}</span>
              <span style="color:#8e909a;font-size:12px">ug/m3 PM2.5</span>
            </div>
            <div style="color:${bandColor(s.pm25)};font-size:12px;margin-top:2px">${s.aqi_band}</div>
          </div>`));
      }
    }
  }, [ready, data, ev, layers]);

  // Frame the episode when the hour changes: the analysis moved, so the view
  // follows it. Motivated motion, not decoration.
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
    m.fitBounds(bounds, { top: 56, right: 56, bottom: 56, left: 56 });
  }, [ready, ev?.ts]);

  if (!MAPS_KEY || failed) {
    return (
      <div style={fallback}>
        <MapTrifold size={32} color="var(--on-surface-dim)" />
        <div style={{ marginTop: 10, fontWeight: 500 }}>
          {failed ? 'Map could not load' : 'Map key not configured'}
        </div>
        <div style={{ color: 'var(--on-surface-variant)', marginTop: 4, fontSize: 13, maxWidth: 320 }}>
          {failed ?? 'Set VITE_GOOGLE_MAPS_API_KEY in web/.env.local, then restart the dev server.'}
        </div>
      </div>
    );
  }

  return <div ref={host} style={{ position: 'absolute', inset: 0 }} />;
}

const fallback: React.CSSProperties = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: 24,
  background: 'var(--surface-container-low)',
};
