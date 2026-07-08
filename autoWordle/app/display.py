#!/usr/bin/env python3
"""Pure display-formatting helpers: shifted-ordinal internal data -> JSON-friendly output.

Split out from `models` since these are stateless conversion functions with
no session/app-state concerns of their own - they're only ever called from
`models.get_guess_stats` to shape its response.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

from autoWordle.modules.computing import WordsInformation


def convert_pool_words(pool: list[tuple[tuple[int, ...], float]], shift: int) -> list[dict[str, float]]:
    """Convert a pool of `(word, entropy)` tuples into display-ready entries.

    Args:
        pool: Candidate words with their entropy score.
        shift: Ordinal shift used to decode letters back to characters.

    Returns:
        list[dict[str, float]]: One `{word: entropy}` mapping per candidate.
    """
    return [{''.join(chr(ord_letter + shift) for ord_letter in suggestion): round(information, 5)}
            for suggestion, information in pool]


def convert_pool_letters(pool_letters: set[int], shift: int) -> list[str]:
    """Convert a set of shifted letter ordinals into characters.

    Args:
        pool_letters: Shifted letter ordinals.
        shift: Ordinal shift used to decode letters back to characters.

    Returns:
        list[str]: Decoded letters.
    """
    return [chr(ord_letter + shift) for ord_letter in pool_letters]


def convert_pool_letters_dupes(pool_letters_dupes: dict[int, int], shift: int) -> dict[str, int]:
    """Convert a shifted-letter-ordinal duplicate-count mapping into characters.

    Args:
        pool_letters_dupes: Mapping of shifted letter ordinal to max duplicate count.
        shift: Ordinal shift used to decode letters back to characters.

    Returns:
        dict[str, int]: Decoded mapping.
    """
    return {chr(key + shift): val for key, val in pool_letters_dupes.items()}


def convert_elimination_suggestions(suggestions: list[WordsInformation | None],
                                    shift: int) -> dict[int, list[dict[str, float]]]:
    """Convert ranked elimination suggestions into display-ready entries.

    Args:
        suggestions: Suggestions bucketed by number of unknown letters covered.
        shift: Ordinal shift used to decode letters back to characters.

    Returns:
        dict[int, list[dict[str, float]]]: Suggestions keyed by rank (1-indexed).
    """
    elimination_suggestions: dict[int, list[dict[str, float]]] = {}

    for rank, ranked_suggestions in enumerate(suggestions):
        if not ranked_suggestions:
            continue

        temp_suggs = [{''.join(chr(ord_letter + shift) for ord_letter in suggestion): round(information, 5)}
                     for suggestion, information in ranked_suggestions]

        elimination_suggestions[rank + 1] = elimination_suggestions.get(rank + 1, []) + temp_suggs

    return elimination_suggestions
