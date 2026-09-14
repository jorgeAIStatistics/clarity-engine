"""Literal number transcription. No arithmetic estimates or unit conversions.

English cardinal words zero through ninety-nine are supported conservatively.
Unsupported word forms remain extraction failures rather than guessed numbers.
"""

import re
from decimal import Decimal

_UNITS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
WORDS = {word: n for n, word in enumerate(_UNITS)}
for base, word in enumerate(_TENS, 2):
    WORDS[word] = base * 10
    for n, unit in enumerate(_UNITS[1:10], 1):
        for separator in ("-", " "):
            WORDS[word + separator + unit] = base * 10 + n
WORD_PATTERN = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(re.escape(w) for w in sorted(WORDS, key=len, reverse=True))
    + r")(?![\w-])",
    re.I,
)
DIGITS = re.compile(
    r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
)


def parse_numeric_token(raw):
    token = raw.replace("−", "-").replace("·", ".")
    if token.lower() in WORDS:
        return float(WORDS[token.lower()])
    if not DIGITS.fullmatch(token):
        raise ValueError("Unsupported numeric token")
    return float(token.replace(",", ""))


def parse_count_token(raw):
    token = raw.replace("−", "-").replace("·", ".")
    if token.lower() in WORDS:
        return WORDS[token.lower()]
    if not DIGITS.fullmatch(token):
        raise ValueError("Unsupported count token")
    value = Decimal(token.replace(",", ""))
    if value != value.to_integral_value():
        raise ValueError("Nonintegral count token")
    return int(value)


def verbatim_numeric_token(raw, quotes):
    """Recover only an identical cardinal literal, never an estimated quantity.

    An extractor may serialize 24 while the quoted source says Twenty-four. Preserve
    that exact source token, after checking that its numeric meaning is identical.
    Ambiguous alternatives and absent numeric support remain unchanged and fail the
    ordinary source validator. The original transport is retained in the audit log.
    """
    if any(raw in quote for quote in quotes):
        return raw
    try:
        value = parse_numeric_token(raw)
    except ValueError:
        return raw
    matches = set()
    for quote in quotes:
        for match in WORD_PATTERN.finditer(quote):
            before, after = quote[: match.start()], quote[match.end() :]
            if re.search(
                r"(?:minus|negative|hundred|thousand|million|billion|[−-])\s*(?:and\s+)?$",
                before,
                re.I,
            ):
                continue
            if re.match(
                r"\s+(?:hundred|thousand|million|billion|point)\b", after, re.I
            ):
                continue
            if WORDS[match.group().lower()] == value:
                matches.add(match.group())
    return next(iter(matches)) if len(matches) == 1 else raw
