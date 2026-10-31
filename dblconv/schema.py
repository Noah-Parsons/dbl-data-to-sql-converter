"""Read the record layouts in SCHEMA.md (produced by dibol-analysis/tools-fdparse.py).

SCHEMA.md lists, for each .FD/.FDC file, one or more record layouts. Each layout is a
table of fields with their byte offset, name, DBL type (for example A25, D8 or the
array 18D7) and, where the source declared one, a precision such as D10.2 (two
implied decimal places).
"""
import re
from dataclasses import dataclass, field

TYPE_RE = re.compile(r"^(\d*)([AaDd])(\d+)$")
PREC_RE = re.compile(r"^[Dd](\d+)\.(\d+)$")
FILE_RE = re.compile(r"^## (\S+)\s*$")
REC_RE = re.compile(r"^### (.+?) - (RECORD|COMMON|GROUP)\b(.*)$")
ROW_RE = re.compile(r"^\| (\d+) \|")


@dataclass
class Field:
    name: str          # field name, or FILLERnnn for unnamed fillers
    offset: int        # byte offset of the first element
    kind: str          # 'A' (alpha) or 'D' (decimal)
    width: int         # width of one element in bytes
    count: int = 1     # number of elements (18 for 18D7)
    decimals: int = 0  # implied decimal places (D10.2 -> 2)
    filler: bool = False
    description: str = ""

    @property
    def size(self):
        return self.width * self.count


@dataclass
class Layout:
    source: str        # the .FD/.FDC file it came from
    name: str          # record name, or "overlay N"
    kind: str          # RECORD, COMMON or GROUP
    fields: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    title: str = ""    # the description line under the heading, if any

    @property
    def length(self):
        return sum(f.size for f in self.fields)

    @property
    def key(self):
        return f"{self.source}:{self.name}"


def parse_schema(path):
    """Return a list of Layout objects, in the order SCHEMA.md gives them."""
    layouts, source, cur = [], None, None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = FILE_RE.match(line)
        if m:
            source, cur = m.group(1), None
            continue
        m = REC_RE.match(line)
        if m and source:
            name = m.group(1).strip()
            if name.startswith("(overlay"):
                name = "overlay " + name.strip("()").split()[-1]
            cur = Layout(source=source, name=name, kind=m.group(2))
            layouts.append(cur)
            continue
        if (cur is not None and not cur.fields and not cur.title and line.strip()
                and not line.lstrip().startswith("|")):
            cur.title = line.strip()
            continue
        if cur is not None and ROW_RE.match(line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            off, fname, ftype, prec = int(cells[0]), cells[1], cells[2], cells[3]
            desc = cells[5] if len(cells) > 5 else ""
            t = TYPE_RE.match(ftype)
            if not t:
                cur.notes.append(f"unrecognised type {ftype!r} for {fname}")
                continue
            count = int(t.group(1)) if t.group(1) else 1
            kind, width = t.group(2).upper(), int(t.group(3))
            decimals = 0
            p = PREC_RE.match(prec)
            if kind == "D" and p:
                if int(p.group(1)) == width:
                    decimals = int(p.group(2))
                else:
                    cur.notes.append(
                        f"{fname}: precision {prec} does not match width {width}; ignored")
            filler = fname.startswith("*(filler")
            if filler:
                fname = f"FILLER{off:04d}"
            cur.fields.append(Field(fname, off, kind, width, count, decimals, filler, desc))
    for lay in layouts:
        expect = 0
        for f in lay.fields:
            if f.offset != expect:
                lay.notes.append(f"{f.name}: offset {f.offset}, expected {expect}")
            expect = f.offset + f.size
        seen = {}
        for f in lay.fields:
            if f.name in seen:
                seen[f.name] += 1
                f.name = f"{f.name}_{seen[f.name]}"
            else:
                seen[f.name] = 1
    return layouts


def find_layout(layouts, spec):
    """Find a layout by 'FILE:RECORD', or by record name if that is unique."""
    if ":" in spec:
        hits = [l for l in layouts if l.key.upper() == spec.upper()]
    else:
        hits = [l for l in layouts if l.name.upper() == spec.upper()]
    if not hits:
        raise KeyError(f"no layout named {spec!r}")
    if len(hits) > 1:
        raise KeyError(f"{spec!r} is ambiguous: " + ", ".join(h.key for h in hits))
    return hits[0]
