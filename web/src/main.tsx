import React from 'react';
import ReactDOM from 'react-dom/client';

// Self-hosted: no render-blocking request to fonts.googleapis.com, and the app
// still renders on a locked-down government network with no CDN access.
import '@fontsource/roboto/400.css';
import '@fontsource/roboto/500.css';
import '@fontsource/roboto/700.css';
import '@fontsource/roboto-mono/400.css';
import '@fontsource/roboto-mono/500.css';

import './theme.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);

// Installable as an app, with the shell available offline. Production only: a
// service worker in development serves stale modules and hides hot reloads.
if ((import.meta as any).env?.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => { /* app works without it */ });
  });
}
