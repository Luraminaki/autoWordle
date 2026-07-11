// Renders a schemas.GuessStats-shaped object into a solver-hints panel.
// Shared by Assisted (game.js) and Solve (solve.js) screens.

const MAX_CANDIDATES_SHOWN = 12;
const MAX_SUGGESTIONS_PER_RANK = 5;

function firstEntry(dictEntry) {
  const [word, information] = Object.entries(dictEntry)[0];
  return { word, information };
}

// textContent throughout (not innerHTML+template-literal interpolation) so a
// word or number from the API can never be parsed as markup - the backend
// only ever returns alphabetic word-list entries today, but this doesn't
// depend on that staying true.
function addHintsRow(container, label, value) {
  const row = document.createElement('div');
  row.className = 'hints-row';

  const labelEl = document.createElement('span');
  labelEl.textContent = label;
  const valueEl = document.createElement('strong');
  valueEl.textContent = value;

  row.append(labelEl, valueEl);
  container.appendChild(row);
}

export function renderHints(container, guessStats) {
  if (!guessStats) {
    container.hidden = true;
    container.innerHTML = '';
    return;
  }

  container.hidden = false;
  container.innerHTML = '';

  const title = document.createElement('h3');
  title.textContent = 'Solver hints';
  container.appendChild(title);

  addHintsRow(container, 'Candidates remaining', String(guessStats.pool_words.length));
  addHintsRow(container, 'Information gained so far', `${guessStats.information.toFixed(2)} bits`);

  if (guessStats.best_guess) {
    const { word, information } = firstEntry(guessStats.best_guess);
    addHintsRow(container, 'Best next guess', `${word} (${information.toFixed(2)} bits)`);
  }

  if (guessStats.pool_letters.length) {
    const lettersHeading = document.createElement('h4');
    lettersHeading.textContent = 'Letters still possible';
    container.appendChild(lettersHeading);

    const chips = document.createElement('div');
    chips.className = 'chip-list';
    for (const letter of guessStats.pool_letters) {
      const dupes = guessStats.pool_letters_dupes[letter];
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = dupes > 1 ? `${letter} ×${dupes}` : letter;
      chips.appendChild(chip);
    }
    container.appendChild(chips);
  }

  if (guessStats.pool_words.length) {
    const wordsHeading = document.createElement('h4');
    wordsHeading.textContent = 'Candidate words';
    container.appendChild(wordsHeading);

    const chips = document.createElement('div');
    chips.className = 'chip-list';
    for (const entry of guessStats.pool_words.slice(0, MAX_CANDIDATES_SHOWN)) {
      const { word, information } = firstEntry(entry);
      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = word;
      chip.title = `${information.toFixed(2)} bits`;
      chips.appendChild(chip);
    }
    if (guessStats.pool_words.length > MAX_CANDIDATES_SHOWN) {
      const more = document.createElement('span');
      more.className = 'chip';
      more.textContent = `+${guessStats.pool_words.length - MAX_CANDIDATES_SHOWN} more`;
      chips.appendChild(more);
    }
    container.appendChild(chips);
  }

  const rankKeys = Object.keys(guessStats.elimination_suggestions);
  if (rankKeys.length) {
    const suggHeading = document.createElement('h4');
    suggHeading.textContent = 'Elimination suggestions';
    container.appendChild(suggHeading);

    for (const rank of rankKeys.sort((a, b) => Number(a) - Number(b))) {
      const suggestions = guessStats.elimination_suggestions[rank];
      const group = document.createElement('div');
      group.className = 'elimination-group';

      const groupHeading = document.createElement('h4');
      groupHeading.textContent = `Covers ${rank} unknown letter${rank === '1' ? '' : 's'}`;
      group.appendChild(groupHeading);

      const chips = document.createElement('div');
      chips.className = 'chip-list';
      for (const entry of suggestions.slice(0, MAX_SUGGESTIONS_PER_RANK)) {
        const { word, information } = firstEntry(entry);
        const chip = document.createElement('span');
        chip.className = 'chip';
        chip.textContent = word;
        chip.title = `${information.toFixed(2)} bits`;
        chips.appendChild(chip);
      }
      if (suggestions.length > MAX_SUGGESTIONS_PER_RANK) {
        const more = document.createElement('span');
        more.className = 'chip';
        more.textContent = `+${suggestions.length - MAX_SUGGESTIONS_PER_RANK} more`;
        chips.appendChild(more);
      }
      group.appendChild(chips);
      container.appendChild(group);
    }
  }
}
