#!/usr/bin/env python3
"""Single-session Wordle game/solver state.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import logging
import random
import time

from autoWordle.modules import computing, entropy, helpers, statics, vectorized_compendium

logger = logging.getLogger(__name__)

# Above this pool size, only pool members are considered as the next guess
# (today's behavior, cheap: O(pool_size**2)). At or below it, every word in
# the language is also scored against the current pool (`best_guesses`) -
# benchmarked at a near-fixed ~400-500ms regardless of pool size (dominated
# by the per-guess Python loop over the whole dictionary, not pool size), so
# it's only worth paying for once the pool is small enough that a same-family
# cluster (e.g. "wight"/"tight"/"night"/"might"/"fight") is actually plausible
# - comfortably covers the failure range observed in a real 2315-game
# self-play run (pool sizes 2-9 at the point of failure).
_FULL_SCAN_POOL_THRESHOLD = 50


class Wordle:
    """Tracks one game's candidate pool, remaining entropy, and target word."""

    def __init__(self, language_launcher: helpers.LangLauncher) -> None:
        """Start a new game against `language_launcher`'s word list.

        Args:
            language_launcher (helpers.LangLauncher): Loaded word list (and, if available, exhaustive solver data).
        """
        self.language_launcher: helpers.LangLauncher = language_launcher

        logger.info("Computing remaining information...")
        self.pool_words: set[computing.Tord] = set()
        self.information: float = 0.0
        self.word: computing.Tord = ()
        self.shift: int = language_launcher.shift
        self.letter_extractor: computing.LetterExtractor = computing.LetterExtractor()
        # Best next-guess ranking: pool-only entropy while the pool is large
        # (cheap, already what `pool_words_information` is), or full-dictionary
        # entropy against the current pool once it's small enough to be worth
        # the extra cost (see `_FULL_SCAN_POOL_THRESHOLD`) - set by
        # `submit_guess_and_pattern`, not `reset()`, since there's nothing
        # meaningful to narrow yet at the start of a fresh game.
        self.best_guesses: computing.WordsInformation = []

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

        self.letter_extractor = computing.LetterExtractor()
        self.best_guesses = []


    def submit_guess_and_pattern(self, guess: computing.Tord, pattern: computing.Tord) -> computing.WordsInformation | None:
        """Narrow the candidate pool given a guess and its resulting pattern (solve/assisted modes).

        Args:
            guess (computing.Tord): Guessed word.
            pattern (computing.Tord): Resulting pattern for `guess`.

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

        pool_words = self.language_launcher.get_matching_words(guess, pattern)

        self.pool_words = self.pool_words.intersection(pool_words)

        if not self.pool_words:
            logger.info("Pool words is empty")
            return None

        # Vectorized cross-counter with guesses == targets == pool, instead of
        # the pure-Python legacy_compendium.build_pattern_compendium +
        # legacy_compendium.compute_words_information pipeline this replaced -
        # benchmarked ~2.4x faster on the real wordle.txt dictionary, and as a
        # side effect also correctly includes each guess's own "self-match"
        # outcome (guessing pool word W when the answer actually is W), which
        # build_pattern_compendium's permutation-based construction always
        # excluded - a uniform, ranking-preserving entropy increase (verified:
        # the exact `-(1/n)*log2(1/n)` self-match contribution), not a bug fix
        # that changes anything's relative order.
        pool_counter = vectorized_compendium.compute_word_counter_by_pattern_cross(self.pool_words, self.pool_words)
        pool_words_information = entropy.rank_words_by_entropy(
            self.pool_words, pool_counter, self.language_launcher.threads, nbr_words=len(self.pool_words))

        self.information = -computing.safe_log2(1.0 / float(len(pool_words_information)))

        # Pool-only ranking by default; once the pool is small enough that a
        # same-family cluster is plausible (e.g. "wight"/"tight"/"night"/
        # "might"/"fight" - guessing any one against any other always
        # produces the identical pattern, so pool-only guessing can only
        # eliminate one candidate per guess), also score every word in the
        # language against the current pool - a word outside the family that
        # tests several of the differentiating letters at once can split it
        # in one guess instead. Gated by size: benchmarked at a near-fixed
        # ~400-500ms regardless of pool size, so not worth paying for on
        # every turn (see `_FULL_SCAN_POOL_THRESHOLD`).
        self.best_guesses = pool_words_information
        if 1 < len(self.pool_words) <= _FULL_SCAN_POOL_THRESHOLD:
            dictionary_counter = vectorized_compendium.compute_word_counter_by_pattern_cross(
                self.language_launcher.words, self.pool_words)
            self.best_guesses = entropy.rank_words_by_entropy(
                self.language_launcher.words, dictionary_counter, self.language_launcher.threads,
                nbr_words=len(self.pool_words))

        tac = time.perf_counter() - tic

        logger.info("Found %d matches in %s second(s)", len(self.pool_words), round(tac, 2))
        logger.info("Remaining information is %s", round(self.information, 2))

        return pool_words_information


    def submit_guess(self, guess: computing.Tord) -> computing.Tord | None:
        """Evaluate a guess against this game's target word (play mode).

        Args:
            guess (computing.Tord): Guessed word.

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
