#!/usr/bin/env python3
"""Pure display-formatting helpers: shifted-ordinal internal data -> JSON-friendly output.

Split out from `models` since these are stateless conversion functions with
no session/app-state concerns of their own - they're only ever called from
`models.get_guess_stats` to shape its response.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from autoWordle.modules.computing import Tord, WordsInformation


def convert_pool_words(pool: list[tuple[tuple[int, ...], float]], shift: int) -> list[dict[str, float]]:
    """Convert a pool of `(word, entropy)` tuples into display-ready entries.

    Args:
        pool (list[tuple[tuple[int, ...], float]]): Candidate words with their entropy score.
        shift (int): Ordinal shift used to decode letters back to characters.

    Returns:
        list[dict[str, float]]: One `{word: entropy}` mapping per candidate.
    """
    return [{''.join(chr(ord_letter + shift) for ord_letter in suggestion): round(information, 5)}
            for suggestion, information in pool]


def convert_best_guess(best_guess: tuple[Tord, float] | None, shift: int) -> dict[str, float] | None:
    """Convert a single `(word, entropy)` pair into a display-ready entry.

    Args:
        best_guess (tuple[Tord, float] | None): The highest-entropy next guess, or `None` if unavailable.
        shift (int): Ordinal shift used to decode letters back to characters.

    Returns:
        dict[str, float] | None: `{word: entropy}`, or `None` if `best_guess` is `None`.
    """
    if best_guess is None:
        return None

    word, information = best_guess
    return {''.join(chr(ord_letter + shift) for ord_letter in word): round(information, 5)}


def convert_pool_letters(pool_letters: set[int], shift: int) -> list[str]:
    """Convert a set of shifted letter ordinals into characters.

    Args:
        pool_letters (set[int]): Shifted letter ordinals.
        shift (int): Ordinal shift used to decode letters back to characters.

    Returns:
        list[str]: Decoded letters.
    """
    return [chr(ord_letter + shift) for ord_letter in pool_letters]


def convert_pool_letters_dupes(pool_letters_dupes: dict[int, int], shift: int) -> dict[str, int]:
    """Convert a shifted-letter-ordinal duplicate-count mapping into characters.

    Args:
        pool_letters_dupes (dict[int, int]): Mapping of shifted letter ordinal to max duplicate count.
        shift (int): Ordinal shift used to decode letters back to characters.

    Returns:
        dict[str, int]: Decoded mapping.
    """
    return {chr(key + shift): val for key, val in pool_letters_dupes.items()}


def convert_elimination_suggestions(suggestions: list[WordsInformation | None],
                                    shift: int) -> dict[int, list[dict[str, float]]]:
    """Convert ranked elimination suggestions into display-ready entries.

    Args:
        suggestions (list[WordsInformation | None]): Suggestions bucketed by number of unknown letters covered.
        shift (int): Ordinal shift used to decode letters back to characters.

    Returns:
        dict[int, list[dict[str, float]]]: Suggestions keyed by number of
        unknown letters covered (0 to word_length) - the same index
        `suggestions` itself already uses, not shifted by one.
    """
    elimination_suggestions: dict[int, list[dict[str, float]]] = {}

    for nb_letters_covered, ranked_suggestions in enumerate(suggestions):
        if not ranked_suggestions:
            continue

        temp_suggs = [{''.join(chr(ord_letter + shift) for ord_letter in suggestion): round(information, 5)}
                      for suggestion, information in ranked_suggestions]

        elimination_suggestions[nb_letters_covered] = elimination_suggestions.get(nb_letters_covered, []) + temp_suggs

    return elimination_suggestions
