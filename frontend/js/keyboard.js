// On-screen QWERTY/AZERTY keyboard + physical keydown listener. One instance
// per active Play/Assisted game screen; call destroy() when leaving the screen.
//
// This only rearranges the on-screen buttons - physical typing already
// respects whichever layout the OS/browser is actually using, since
// `onPhysicalKeydown` reads the resulting `event.key` character rather than
// a physical scan code.

import { StatusLetter, statusLabel } from './statics.js';

export const KeyboardLayout = {
  QWERTY: 'qwerty',
  AZERTY: 'azerty',
};

const LAYOUT_ROWS = {
  [KeyboardLayout.QWERTY]: [
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l'],
    ['enter', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'backspace'],
  ],
  [KeyboardLayout.AZERTY]: [
    ['a', 'z', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['q', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'm'],
    ['enter', 'w', 'x', 'c', 'v', 'b', 'n', 'backspace'],
  ],
};

export function createKeyboard(container, { onLetter, onEnter, onBackspace }, layout = KeyboardLayout.QWERTY) {
  container.innerHTML = '';
  const keyEls = new Map();
  const allKeyEls = new Map();

  for (const row of LAYOUT_ROWS[layout] || LAYOUT_ROWS[KeyboardLayout.QWERTY]) {
    const rowEl = document.createElement('div');
    rowEl.className = 'keyboard-row';

    for (const key of row) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'key';
      if (key === 'enter' || key === 'backspace') btn.classList.add('wide');
      btn.textContent = key === 'backspace' ? '⌫' : key === 'enter' ? 'Enter' : key;
      btn.addEventListener('click', () => handleKey(key));
      rowEl.appendChild(btn);
      if (key.length === 1) keyEls.set(key, btn);
      allKeyEls.set(key, btn);
    }

    container.appendChild(rowEl);
  }

  // Physical key presses don't trigger the on-screen button's own `:active`
  // state, and a fast click's `:active` window is often too short to
  // register visually - so press feedback is driven explicitly here instead,
  // covering both input paths the same way.
  function flashPress(key) {
    const btn = allKeyEls.get(key);
    if (!btn) return;

    btn.classList.add('pressed');
    window.setTimeout(() => btn.classList.remove('pressed'), 120);
  }

  function handleKey(key) {
    flashPress(key);
    if (key === 'enter') onEnter();
    else if (key === 'backspace') onBackspace();
    else onLetter(key);
  }

  function onPhysicalKeydown(event) {
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const key = event.key.toLowerCase();

    if (key === 'enter') handleKey('enter');
    else if (key === 'backspace') handleKey('backspace');
    else if (/^[a-z]$/.test(key)) handleKey(key);
  }

  document.addEventListener('keydown', onPhysicalKeydown);

  return {
    setKeyStatus(letter, status) {
      const btn = keyEls.get(letter);
      if (!btn) return;

      // StatusLetter's own values (MISS:1, MISPLACED:2, EXACT:3) already are
      // the rank order, so the raw status doubles as its own priority - no
      // separate lookup table needed.
      const current = Object.values(StatusLetter).find((s) => btn.classList.contains(`status-${s}`));
      if (current && current >= status) return;

      if (current) btn.classList.remove(`status-${current}`);
      btn.classList.add(`status-${status}`);
      btn.setAttribute('aria-label', `${letter}: ${statusLabel(status)}`);
    },
    destroy() {
      document.removeEventListener('keydown', onPhysicalKeydown);
    },
  };
}
