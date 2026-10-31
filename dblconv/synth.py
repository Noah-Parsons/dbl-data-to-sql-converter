"""Generate synthetic DBL data files from SCHEMA.md, for testing only.

Every value is random: no real names, numbers or accounts. The generator also returns
the values it wrote, so a test can check that the converter reads back exactly them.
"""
import random
import string
from decimal import Decimal

from .codec import encode_alpha, encode_decimal

ALPHA = string.ascii_uppercase + string.digits + " .,-/&#"


def random_value(f, rng):
    if f.kind == "A":
        n = rng.randint(0, f.width)
        return "".join(rng.choice(ALPHA) for _ in range(n)).rstrip(" ")
    digits = min(f.width, 28)
    n = rng.randint(-(10 ** digits - 1), 10 ** digits - 1)
    if rng.random() < 0.1:
        n = rng.choice([0, 1, -1, 9, -9, 10 ** digits - 1, -(10 ** digits - 1)])
    return Decimal(n).scaleb(-f.decimals)


def synth_record(layout, rng):
    out, values = bytearray(), {}
    for f in layout.fields:
        for i in range(f.count):
            name = f.name if f.count == 1 else f"{f.name}_{i + 1}"
            if f.filler:
                out += b" " * f.width
                continue
            v = random_value(f, rng)
            values[name] = v
            out += (encode_alpha(v, f.width) if f.kind == "A"
                    else encode_decimal(v, f.width, f.decimals))
    assert len(out) == layout.length
    return bytes(out), values


def write_file(path, layout, n, seed=0, terminator=b"\r\n"):
    rng = random.Random(seed)
    expected = []
    with open(path, "wb") as fh:
        for _ in range(n):
            rec, values = synth_record(layout, rng)
            fh.write(rec + terminator)
            expected.append(values)
    return expected
