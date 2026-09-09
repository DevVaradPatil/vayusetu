import React from 'react';
import ReactDOM from 'react-dom/client';

// Self-hosted: no render-blocking request to fonts.googleapis.com, and the console
// still renders correctly on a locked-down government network with no CDN access.
import '@fontsource/roboto/300.css';
import '@fontsource/roboto/400.css';
import '@fontsource/roboto/500.css';
import '@fontsource/roboto-mono/400.css';
import '@fontsource/roboto-mono/500.css';

import './theme.css';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
