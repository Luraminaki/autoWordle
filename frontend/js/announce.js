// Screen-reader-only announcements via a shared aria-live region (#sr-announcer
// in index.html) - separate from toast.js's visible-but-transient messages.

const el = document.getElementById('sr-announcer');

export function announce(message) {
  // Clearing first, then setting on the next frame, forces a fresh mutation
  // even if the new message is identical to what's already there - otherwise
  // an unchanged aria-live region doesn't fire a second announcement.
  el.textContent = '';
  requestAnimationFrame(() => {
    el.textContent = message;
  });
}
