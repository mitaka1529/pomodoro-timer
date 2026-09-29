"""Per-drawing touch-ups applied after autotranslate (partial strike-throughs etc.)."""
import re

from autotranslate import tw, mtext_plain


def _mtext_span(e, sub):
    m = re.match(r"^\{\\W([\d.]+);", e.text)
    wf = float(m.group(1)) if m else 1.0
    plain = mtext_plain(e.text)
    k = plain.find(sub)
    h = e.dxf.char_height
    x0 = e.dxf.insert.x + tw(plain[:k], h) * wf
    return x0, x0 + tw(sub, h) * wf, e.dxf.insert.y - h, e.dxf.insert.y


def strike_substring(msp, prefix, sub):
    e = next(t for t in msp.query("MTEXT") if mtext_plain(t.text).startswith(prefix))
    x0, x1, yb, yt = _mtext_span(e, sub)
    for ln in msp.query("LINE"):
        s, t = ln.dxf.start, ln.dxf.end
        if abs(s.y - t.y) < 0.01 and yb + 0.1 < s.y < yt + 0.3 and max(s.x, t.x) > e.dxf.insert.x:
            ln.dxf.start, ln.dxf.end = (x0 - 0.3, s.y, 0), (x1 + 0.3, s.y, 0)
    return e, x0, x1


def fix_154_01_21310_3(doc):
    msp = doc.modelspace()
    strike_substring(msp, "MATERIAL STKM11A", "SEAMLESS, PICKLED (BRIGHT ANNEALED)")
    e, x0, x1 = strike_substring(msp, "RAW TUBE SIZE", "x 36±0.1")
    corr = next(t for t in msp.query("MTEXT") if t.text.strip() == "39")
    h = e.dxf.char_height
    xs = x0 + (x1 - x0) * 0.6 - tw("39", corr.dxf.char_height) / 2
    dx = xs - corr.dxf.insert.x
    for ins in msp.query("INSERT"):
        p = ins.dxf.insert
        if abs(p.y - corr.dxf.insert.y) < 4 and 0 < p.x - corr.dxf.insert.x < 12:
            ins.translate(dx, 0, 0)
    corr.dxf.insert = (xs, corr.dxf.insert.y, 0)


FIXES = {"154-01-21310-3": fix_154_01_21310_3}


def apply(name, doc):
    f = FIXES.get(name)
    if f:
        f(doc)
