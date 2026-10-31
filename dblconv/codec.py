"""Decode and encode DBL alpha and decimal fields.

Synergy/DE documents decimal data as "signed, whole numbers that consist of ASCII
numeric characters", where a negative sign takes no storage: "the sign is stored in
the right-most digit with a 'p' through 'y', corresponding to 0 through 9". Implied
decimal places (d10.2) take no storage either.
Source: https://www.synergex.com/docs/lrm/lrmChap2Datatypes.htm
"""
from decimal import Decimal

NEG = "pqrstuvwxy"   # p = -0 ... y = -9 in the right-most digit


class DecodeError(ValueError):
    pass


def decode_alpha(raw: bytes) -> str:
    """Alpha fields are fixed width; trailing spaces are padding."""
    return raw.decode("latin-1").rstrip(" ")


def decode_decimal(raw: bytes, decimals: int = 0):
    """Return a Decimal, or None for an all-blank field.

    Leading blanks are accepted as zeros, since DBL writes unset numeric fields as
    blanks in some files. Anything else that is not a digit (or a sign digit in the
    last place) raises DecodeError.
    """
    s = raw.decode("latin-1")
    if s.strip() == "":
        return None
    body, last = s[:-1], s[-1]
    negative = False
    if last in NEG:
        negative, last = True, str(NEG.index(last))
    elif not last.isdigit():
        raise DecodeError(f"bad last character {last!r} in {s!r}")
    body = body.replace(" ", "0")
    if not body.isdigit() and body != "":
        raise DecodeError(f"non-digit in {s!r}")
    value = Decimal(body + last)
    if decimals:
        value = value.scaleb(-decimals)
    return -value if negative else value


def encode_alpha(value: str, width: int) -> bytes:
    b = value.encode("latin-1")
    if len(b) > width:
        raise ValueError(f"{value!r} longer than {width}")
    return b.ljust(width, b" ")


def encode_decimal(value, width: int, decimals: int = 0) -> bytes:
    """Encode a Decimal (or int) the way DBL stores it: zero-padded digits, with a
    negative sign folded into the last digit."""
    value = Decimal(value)
    scaled = value.scaleb(decimals)
    if scaled != scaled.to_integral_value():
        raise ValueError(f"{value} has more than {decimals} decimal places")
    n = int(scaled)
    digits = str(abs(n)).rjust(width, "0")
    if len(digits) > width:
        raise ValueError(f"{value} does not fit in D{width}.{decimals}")
    if n < 0:
        digits = digits[:-1] + NEG[int(digits[-1])]
    return digits.encode("ascii")
