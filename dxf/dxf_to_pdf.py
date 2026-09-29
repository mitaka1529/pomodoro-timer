"""Plot a DXF drawing to an A3 PDF at 1:1, drawing all text with the single-stroke
Hershey Roman Simplex font (the design romans.shx is based on) so the PDF matches a
CAD plot with thin text strokes.

usage: python dxf_to_pdf.py IN.dxf OUT.pdf [--paper A3|A4] [--text-lw 0.18]
"""
import argparse
import math
import re
from functools import lru_cache

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from ezdxf import bbox
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from HersheyFonts import HersheyFonts

_HF = HersheyFonts()
_HF.load_default_font("rowmans")
CAP, BASE = 21.0, 9.0          # rowmans: cap height 21 units, baseline at y=9 (y grows downwards)
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}


@lru_cache(maxsize=None)
def glyph(c):
    """(segments relative to glyph origin, advance) in raw font units."""
    if c == "Ø":
        segs, adv = glyph("O")
        return segs + [((19.0, -13.0), (3.0, 11.0))], adv
    if c == "±":
        segs, adv = glyph("+")
        return [((a[0], a[1] - 3), (b[0], b[1] - 3)) for a, b in segs] + [((4.0, 9.0), (22.0, 9.0))], adv
    if c in "µμ":
        segs, adv = glyph("u")
        return segs + [((4.0, -5.0), (4.0, 16.0))], adv
    if c == "°":
        pts = [(8 + 3 * math.cos(t / 8 * 2 * math.pi), -9 + 3 * math.sin(t / 8 * 2 * math.pi)) for t in range(9)]
        return list(zip(pts, pts[1:])), 14.0
    if not (32 <= ord(c) < 127):
        c = "?"
    if c == " ":
        return [], 16.0
    segs = [tuple(map(tuple, s)) for s in _HF.lines_for_text(c + "|")]
    bar = segs[-1]
    assert bar[0][0] == bar[1][0] and {bar[0][1], bar[1][1]} == {-16, 16}, (c, bar)
    return segs[:-1], bar[0][0] - 4


def decode(s):
    s = re.sub(r"%%[cC]", "Ø", s)
    s = re.sub(r"%%[pP]", "±", s)
    s = re.sub(r"%%[dD]", "°", s)
    return re.sub(r"%%[uUoO]", "", s)


def run_advance(s):
    return sum(glyph(c)[1] for c in s)


def run_segments(s, x, y, h, wf, rot, p0):
    """Segments of string s whose baseline-left is at local (x, y) relative to p0, rotated by rot."""
    k = h / CAP
    ca, sa = math.cos(rot), math.sin(rot)
    out, cx = [], 0.0
    for c in s:
        segs, adv = glyph(c)
        for a, b in segs:
            pts = []
            for gx, gy in (a, b):
                lx = x + (cx + gx) * k * wf
                ly = y + (BASE - gy) * k
                pts.append((p0[0] + lx * ca - ly * sa, p0[1] + lx * sa + ly * ca))
            out.append(pts)
        cx += adv
    return out


def text_segments(e):
    d = e.dxf
    s = decode(d.text)
    if not s.strip():
        return []
    h = d.height
    wf = d.get("width", 1.0) or 1.0
    rot = math.radians(d.get("rotation", 0.0))
    ha, va = d.get("halign", 0), d.get("valign", 0)
    adv = run_advance(s) * h / CAP
    ins = d.insert
    ap = d.get("align_point", ins)
    if ha in (3, 5):
        dist = math.hypot(ap[0] - ins[0], ap[1] - ins[1])
        rot = math.atan2(ap[1] - ins[1], ap[0] - ins[0])
        if ha == 3:
            h = h * dist / (adv * wf) if adv else h
            adv = run_advance(s) * h / CAP
        wf = dist / adv if adv else wf
        return run_segments(s, 0, 0, h, wf, rot, (ins[0], ins[1]))
    w = adv * wf
    p = ap if (ha or va) else ins
    x = {0: 0, 1: -w / 2, 2: -w, 4: -w / 2}.get(ha, 0)
    y = {0: 0, 1: 0.33 * h, 2: -h / 2, 3: -h}.get(va, 0)
    if ha == 4:
        y = -h / 2
    return run_segments(s, x, y, h, wf, rot, (p[0], p[1]))


