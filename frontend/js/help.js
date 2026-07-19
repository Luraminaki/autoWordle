// Wires the header's "?" button to the static how-to-play modal in
// index.html. The modal's content is authored directly in the HTML (it never
// changes at runtime) - this only handles show/hide, focus, and dismissal.

const toggle = document.getElementById('help-toggle');
const overlay = document.getElementById('help-modal-overlay');
const closeBtn = document.getElementById('help-modal-close');

let lastFocused = null;

function openModal() {
  lastFocused = document.activeElement;
  overlay.hidden = false;
  closeBtn.focus();
  document.addEventListener('keydown', onKeydown);
}

function closeModal() {
  overlay.hidden = true;
  document.removeEventListener('keydown', onKeydown);
  // Restore focus to whatever opened the modal (the "?" button, normally) -
  // without this, focus silently drops to <body> and keyboard users lose
  // their place.
  if (lastFocused instanceof HTMLElement) lastFocused.focus();
}

function onKeydown(event) {
  if (event.key === 'Escape') closeModal();
}

export function initHelp() {
  toggle.addEventListener('click', openModal);
  closeBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', (event) => {
    // Only the backdrop itself should dismiss on click - clicking inside the
    // modal card (including text selection) must not close it.
    if (event.target === overlay) closeModal();
  });
}
