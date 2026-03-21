"""
Formatting utilities for Valinor SaaS reports.

Provides human-readable formatters for currency values, percentages,
deltas, text truncation, and slug generation.
"""

import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# Currency configuration
# ---------------------------------------------------------------------------

_CURRENCY_CONFIG: dict[str, dict] = {
    "EUR": {
        "symbol": "€",
        "symbol_position": "prefix",
        "thousands_sep": ".",
        "decimal_sep": ",",
    },
    "USD": {
        "symbol": "$",
        "symbol_position": "prefix",
        "thousands_sep": ",",
        "decimal_sep": ".",
    },
    "GBP": {
        "symbol": "£",
        "symbol_position": "prefix",
        "thousands_sep": ",",
        "decimal_sep": ".",
    },
    "ARS": {
        "symbol": "$",
        "symbol_position": "prefix",
        "thousands_sep": ".",
        "decimal_sep": ",",
    },
    "BRL": {
        "symbol": "R$",
        "symbol_position": "prefix",
        "thousands_sep": ".",
        "decimal_sep": ",",
    },
    "MXN": {
        "symbol": "$",
        "symbol_position": "prefix",
        "thousands_sep": ",",
        "decimal_sep": ".",
    },
}

_SUPPORTED_CURRENCIES = set(_CURRENCY_CONFIG.keys())


def _apply_separators(integer_part: str, thousands_sep: str) -> str:
    """Insert thousands separators into the integer part of a number string."""
    # Work right-to-left in groups of 3.
    result = []
    for i, ch in enumerate(reversed(integer_part)):
        if i > 0 and i % 3 == 0:
            result.append(thousands_sep)
        result.append(ch)
    return "".join(reversed(result))


# ---------------------------------------------------------------------------
# format_currency
# ---------------------------------------------------------------------------

def format_currency(
    value: float,
    currency: str = "EUR",
    locale: str = "es_ES",
    compact: bool = False,
    decimals: int = 2,
) -> str:
    """
    Format a numeric value as a currency string.

    Parameters
    ----------
    value:
        The numeric amount to format.
    currency:
        ISO 4217 currency code.  Supported: EUR, USD, GBP, ARS, BRL, MXN.
    locale:
        Reserved for future locale-aware formatting.  Currently the
        formatting style (dot/comma conventions) is derived from the
        currency configuration.
    compact:
        When True, large numbers are rendered with M/K suffixes
        (e.g. 1_500_000 → "€1.5M").
    decimals:
        Number of decimal places shown in non-compact mode (default 2).

    Returns
    -------
    str
        Formatted currency string, e.g. "€840.412,50" or "$840,412.50".

    Raises
    ------
    ValueError
        If *currency* is not in the supported set.
    """
    currency = currency.upper()
    if currency not in _SUPPORTED_CURRENCIES:
        raise ValueError(
            f"Unsupported currency '{currency}'. "
            f"Supported: {sorted(_SUPPORTED_CURRENCIES)}"
        )

    cfg = _CURRENCY_CONFIG[currency]
    symbol = cfg["symbol"]
    thousands_sep = cfg["thousands_sep"]
    decimal_sep = cfg["decimal_sep"]

    negative = value < 0
    abs_value = abs(value)

    if compact:
        if abs_value >= 1_000_000:
            compact_value = abs_value / 1_000_000
            # Trim trailing zeros in compact suffix
            compact_str = f"{compact_value:.1f}".rstrip("0").rstrip(".")
            formatted = f"{symbol}{compact_str}M"
        elif abs_value >= 1_000:
            compact_value = abs_value / 1_000
            compact_str = f"{compact_value:.1f}".rstrip("0").rstrip(".")
            formatted = f"{symbol}{compact_str}K"
        else:
            # Fall through to full formatting for small values
            compact = False

    if not compact:
        # Split into integer and fractional parts.
        rounded = round(abs_value, decimals)
        int_part = int(rounded)
        frac_part = round(rounded - int_part, decimals)

        int_str = _apply_separators(str(int_part), thousands_sep)

        if decimals > 0:
            frac_str = f"{frac_part:.{decimals}f}"[2:]  # strip "0."
            formatted = f"{symbol}{int_str}{decimal_sep}{frac_str}"
        else:
            formatted = f"{symbol}{int_str}"

    return f"-{formatted}" if negative else formatted


# ---------------------------------------------------------------------------
# format_percentage
# ---------------------------------------------------------------------------

def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format a float as a percentage string.

    Parameters
    ----------
    value:
        Numeric value expressed as a percentage (e.g. 8.2 for 8.2 %).
    decimals:
        Number of decimal places (default 1).

    Returns
    -------
    str
        e.g. "8.2%", "-3.0%", "0.0%"
    """
    return f"{value:.{decimals}f}%"


# ---------------------------------------------------------------------------
# format_delta
# ---------------------------------------------------------------------------

def format_delta(value: float, as_percentage: bool = False, decimals: int = 1) -> str:
    """
    Format a numeric delta with an explicit sign prefix.

    Parameters
    ----------
    value:
        The delta value.
    as_percentage:
        When True, appends a "%" suffix.
    decimals:
        Number of decimal places (default 1).

    Returns
    -------
    str
        e.g. "+12.3%", "-5.1%", "+0.0", "-3.2"
    """
    sign = "+" if value >= 0 else ""
    number = f"{value:.{decimals}f}"
    suffix = "%" if as_percentage else ""
    return f"{sign}{number}{suffix}"


# ---------------------------------------------------------------------------
# truncate_text
# ---------------------------------------------------------------------------

def truncate_text(text: str, max_len: int = 100, suffix: str = "...") -> str:
    """
    Truncate *text* to *max_len* characters, appending *suffix* if trimmed.

    The total length of the returned string (including suffix) will not
    exceed *max_len*.

    Parameters
    ----------
    text:
        Input string.
    max_len:
        Maximum allowed length of the output string.
    suffix:
        Appended when truncation occurs (default "...").

    Returns
    -------
    str
        Original text if short enough, otherwise truncated text + suffix.
    """
    if len(text) <= max_len:
        return text
    cut = max_len - len(suffix)
    if cut <= 0:
        return suffix[:max_len]
    return text[:cut] + suffix


# ---------------------------------------------------------------------------
# slugify
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """
    Convert *text* into a URL-friendly slug.

    Steps applied:
    1. Unicode normalisation (NFKD) to decompose accented characters.
    2. Encode to ASCII, ignoring characters that cannot be represented.
    3. Lowercase.
    4. Replace any sequence of non-alphanumeric characters with a single dash.
    5. Strip leading/trailing dashes.

    Parameters
    ----------
    text:
        Input string, e.g. "Acme Corp S.A."

    Returns
    -------
    str
        URL-safe slug, e.g. "acme-corp-sa"
    """
    # Normalise unicode and drop combining characters.
    normalised = unicodedata.normalize("NFKD", text)
    ascii_bytes = normalised.encode("ascii", "ignore")
    ascii_str = ascii_bytes.decode("ascii")

    lowered = ascii_str.lower()

    # Remove dots that are not surrounded by digits (abbreviation dots like
    # "S.A." should vanish so that "sa" is produced, not "s-a").
    # A dot between two digits (e.g. "3.14") is kept as a separator.
    lowered = re.sub(r"(?<!\d)\.(?!\d)", "", lowered)

    # Replace runs of non-alphanumeric characters with a single dash.
    slug = re.sub(r"[^a-z0-9]+", "-", lowered)

    return slug.strip("-")
