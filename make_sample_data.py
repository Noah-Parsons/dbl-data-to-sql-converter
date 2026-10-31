"""Write a folder of synthetic DBL data files for trying the converter.

    python make_sample_data.py "Sample data"

Every value is random. The folder shows each case the converter handles: relative files
with a control record and unused slots, an ISLOAD unload (.SEQ), a file whose name does not
identify its layout, and an ISAM file that still needs unloading.
"""
import os
import random
import sys

from dblconv.batch import default_schema
from dblconv.schema import find_layout, parse_schema
from dblconv.synth import synth_record

FILES = [  # file name, layout, records, unused slots, has control record
    ("AR01SALC.DDF", "SALCT", 40, 5, True),
    ("PR01PB15.DDF", "PB15.FD:PCHLG", 25, 3, True),
    ("GL01GLAMS.SEQ", "GLAMS.FD:GLAMS", 30, 0, False),
    ("XX01UNKN.DDF", "GLDIS.FD:GLDIS", 12, 0, True),
]


def main(folder):
    layouts = parse_schema(default_schema())
    os.makedirs(folder, exist_ok=True)
    rng = random.Random(2026)
    for name, spec, n, slots, control in FILES:
        lay = find_layout(layouts, spec)
        with open(os.path.join(folder, name), "wb") as fh:
            if control:
                fh.write(b"0" * lay.length + b"\r\n")
            for _ in range(n):
                fh.write(synth_record(lay, rng)[0] + b"\r\n")
            for _ in range(slots):
                fh.write(b"]" * lay.length + b"\r\n")
    with open(os.path.join(folder, "AR01ARCU.ISM"), "wb") as fh:
        fh.write(b"\0" * 512)            # stands in for an ISAM file; never read
    print(f"Wrote {len(FILES) + 1} synthetic files to {os.path.abspath(folder)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "Sample data")
