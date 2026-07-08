#!/usr/bin/env python3
"""Single-session Wordle game/solver state.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import logging
import random
import time

from autoWordle.modules import computing, entropy, helpers, statics

logger = logging.getLogger(__name__)


class Wordle:
    """Tracks one game's candidate pool, remaining entropy, and target word."""

    def __init__(self, language_launcher: helpers.LangLauncher) -> None:
        """Start a new game against `language_launcher`'s word list.

        Args:
            language_launcher: Loaded word list (and, if available, exhaustive solver data).
        """
        self.language_launcher: helpers.LangLauncher = language_launcher

        logger.info("Computing remaining information...")
        self.pool_words: set[computing.Tord] = set()
        self.information: float = 0.0
        self.word: computing.Tord = ()
        self.shift: int = language_launcher.shift
        self.letter_extractor: computing.LetterExtractor = {'incl': {}, 'excl': {}}

        self.reset()
        logger.info("Remaining information is: %s bit(s)", round(self.information, 2))


    def _is_invalid_word(self, word: computing.Tord) -> bool:
        return len(word) != self.language_launcher.word_length or word not in self.language_launcher.words


    def _is_invalid_pattern(self, pattern: computing.Tord) -> bool:
        allowed = [entry.value for entry in statics.StatusLetter]
        foreign_found = not all(status in allowed for status in set(pattern))

        return len(pattern) != self.language_launcher.word_length or foreign_found


    def reset(self) -> None:
        """Pick a new random target word and reset the candidate pool/solver state."""
        self.pool_words = self.language_launcher.words.copy()
        self.information = -computing.safe_log2(1.0 / float(len(self.pool_words)))
        self.word = random.choice(list(self.pool_words))

        self.letter_extractor = {'incl': {}, 'excl': {}}


    def submit_guess_and_pattern(self, guess: computing.Tord, pattern: computing.Tord) -> computing.WordsInformation | None:
        """Narrow the candidate pool given a guess and its resulting pattern (solve/assisted modes).

        Args:
            guess: Guessed word.
            pattern: Resulting pattern for `guess`.

        Returns:
            computing.WordsInformation | None: Remaining candidates ranked by
            entropy, or `None` if `guess`/`pattern` are invalid or no
            candidates remain.
        """
        if self._is_invalid_word(guess):
            logger.warning("Word %s is not allowed", guess)
            return None

        if self._is_invalid_pattern(pattern):
            logger.warning("Pattern %s is not allowed", pattern)
            return None

        tic = time.perf_counter()

        if not self.pool_words:
            logger.info("Pool words is empty")
            return None

        pool_words: set[computing.Tord] = set()

        for cand_01, cand_02 in self.language_launcher.get_couples_from_compendium(pattern):
            if cand_01 == guess:
                pool_words.add(cand_02)
            elif cand_02 == guess:
                pool_words.add(cand_01)
            else:
                continue

        self.pool_words = self.pool_words.intersection(pool_words)

        if not self.pool_words:
            logger.info("Pool words is empty")
            return None

        pool_pattern_compendium = computing.build_pattern_compendium(self.pool_words)
        pool_words_information = entropy.compute_words_information(self.pool_words, pool_pattern_compendium)

        self.information = -computing.safe_log2(1.0 / float(len(pool_words_information)))

        tac = time.perf_counter() - tic

        logger.info("Found %d matches in %s second(s)", len(self.pool_words), round(tac, 2))
        logger.info("Remaining information is %s", round(self.information, 2))

        return pool_words_information


    def submit_guess(self, guess: computing.Tord) -> computing.Tord | None:
        """Evaluate a guess against this game's target word (play mode).

        Args:
            guess: Guessed word.

        Returns:
            computing.Tord | None: Resulting pattern, or `None` if `guess` isn't a valid word.
        """
        if self._is_invalid_word(guess):
            guess_str = ''.join(chr(ord_letter + self.shift) for ord_letter in guess)
            logger.warning("Word %s is not allowed", guess_str)
            return None

        pattern = computing.compute_pattern(guess=guess, word=self.word)
        logger.info("%s", statics.pattern_to_emoji(pattern))

        return pattern
