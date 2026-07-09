#!/usr/bin/env python3
"""Word-list loading, int-packing codec, and CSV sidecar I/O.

Pure, stateless utility functions with no dependency on `LangLauncher` or any
other class state - split out from `helpers` so the low-level word-list/file
mechanics stay separate from the higher-level per-language orchestration.

@author: Luraminaki
@rules: https://en.wikipedia.org/wiki/Wordle
"""

import csv
import logging
import pathlib

import unidecode

from autoWordle.modules.computing import Tord, WordsInformation

logger = logging.getLogger(__name__)


def tord_from_int(txt: int, word_length: int, units: int = 100) -> Tord:
    """Unpack a base-`units`-encoded int back into a shifted-ordinal word tuple.

    Args:
        txt (int): Packed integer, as produced by `tord_to_int`.
        word_length (int): Number of letters to unpack.
        units (int): Base used for packing (matches the base used in `tord_to_int`).

    Returns:
        Tord: Decoded shifted-ordinal word.
    """
    res = [0] * word_length

    for cptr in range(-1, -word_length - 1, -1):
        res[cptr] = txt % units
        txt = txt // units

    return tuple(res)


def tord_to_int(tord: Tord, units: int = 100) -> int:
    """Pack a shifted-ordinal word tuple into a single base-`units` int.

    Args:
        tord (Tord): Shifted-ordinal word.
        units (int): Base to pack with (100 comfortably fits any single shifted ordinal digit-pair).

    Returns:
        int: Packed integer.
    """
    acc = 0

    for ord_letter in tord:
        acc = (acc * units) + ord_letter

    return acc


def get_words_list(path: pathlib.Path, word_length: int, shift: int) -> set[Tord]:
    """Load every `word_length`-letter word from a word list file.

    Args:
        path (pathlib.Path): Newline-delimited word list file.
        word_length (int): Word length to filter to.
        shift (int): Ordinal shift applied when encoding letters.

    Returns:
        set[Tord]: Distinct matching words, as shifted-ordinal tuples.
    """
    words: set[Tord] = set()

    if not path.is_file():
        logger.warning("Invalid path for file %s", path)
        return words

    with path.open('r', encoding='utf-8') as fp:
        for line in fp:
            word = unidecode.unidecode(line.strip()).lower()
            if len(word) == word_length and word.isalpha():
                words.add(tuple(ord(letter) - shift for letter in word))

    return words


def get_data_paths(words_file: pathlib.Path, word_length: int) -> tuple[pathlib.Path, pathlib.Path]:
    """Derive this word list's precomputed sidecar file paths for a given word length.

    Args:
        words_file (pathlib.Path): Source word list file.
        word_length (int): Word length these sidecars are precomputed for.

    Returns:
        tuple[pathlib.Path, pathlib.Path]: `(cache_file, words_information_file)`.
    """
    cache_path = str(words_file).replace(words_file.name, f"{words_file.stem}_{word_length}_compendium.sqlite")
    cache_file = pathlib.Path(cache_path).expanduser()

    words_information_path = str(words_file).replace(words_file.name, f"{words_file.stem}_{word_length}_info.csv")
    words_information_file = pathlib.Path(words_information_path).expanduser()

    return cache_file, words_information_file


def save_words_information(path: pathlib.Path, words_information: WordsInformation, shift: int) -> None:
    """Persist an entropy ranking to a CSV sidecar file.

    Args:
        path (pathlib.Path): Destination CSV file (overwritten if it exists).
        words_information (WordsInformation): Words ranked by entropy.
        shift (int): Ordinal shift used to decode letters back to characters.
    """
    path.unlink(missing_ok=True)

    with path.open('a', encoding='utf-8') as fp:
        writer = csv.writer(fp)

        for word, entropy in words_information:
            writer.writerow([''.join(chr(letter + shift) for letter in word), entropy])


def load_words_information(path: pathlib.Path, shift: int) -> WordsInformation:
    """Load a previously persisted entropy ranking from a CSV sidecar file.

    Args:
        path (pathlib.Path): Source CSV file, as written by `save_words_information`.
        shift (int): Ordinal shift used to encode letters.

    Returns:
        WordsInformation: Words ranked by entropy, as persisted.
    """
    with path.open('r', encoding='utf-8') as fp:
        reader = csv.reader(fp)
        return [(tuple(ord(letter) - shift for letter in word), float(entropy)) for word, entropy in reader]