def mtext_lines(text, h0):
    """Parse MTEXT content into lines of runs: (str, height, wf, dy, stacked_parts)."""
    lines, runs = [], []
    stack = [(h0, 1.0)]
    i, buf = 0, ""

    def flush():
        nonlocal buf
        if buf:
            runs.append(("t", buf, stack[-1][0], stack[-1][1]))
            buf = ""

    while i < len(text):
        c = text[i]
        if c == "\\" and i + 1 < len(text):
            n = text[i + 1]
            if n in "\\{}":
                buf += n
                i += 2
                continue
            if n == "P":
                flush()
                lines.append(runs)
                runs = []
                i += 2
                continue
            j = text.find(";", i)
            if n in "LlOoKk":
                i += 2
                continue
            arg = text[i + 2:j] if j >= 0 else ""
            flush()
            if n == "H":
                h, wf = stack[-1]
                stack[-1] = (h * float(arg[:-1]) if arg.endswith(("x", "X")) else float(arg), wf)
            elif n == "W":
                h, wf = stack[-1]
                stack[-1] = (h, float(arg.rstrip("xX")))
            elif n == "S":
                m = re.split(r"[\^/#]", arg, maxsplit=1)
                runs.append(("s", (m[0], m[1] if len(m) > 1 else ""), stack[-1][0], stack[-1][1]))
            i = j + 1 if j >= 0 else len(text)
            continue
        if c == "{":
            flush()
            stack.append(stack[-1])
        elif c == "}":
            flush()
            if len(stack) > 1:
                stack.pop()
        else:
            buf += c
        i += 1
    flush()
    lines.append(runs)
    return lines


def mtext_segments(e):
    d = e.dxf
    h0 = d.char_height
    lines = mtext_lines(decode(e.text), h0)
    rot = math.radians(d.get("rotation", 0.0))
    if d.hasattr("text_direction"):
        td = d.text_direction
        rot = math.atan2(td[1], td[0])

    def run_w(r):
        kind, s, h, wf = r
        if kind == "t":
            return run_advance(s) * h / CAP * wf
        return max(run_advance(s[0]), run_advance(s[1])) * h / CAP * wf + 0.3 * h0

    widths = [sum(run_w(r) for r in ln) for ln in lines]
    pitch = 5.0 / 3.0 * h0 * d.get("line_spacing_factor", 1.0)
    total_h = h0 + pitch * (len(lines) - 1)
    ap = d.get("attachment_point", 1)
    col, row = (ap - 1) % 3, (ap - 1) // 3
    top = {0: 0.0, 1: total_h / 2, 2: total_h}[row]
    segs = []
    for li, (ln, w) in enumerate(zip(lines, widths)):
        x = {0: 0.0, 1: -w / 2, 2: -w}[col]
        y = top - h0 - li * pitch
        for r in ln:
            kind, s, h, wf = r
            if kind == "t":
                segs += run_segments(s, x, y, h, wf, rot, (d.insert[0], d.insert[1]))
            else:
                up, lo = s
                x += 0.3 * h0
                segs += run_segments(up.strip(), x, y + 0.55 * h0, h, wf, rot, (d.insert[0], d.insert[1]))
                segs += run_segments(lo.strip(), x, y - 0.1 * h0, h, wf, rot, (d.insert[0], d.insert[1]))
                x -= 0.3 * h0
            x += run_w(r)
    return segs


def iter_texts(doc, entities, hidden_layers):
    for e in entities:
        if e.dxf.get("layer", "0") in hidden_layers or e.dxf.get("invisible", 0):
            continue
        t = e.dxftype()
        if t == "INSERT":
            yield from iter_texts(doc, e.virtual_entities(), hidden_layers)
            yield from iter_texts(doc, e.attribs, hidden_layers)
        elif t == "DIMENSION":
            yield from iter_texts(doc, e.virtual_entities(), hidden_layers)
        elif t in ("TEXT", "ATTRIB"):
            if t == "ATTRIB" and e.is_invisible:
                continue
            yield e
        elif t == "MTEXT":
            yield e


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--paper", default="A3")
    ap.add_argument("--text-lw", type=float, default=0.18, help="text stroke width in mm")
    a = ap.parse_args()
    pw, ph = {"A3": (420, 297), "A4": (297, 210)}[a.paper]

    doc = ezdxf.readfile(a.src)
    msp = doc.modelspace()
    hidden = {l.dxf.name for l in doc.layers if l.is_off() or l.is_frozen()}

    fig = plt.figure(figsize=(pw / 25.4, ph / 25.4))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ctx = RenderContext(doc)
    fe = Frontend(ctx, MatplotlibBackend(ax, adjust_figure=False),
                  config=Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.BLACK))

    def hide_text(entity, props):
        if entity.dxftype() in TEXT_TYPES:
            props.is_visible = False

    fe.push_property_override_function(hide_text)
    fe.draw_layout(msp, finalize=False)

    segs = []
    for e in iter_texts(doc, msp, hidden):
        segs += mtext_segments(e) if e.dxftype() == "MTEXT" else text_segments(e)
    ax.add_collection(LineCollection(segs, colors="black", linewidths=a.text_lw * 72 / 25.4,
                                     capstyle="round", joinstyle="round"))

    ext = bbox.extents(msp)
    cx, cy = (ext.extmin.x + ext.extmax.x) / 2, (ext.extmin.y + ext.extmax.y) / 2
    ax.set_xlim(cx - pw / 2, cx + pw / 2)
    ax.set_ylim(cy - ph / 2, cy + ph / 2)
    ax.set_aspect("equal", adjustable="box")
    fig.savefig(a.out, facecolor="white")
    print("saved", a.out)


if __name__ == "__main__":
    main()
