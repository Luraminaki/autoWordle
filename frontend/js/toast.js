const el = document.getElementById('toast');
let hideTimer = null;

export function showToast(message, durationMs = 2500) {
  el.textContent = message;
  el.hidden = false;
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => {
    el.hidden = true;
  }, durationMs);
}
