#!/usr/bin/env python3
"""Core pattern/candidate-pool algorithms: pattern computation and elimination suggestions.

Entropy ranking and its `ProcessPoolExecutor` parallelization live in the
companion `entropy` module instead - a distinct concern (statistics +
multiprocessing) from the pattern/pool logic here.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import dataclasses
import math

from autoWordle.modules import statics

type Tord = tuple[int, ...]
type PatternCompendium = dict[Tord, set[tuple[Tord, Tord]]]
type WordCounterByPattern = dict[Tord, dict[Tord, int]]
type WordsInformation = list[tuple[Tord, float]]


@dataclasses.dataclass
class LetterExtractor:
    """Known-included/excluded letters accumulated across a session's guesses.

    `incl`/`excl` map a shifted letter ordinal to a count (occurrences seen
    included, or `1` for excluded - excluded letters are never counted, just
    flagged).
    """

    incl: dict[int, int] = dataclasses.field(default_factory=dict)
    excl: dict[int, int] = dataclasses.field(default_factory=dict)


def compute_pattern(guess: Tord, word: Tord) -> Tord:
    """Compute the Wordle guess/word evaluation pattern.

    This is the single most-called function in the whole solver (called
    `O(n**2)` times when building a pattern compendium). Standard two-pass
    algorithm: exact matches first, then misplaced letters are assigned
    left-to-right in *guess* order, budgeted by how many of that letter are
    left over in `word` after exact matches are removed.

    This replaces an earlier version that scanned `word` (not `guess`) and
    grabbed the first available guess slot via `list.index()` for each
    non-exact word letter - which could "spend" a guess slot on a word letter
    before learning that slot was actually an unrelated exact match found
    later in the same pass (only possible when `guess` has a repeated
    letter). E.g. `guess="jelly"`, `word="allay"`: `allay`'s first "l" (index
    1) would get greedily matched to `jelly`'s first "l" (index 2, via
    `index()`) as MISPLACED, moments before index 2 is independently found to
    be an EXACT match at `word`'s own index 2 and overwritten - permanently
    losing the leftover "l" that should have gone to `jelly`'s *second* "l"
    (index 3), which the old code left as MISS instead of MISPLACED.
    Confirmed empirically: ~0.08% of pairs in the bundled `wordle.txt` list
    disagreed between the two versions, always on a repeated-letter guess.

    Args:
        guess (Tord): Guessed word, as shifted letter ordinals.
        word (Tord): Target word, as shifted letter ordinals.

    Returns:
        Tord: One `StatusLetter` value per letter of `guess`.
    """
    length = len(word)
    pattern = [statics.StatusLetter.MISS.value] * length
    remaining: dict[int, int] = {}

    for pos in range(length):
        if guess[pos] == word[pos]:
            pattern[pos] = statics.StatusLetter.EXACT.value
        else:
            remaining[word[pos]] = remaining.get(word[pos], 0) + 1

    for pos in range(length):
        if pattern[pos] == statics.StatusLetter.EXACT.value:
            continue

        letter = guess[pos]
        if remaining.get(letter, 0) > 0:
            pattern[pos] = statics.StatusLetter.MISPLACED.value
            remaining[letter] -= 1

    return tuple(pattern)


def build_letter_extractor(guess: Tord, pattern: Tord) -> LetterExtractor:
    """Extract known-included/excluded letters from one guess and its pattern.

    Args:
        guess (Tord): Guessed word, as shifted letter ordinals.
        pattern (Tord): Resulting pattern for `guess`.

    Returns:
        LetterExtractor: Freshly built from this one guess/pattern.
    """
    extractor = LetterExtractor()

    for pos, letter in enumerate(guess):
        if pattern[pos] != statics.StatusLetter.MISS.value:
            if letter not in extractor.incl:
                extractor.incl[letter] = 1
                continue

            extractor.incl[letter] = extractor.incl[letter] + 1
            continue

        extractor.excl[letter] = 1

    return extractor


def update_letter_extractor(old_ext: LetterExtractor, new_ext: LetterExtractor) -> LetterExtractor:
    """Merge a newly extracted letter extractor into the running one for a session.

    Args:
        old_ext (LetterExtractor): Accumulated extractor so far.
        new_ext (LetterExtractor): Extractor for the latest guess.

    Returns:
        LetterExtractor: `old_ext`, updated in place.
    """
    for letter in new_ext.incl:
        if letter not in old_ext.incl:
            old_ext.incl[letter] = new_ext.incl[letter]
            continue

        old_ext.incl[letter] = old_ext.incl[letter] + new_ext.incl[letter]

    old_ext.excl.update(new_ext.excl)

    return old_ext


def gather_pool_letters(pool_words: WordsInformation) -> tuple[set[int], dict[int, int]]:
    """Collect every letter present in a candidate pool, and duplicate-letter counts.

    Args:
        pool_words (WordsInformation): Candidate words with their entropy score.

    Returns:
        tuple[set[int], dict[int, int]]: Letters seen across the pool, and the
        maximum observed duplicate count per letter.
    """
    pool_letters: set[int] = set()
    dupes: dict[int, int] = {}

    for word, _ in pool_words:
        unique_letters = set(word)
        pool_letters.update(unique_letters)

        if len(unique_letters) < len(word):
            for letter in unique_letters:
                if count := word.count(letter):
                    dupes[letter] = count if dupes.get(letter, 0) < count else dupes.get(letter, count)

    return pool_letters, dupes


def build_suggestion(pool_words_information: WordsInformation,
                     pool_letters: set[int],
                     pool_letters_dupes: dict[int, int],
                     letter_extractor: LetterExtractor) -> list[WordsInformation | None]:
    """Rank candidate words by how many still-unknown letters they'd test.

    Args:
        pool_words_information (WordsInformation): Candidate words with their entropy score.
        pool_letters (set[int]): Every letter present across the candidate pool.
        pool_letters_dupes (dict[int, int]): Maximum observed duplicate count per letter.
        letter_extractor (LetterExtractor): Known-included/excluded letters so far.

    Returns:
        list[WordsInformation | None]: Suggestions bucketed by number of
        unknown letters covered (index 0 = covers none, ..., index
        word_length = covers all), each bucket sorted by entropy descending.
        A bucket is `None` if no candidate covers that exact number of
        unknown letters.
    """
    known_letters: set[int] = set()

    for letter in letter_extractor.incl:
        # If the letter can have a dupe (according to the pool_words),
        # but we don't know for sure (because not tested),
        # then we don't add it in the known_letters (and should test it if possible)
        if pool_letters_dupes.get(letter, 0) != 0 and pool_letters_dupes.get(letter, 0) > letter_extractor.incl.get(letter, 0):
            continue
        known_letters.add(letter)

    # By design, if the letter extracted is in the exclusion list, but also in the inclusion list,
    # then it means that we know for sure how many time the letter is in the word to guess,
    # and we should have pool_letters_dupes.get(letter, 0) == letter_extractor.incl.get(letter, 0)
    for letter in letter_extractor.excl:
        known_letters.add(letter)

    unknown_letters = pool_letters.difference(known_letters)
    suggestions: list[WordsInformation | None] = [None] * (len(pool_words_information[0][0]) + 1)

    for word_information in pool_words_information:
        nb_letters_in_common = len(set(word_information[0]).intersection(unknown_letters))
        bucket = suggestions[nb_letters_in_common]

        if bucket is None:
            suggestions[nb_letters_in_common] = [word_information]
            continue

        bucket.append(word_information)

    for idx, sugg_letters_in_common in enumerate(suggestions):
        if sugg_letters_in_common:
            suggestions[idx] = sorted(sugg_letters_in_common, key=lambda x: x[-1], reverse=True)

    return suggestions


def safe_log2(x: int | float) -> int | float:
    """Compute `log2(x)`, treating non-positive input as zero information.

    Args:
        x (int | float): Value to take the log of.

    Returns:
        int | float: `log2(x)` if `x > 0`, else `0`.
    """
    return math.log2(x) if x > 0 else 0
