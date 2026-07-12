// Triggers a POST /precompute build and drives a progress bar off its SSE
// GET /precompute_progress stream. Used by the setup screen.

import { requestPrecompute, precomputeProgressUrl } from './api.js';
import { PrecomputeStatus } from './statics.js';

// Not PrecomputeStatus members on the Python side either (webapp/api_views.py's
// `precompute_progress` SSE stream) - both mean the stream itself couldn't
// report real job state, distinct from any actual job lifecycle state:
// 'not_found' means no job record exists at all for this lang/word_length;
// 'error' means the generator hit an unexpected server-side exception.
const SSE_JOB_NOT_FOUND = 'not_found';
const SSE_STREAM_ERROR = 'error';

function formatEta(seconds) {
  if (seconds == null) return '';
  if (seconds < 60) return `~${Math.ceil(seconds)}s left`;
  return `~${Math.ceil(seconds / 60)}min left`;
}

export async function runPrecompute(lang, wordLength, { barEl, fillEl, statusEl, onDone, onError }) {
  let result;
  try {
    result = await requestPrecompute(lang, wordLength);
  } catch (err) {
    onError(err.message);
    return;
  }

  if (result.job_status === PrecomputeStatus.DONE) {
    // The backend short-circuits a request for data that's already built
    // (e.g. another tab/process finished it since this screen last
    // refreshed) - no job was queued at all, so there's nothing to open an
    // SSE connection for; doing so anyway would just get "not found".
    barEl.hidden = false;
    fillEl.style.width = '100%';
    statusEl.textContent = 'Already built';
    onDone();
    return;
  }

  barEl.hidden = false;
  fillEl.style.width = '0%';
  statusEl.textContent = result.queue_position ? `Queued (position ${result.queue_position})...` : 'Starting...';

  const source = new EventSource(precomputeProgressUrl(lang, wordLength));

  source.onmessage = (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (err) {
      source.close();
      onError(`Malformed precompute progress update: ${err.message}`);
      return;
    }

    if (payload.status === SSE_JOB_NOT_FOUND) {
      source.close();
      onError('Precompute job not found');
      return;
    }

    if (payload.status === SSE_STREAM_ERROR) {
      source.close();
      onError(payload.error || 'Precompute progress stream failed');
      return;
    }

    if (payload.status === PrecomputeStatus.FAILED) {
      source.close();
      onError(payload.error || 'Precompute job failed');
      return;
    }

    if (payload.status === PrecomputeStatus.DONE) {
      fillEl.style.width = '100%';
      statusEl.textContent = 'Done';
      source.close();
      onDone();
      return;
    }

    if (payload.status === PrecomputeStatus.QUEUED) {
      // This job's own fraction_done/eta_seconds are meaningless placeholders
      // (nothing updates them until it starts running). The backend instead
      // sends whichever job *is* currently running (`current_job`) when one
      // exists - showing its real, live-moving progress proves the server
      // hasn't hung, and for whoever's next in line it doubles as their own
      // wait estimate for free.
      const position = payload.position ? ` (position ${payload.position})` : '';

      if (payload.current_job) {
        const { lang: currentLang, word_length: currentWordLength, fraction_done, eta_seconds } = payload.current_job;
        const pct = Math.round((fraction_done || 0) * 100);
        fillEl.style.width = `${pct}%`;
        statusEl.textContent =
          `Queued${position} - currently building ${currentLang}/${currentWordLength}: ${pct}% ${formatEta(eta_seconds)}`;
      } else {
        // Momentary gap between one job finishing and the next being claimed.
        fillEl.style.width = '0%';
        statusEl.textContent = `Queued${position} - waiting for another build to finish`;
      }
      return;
    }

    const pct = Math.round((payload.fraction_done || 0) * 100);
    fillEl.style.width = `${pct}%`;
    statusEl.textContent = `Running - ${pct}% ${formatEta(payload.eta_seconds)}`;
  };

  source.onerror = () => {
    // EventSource retries automatically on a transient drop (readyState
    // becomes CONNECTING, not CLOSED) - the build itself keeps progressing
    // server-side regardless of this one connection's state, so treating
    // every blip as terminal would show a hard error for something that was
    // about to recover on its own. Only CLOSED (the browser gave up, or this
    // was a fatal client-side error) is an actual, unrecoverable failure.
    if (source.readyState !== EventSource.CLOSED) return;
    source.close();
    onError('Lost connection to the precompute progress stream');
  };
}
