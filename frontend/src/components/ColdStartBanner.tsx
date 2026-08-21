import { useEffect, useState } from 'react';

import { setColdStartHandler } from '@/api/client';

/**
 * Explains a cold start while it's happening.
 *
 * The API sleeps on the free tier, so the first request after a quiet period
 * waits 30-60s while the container boots. Without this the user sees a spinner
 * that never resolves, or a raw "status 503" — both of which read as "broken"
 * rather than "waking up".
 */
export function ColdStartBanner() {
  const [waking, setWaking] = useState(false);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    setColdStartHandler(setWaking);
    return () => setColdStartHandler(null);
  }, []);

  useEffect(() => {
    if (!waking) {
      setSeconds(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(
      () => setSeconds(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [waking]);

  if (!waking) return null;

  return (
    <div className="alert alert-info" role="status" aria-live="polite" style={{ marginBottom: 14 }}>
      <strong>Waking the server…</strong> The API sleeps when idle on the free
      tier and takes up to a minute to start. Retrying automatically — no need to
      refresh. ({seconds}s)
    </div>
  );
}
