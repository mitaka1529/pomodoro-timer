"""Translate the Japanese text of a DXF drawing to English and fit it into the free
space around each original text (no overlaps with geometry or other text).

usage: python autotranslate.py IN.dxf OUT.dxf REPORT.json
Needs glossary.py (dict G: normalized Japanese -> English) next to this file.
"""
import json
import math
import re
import sys
import unicodedata

import ezdxf
from ezdxf import bbox as ezbbox
from ezdxf.math import Matrix44, Vec3

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from glossary import G  # noqa: E402

ST = "ROMANS_EN"
WF = 0.80
MIN_WF = 0.62
MIN_H = 1.8
JP = re.compile(r"[⅐-↏　-ヿ一-鿿＀-￯㈀-㏿①-⓿]")
CIRC = {c: f"({i})" for i, c in enumerate("①②③④⑤⑥⑦⑧⑨", 1)}
HEADINGS = {"SPECIFICATIONS", "NOTES", "SECTION VIEW", "%%USECTION VIEW", "SECTION A-A", "MEASUREMENT METHOD",
            "ASSEMBLY METHOD (SCALE: FREE)", "DETAIL A"}
TITLE_BLOCK_HINTS = ("waku", "title", "a4bg", "a3bg", "zuwaku")

# ---------------------------------------------------------------- romans.shx metrics
_HW = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [18, 21, 21, 21, 19, 18, 21, 22, 8, 16, 21, 17, 24, 22, 22, 21, 22, 21, 20, 16, 22, 18, 24, 20, 18, 20]))
_HW.update(dict(zip("abcdefghijklmnopqrstuvwxyz", [19, 19, 18, 19, 18, 12, 19, 19, 8, 10, 17, 8, 30, 19, 19, 19, 19, 13, 17, 12, 19, 16, 22, 17, 16, 17])))
_HW.update({c: 20 for c in "0123456789"})
_HW.update({" ": 16, ".": 10, ",": 10, ":": 10, ";": 10, "(": 14, ")": 14, "-": 26, "/": 22, "+": 26, "±": 26,
            "Ø": 22, "%": 24, "*": 16, "'": 10, "=": 26, "µ": 19, "°": 14, "<": 24, ">": 24, '"': 16, "~": 24,
            "!": 10, "?": 18, "#": 21, "&": 26, "[": 14, "]": 14, "_": 16, "x": 17})


def decode(s):
    s = re.sub(r"%%[cC]", "Ø", s)
    s = re.sub(r"%%[pP]", "±", s)
    s = re.sub(r"%%[dD]", "°", s)
    return re.sub(r"%%[uUoO]", "", s)


def tw(s, h):
    return sum(_HW.get(c, 22) for c in decode(s)) / 21.0 * h * 1.03


def mtext_plain(s):
    s = re.sub(r"\\S([^;]*);", lambda m: max(re.split(r"[\^/#]", m.group(1)), key=len), s)
    s = re.sub(r"\\[A-Za-z][^;\\{}]*;", "", s)
    return s.replace("{", "").replace("}", "")


def mtext_lines_w(s, h):
    return max(tw(ln, h) for ln in mtext_plain(s).split("\\P"))


def norm(s):
    for k, v in CIRC.items():
        s = s.replace(k, v)
    s = s.replace("　", " ")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("×", "x").replace("℃", "%%dC").replace("°C", "%%dC").replace("μ", "µ")
    return re.sub(r" {2,}", " ", s).strip()


def translate(s):
    n = norm(s)
    if JP.search(n):
        return G[n]
    return n


def orig_width(s, h, wf):
    """Rough width of the original (txt.shx + extfont2 bigfont) text."""
    w = 0.0
    for c in decode(s):
        if c == " ":
            w += 0.67
        elif ord(c) > 0x2000:
            w += 1.2
        else:
            w += 0.85
    return w * h * wf


def lead_offset(s, h, wf):
    m = re.match(r"[ 　]*", s)
    return orig_width(m.group(0), h, wf) if m else 0.0


def new_height(h, en, in_title):
    if in_title:
        return min(h, 2.5)
    if en in HEADINGS:
        return min(h, 3.5)
    if h >= 5:
        return 3.5
    if h >= 4:
        return 3.0
    if h >= 3:
        return 2.5
    if h >= 2.5:
        return 2.2
    return max(1.5, round(h * 0.9, 2))


# ---------------------------------------------------------------- geometry
class Scene:
    """World-space obstacles: segments and text boxes."""

    def __init__(self, doc):
        self.doc = doc
        self.hidden = {l.dxf.name for l in doc.layers if l.is_off() or l.is_frozen() or not l.dxf.get("plot", 1)}
        self.hidden.add("DEFPOINTS")
        self.segs = []            # (x1,y1,x2,y2, owner_id)
        self.boxes = {}           # id -> (x0,y0,x1,y1, rot, anchor) world oriented box as 4 corners
        self.texts = []           # (entity, matrix, layout_key)

    def add_entity(self, e, m, oid):
        t = e.dxftype()
        if e.dxf.get("layer", "0") in self.hidden:
            return
        if t in ("TEXT", "ATTRIB", "MTEXT"):
            self.texts.append((e, m, oid))
            return
        if t in ("XLINE", "RAY", "POINT", "ATTDEF", "VIEWPORT"):
            return
        try:
            v = e.copy()
            if m is not None:
                v.transform(m)
        except Exception:
            return
        pts_list = []
        try:
            if t == "LINE":
                pts_list = [[v.dxf.start, v.dxf.end]]
            elif t in ("ARC", "CIRCLE", "ELLIPSE", "SPLINE"):
                if t == "CIRCLE":
                    v = v.to_ellipse()
                pts_list = [list(v.flattening(0.05))]
            elif t in ("LWPOLYLINE", "POLYLINE"):
                from ezdxf import path
                pts_list = [list(path.make_path(v).flattening(0.05))]
            elif t == "HATCH":
                from ezdxf import path
                pts_list = [list(p.flattening(0.05)) for p in path.from_hatch(v)]
            elif t in ("SOLID", "TRACE", "3DFACE"):
                vs = v.wcs_vertices() if hasattr(v, "wcs_vertices") else v.vertices()
                pts_list = [list(vs) + [vs[0]]]
            elif t == "OLE2FRAME":
                b = ezbbox.extents([v])
                if b.has_data:
                    x0, y0, x1, y1 = b.extmin.x, b.extmin.y, b.extmax.x, b.extmax.y
                    pts_list = [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
        except Exception:
            return
        for pts in pts_list:
            for a, b in zip(pts, pts[1:]):
                self.segs.append((a[0], a[1], b[0], b[1], oid))

    def walk(self, entities, m, depth=0):
        for e in entities:
            t = e.dxftype()
            if e.dxf.get("layer", "0") in self.hidden:
                continue
            if t == "INSERT":
                blk = self.doc.blocks.get(e.dxf.name)
                if blk is None:
                    continue
                mm = e.matrix44() if m is None else e.matrix44() @ m
                self.walk(blk, mm, depth + 1)
                for a in e.attribs:
                    self.add_entity(a, None, id(a))
            elif t == "DIMENSION":
                blk = self.doc.blocks.get(e.dxf.geometry) if e.dxf.hasattr("geometry") else None
                if blk is not None:
                    self.walk(blk, m, depth + 1)
            else:
                self.add_entity(e, m, id(e))


def text_frame(e, m):
    """(anchor Vec3 world, rotation rad, scale) of a TEXT/MTEXT under matrix m."""
    d = e.dxf
    if e.dxftype() == "MTEXT":
        p = Vec3(d.insert)
        rot = math.radians(d.get("rotation", 0.0))
        if d.hasattr("text_direction"):
            td = d.text_direction
            rot = math.atan2(td[1], td[0])
    else:
        ha, va = d.get("halign", 0), d.get("valign", 0)
        p = Vec3(d.align_point) if (ha or va) and ha not in (3, 5) else Vec3(d.insert)
        rot = math.radians(d.get("rotation", 0.0))
    s = 1.0
    if m is not None:
        p = m.transform(p)
        ux = m.transform_direction(Vec3(math.cos(rot), math.sin(rot), 0))
        rot = math.atan2(ux.y, ux.x)
        s = ux.magnitude
    return p, rot, s


def to_local(x, y, p, rot):
    c, s = math.cos(-rot), math.sin(-rot)
    dx, dy = x - p.x, y - p.y
    return dx * c - dy * s, dx * s + dy * c


def blocking(scene, p, rot, y0, y1, exclude):
    """x-intervals (text-local) blocked inside band y0..y1."""
    out = []
    for x1, y1_, x2, y2, oid in scene.segs:
        if oid in exclude:
            continue
        a = to_local(x1, y1_, p, rot)
        b = to_local(x2, y2, p, rot)
        if max(a[1], b[1]) < y0 or min(a[1], b[1]) > y1:
            continue
        if abs(b[1] - a[1]) < 1e-9:
            out.append((min(a[0], b[0]), max(a[0], b[0])))
            continue
        ta = (y0 - a[1]) / (b[1] - a[1])
        tb = (y1 - a[1]) / (b[1] - a[1])
        t0, t1 = max(0.0, min(ta, tb)), min(1.0, max(ta, tb))
        xa = a[0] + (b[0] - a[0]) * t0
        xb = a[0] + (b[0] - a[0]) * t1
        out.append((min(xa, xb), max(xa, xb)))
    for oid, corners in scene.boxes.items():
        if oid in exclude:
            continue
        loc = [to_local(x, y, p, rot) for x, y in corners]
        ys = [q[1] for q in loc]
        if max(ys) < y0 or min(ys) > y1:
            continue
        xs = [q[0] for q in loc]
        out.append((min(xs), max(xs)))
    return out


def free_interval(blocks, seed_lo, seed_hi, lim=400.0):
    """Largest interval containing [seed_lo, seed_hi] free of blocks; None if the seed is blocked."""
    lo, hi = -lim, lim
    for a, b in blocks:
        if b < seed_lo:
            lo = max(lo, b)
        elif a > seed_hi:
            hi = min(hi, a)
        else:
            return None
    return lo, hi


def safe_layout(e):
    if e.dxftype() == "ATTRIB":
        return None
    try:
        return e.get_layout()
    except Exception:
        return None


def box_corners(p, rot, x0, y0, x1, y1):
    c, s = math.cos(rot), math.sin(rot)
    return [(p.x + x * c - y * s, p.y + x * s + y * c) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]


# ---------------------------------------------------------------- main fitter
class Fitter:
    def __init__(self, doc, root=None, report=None, tag=None):
        self.doc = doc
        self.msp = doc.modelspace()
        self.root = root if root is not None else self.msp
        self.tag = tag
        if ST not in doc.styles:
            doc.styles.add(ST, font="romans.shx")
        self.scene = Scene(doc)
        self.scene.walk(self.root, None)
        self.report = report if report is not None else []
        self.used_blocks = self._used_blocks()
        # original boxes of all texts as obstacles
        for e, m, oid in self.scene.texts:
            raw = e.text if e.dxftype() == "MTEXT" else e.dxf.text
            if not mtext_plain(raw).replace("\\P", "").strip():
                continue
            self.scene.boxes[oid] = self._orig_box(e, m)

    def _used_blocks(self):
        used = {}

        def walk(layout, m):
            for e in layout.query("INSERT"):
                mm = e.matrix44() if m is None else e.matrix44() @ m
                used.setdefault(e.dxf.name, []).append(mm)
                b = self.doc.blocks.get(e.dxf.name)
                if b is not None:
                    walk(b, mm)
            for e in layout.query("DIMENSION"):
                if e.dxf.hasattr("geometry"):
                    used.setdefault(e.dxf.geometry, []).append(m)
        walk(self.msp, None)
        return used

    def _orig_box(self, e, m):
        p, rot, s = text_frame(e, m)
        d = e.dxf
        if e.dxftype() == "MTEXT":
            h = d.char_height * s
            w = max(orig_width(ln, h, 1.0) for ln in mtext_plain(e.text).split("\\P"))
            nlines = e.text.count("\\P") + 1
            H = h * (1 + 1.667 * (nlines - 1))
            ap = d.get("attachment_point", 1)
            col, row = (ap - 1) % 3, (ap - 1) // 3
            x0 = {0: 0, 1: -w / 2, 2: -w}[col]
            y1 = {0: 0, 1: H / 2, 2: H}[row]
            return box_corners(p, rot, x0, y1 - H, x0 + w, y1)
        h = d.height * s
        wf = d.get("width", 1.0) or 1.0
        txt = d.text
        if JP.search(txt) or ord(max(txt or " ")) > 0x2000:
            w = orig_width(txt, h, wf)
        else:
            w = tw(txt, h) * wf
        ha, va = d.get("halign", 0), d.get("valign", 0)
        if ha in (3, 5):
            a = Vec3(d.insert)
            b = Vec3(d.align_point)
            if m is not None:
                a, b = m.transform(a), m.transform(b)
            w = (b - a).magnitude
            return box_corners(p, rot, 0, 0, w, h)
        x0 = {0: 0, 1: -w / 2, 2: -w, 4: -w / 2}.get(ha, 0)
        y0 = -h / 2 if (ha == 4 or va == 2) else (-h if va == 3 else 0)
        return box_corners(p, rot, x0, y0, x0 + w, y0 + h)

    # ------------------------------------------------------------------
    def attached_lines(self, e, m, p, rot, x0, x1, y0, h):
        """Underlines / strike-throughs belonging to the text (same owner layout)."""
        layout = safe_layout(e)
        res = []
        if layout is None:
            return res
        for ln in layout.query("LINE"):
            a, b = Vec3(ln.dxf.start), Vec3(ln.dxf.end)
            if m is not None:
                a, b = m.transform(a), m.transform(b)
            la, lb = to_local(a.x, a.y, p, rot), to_local(b.x, b.y, p, rot)
            if abs(la[1] - lb[1]) > 0.05:
                continue
            y = la[1]
            lo, hi = min(la[0], lb[0]), max(la[0], lb[0])
            ov = min(hi, x1) - max(lo, x0)
            if y0 - 2.2 <= y <= y0 - 0.15 and ov >= 0.6 * (x1 - x0):
                res.append(("under", ln, lo, hi))
            elif y0 + 0.15 * h <= y <= y0 + 0.85 * h and ov >= 0.15 * (x1 - x0) and lo > x0 - 3 and hi < x1 + 3:
                res.append(("strike", ln, lo, hi))
        return res

    def move_endpoint(self, ln, old_world, new_world, m):
        inv = m.copy() if m is not None else None
        if inv is not None:
            inv.inverse()
        layout = ln.get_layout()
        old_l = inv.transform(Vec3(old_world)) if inv else Vec3(old_world)
        new_l = inv.transform(Vec3(new_world)) if inv else Vec3(new_world)
        for other in layout.query("LINE"):
            for attr in ("start", "end"):
                if Vec3(other.dxf.get(attr)).isclose(old_l, abs_tol=0.02):
                    other.dxf.set(attr, new_l)

    def find_riders(self, e, m, rot, ox0, oy0, h, wf, src, en):
        """Small superscript texts and in-line symbols that must move with the text."""
        out = []
        if abs(rot) > 1e-3:
            return out
        p = text_frame(e, m)[0]
        x_org = p.x + ox0
        y_org = p.y + oy0
        W = orig_width(src, h, wf)
        for t in self.msp.query("TEXT"):
            if t is e or JP.search(t.dxf.text) or len(t.dxf.text.strip()) > 3 or t.dxf.height > 0.75 * h:
                continue
            tx, ty = t.dxf.insert.x - x_org, t.dxf.insert.y - y_org
            if not (0 <= tx <= W * 1.2 + h and 0.2 * h <= ty <= 1.3 * h):
                continue
            toks = [t_ for t_ in re.findall(r"[\dx.]+", norm(src)) if t_.endswith("10")]
            if not toks:
                continue
            tok = toks[-1]
            if tok not in en:
                continue
            out.append({"kind": "sup", "ent": t, "token": tok, "dy": ty, "oids": {id(t)}})
        if "{GAP}" in en:
            mg = re.search(r"\S((?:\u3000){2,}| {3,})", src)
            if mg:
                ymin_ok = y_org - 1.5 - h
                gx0 = x_org + orig_width(src[:mg.start(1)], h, wf)
                gx1 = gx0 + orig_width(mg.group(1), h, wf)
                ents = []
                for g in self.msp:
                    if g.dxftype() in ("INSERT", "DIMENSION") or g is e:
                        continue
                    if g.dxftype() in ("TEXT", "MTEXT"):
                        gh = g.dxf.char_height if g.dxftype() == "MTEXT" else g.dxf.height
                        if gh > 0.8 * h:
                            continue
                    b = ezbbox.extents([g])
                    if b.has_data and gx0 - 3 <= b.center.x <= gx1 + 3 and b.size.x <= (gx1 - gx0) + 8 and b.extmin.y >= ymin_ok and b.extmax.y <= y_org + h + 1.5:
                        ents.append(g)
                if ents:
                    b = ezbbox.extents(ents)
                    out.append({"kind": "gap", "ents": ents, "x0": b.extmin.x, "w": b.size.x, "oids": {id(g) for g in ents}})
        return out

    def _find_rect(self, tx0, ty0, tx1, ty1):
        def ok(bx0, by0, bx1, by1):
            return (bx0 <= tx0 + 1 and bx1 >= tx1 - 1 and 0 <= ty0 - by0 < 3.5 and 0 <= by1 - ty1 < 3.5
                    and bx1 - bx0 <= (tx1 - tx0) + 12)
        for pl in self.msp.query("LWPOLYLINE"):
            pts = [(round(x, 4), round(y, 4)) for x, y in pl.get_points("xy")]
            if len(pts) == 5 and pts[0] == pts[-1]:
                pts = pts[:4]
            if len(pts) != 4 or not (pl.closed or True):
                continue
            xs, ys = sorted({x for x, _ in pts}), sorted({y for _, y in pts})
            if len(xs) != 2 or len(ys) != 2 or not ok(xs[0], ys[0], xs[1], ys[1]):
                continue

            def apply(nx0, nx1, pl=pl, xs=xs):
                raw = list(pl.get_points("xyseb"))
                out = []
                for q in raw:
                    x = nx0 if abs(q[0] - xs[0]) < 1e-3 else (nx1 if abs(q[0] - xs[1]) < 1e-3 else q[0])
                    out.append((x,) + tuple(q[1:]))
                pl.set_points(out, format="xyseb")
            return xs[0], ys[0], xs[1], ys[1], {id(pl)}, apply
        lines = list(self.msp.query("LINE"))
        H = [l for l in lines if abs(l.dxf.start.y - l.dxf.end.y) < 0.01]
        V = [l for l in lines if abs(l.dxf.start.x - l.dxf.end.x) < 0.01]
        for top in H:
            for bot in H:
                bx0, bx1 = min(top.dxf.start.x, top.dxf.end.x), max(top.dxf.start.x, top.dxf.end.x)
                if bot is top or abs(min(bot.dxf.start.x, bot.dxf.end.x) - bx0) > 0.05 or abs(max(bot.dxf.start.x, bot.dxf.end.x) - bx1) > 0.05:
                    continue
                by0, by1 = bot.dxf.start.y, top.dxf.start.y
                if not ok(bx0, by0, bx1, by1):
                    continue
                side = lambda x: [l for l in V if abs(l.dxf.start.x - x) < 0.05 and min(l.dxf.start.y, l.dxf.end.y) <= by0 + 0.05 and max(l.dxf.start.y, l.dxf.end.y) >= by1 - 0.05]
                L, R = side(bx0), side(bx1)
                if not L or not R:
                    continue

                def apply(nx0, nx1, top=top, bx0=bx0, bx1=bx1, by0=by0, by1=by1):
                    for old, new in (((bx0, by0), (nx0, by0)), ((bx0, by1), (nx0, by1)), ((bx1, by0), (nx1, by0)), ((bx1, by1), (nx1, by1))):
                        if old != new:
                            self.move_endpoint(top, Vec3(*old), Vec3(*new), None)
                return bx0, by0, bx1, by1, {id(top), id(bot), id(L[0]), id(R[0])}, apply
        return None

    def try_box(self, e, oid):
        """Text framed by its own rectangle (e.g. MANUFACTURING DRAWING): widen the box to fit."""
        if e.dxftype() != "TEXT" or safe_layout(e) is None or e.dxf.owner != self.msp.layout_key:
            return False
        ob = self._orig_box(e, None)
        tx0, tx1 = min(q[0] for q in ob), max(q[0] for q in ob)
        ty0, ty1 = min(q[1] for q in ob), max(q[1] for q in ob)
        rect = self._find_rect(tx0, ty0, tx1, ty1)
        if rect is None:
            return False
        bx0, by0, bx1, by1, own_ids, apply_rect = rect
        en = translate(e.dxf.text)
        h = new_height(e.dxf.height, en, False)
        need = tw(en, h) * WF + 4.0
        own = set(own_ids) | {oid}
        p = Vec3(0, 0, 0)
        bl = blocking(self.scene, p, 0.0, by0 + 0.05, by1 - 0.05, own)
        fi = free_interval(bl, bx0 + 0.05, bx1 - 0.05) or (bx0, bx1)
        nx0, nx1 = bx0, bx1
        if need > bx1 - bx0:
            grow = need - (bx1 - bx0)
            room_l = bx0 - fi[0] - 0.5
            room_r = fi[1] - bx1 - 0.5
            gl = max(0.0, min(grow, room_l))
            gr = max(0.0, min(grow - gl, room_r))
            nx0, nx1 = bx0 - gl, bx1 + gr
        wf = min(WF, (nx1 - nx0 - 3.0) / tw(en, h))
        two = None
        bh = by1 - by0
        if wf < WF and " " in en and bh >= 5.5:
            h2 = min(h, round((bh - 1.2) / 2.3, 1))
            ls = balanced_split(en, 2, h2)
            wf2 = min(WF, (nx1 - nx0 - 3.0) / max(tw(l, h2) for l in ls))
            if h2 * math.sqrt(wf2) > h * math.sqrt(wf):
                two = (h2, wf2, ls)
        apply_rect(nx0, nx1)
        cxx, cyy = (nx0 + nx1) / 2, (by0 + by1) / 2
        MC = ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER
        if two:
            h, wf, ls = two
            pitch = 1.3 * h
            for i, t in enumerate(ls):
                tgt = e if i == 0 else e.copy()
                if i:
                    self.msp.add_entity(tgt)
                tgt.dxf.text, tgt.dxf.style, tgt.dxf.height, tgt.dxf.width, tgt.dxf.rotation = t, ST, h, wf, 0
                tgt.set_placement((cxx, cyy + pitch / 2 - i * pitch), align=MC)
            en_drawn = " / ".join(ls)
            w = max(tw(l, h) for l in ls) * wf
            self.scene.boxes[oid] = box_corners(p, 0.0, cxx - w / 2, by0 + 0.5, cxx + w / 2, by1 - 0.5)
        else:
            e.dxf.text, e.dxf.style, e.dxf.height, e.dxf.width, e.dxf.rotation = en, ST, h, wf, 0
            e.set_placement((cxx, cyy), align=MC)
            en_drawn = en
            w = tw(en, h) * wf
            self.scene.boxes[oid] = box_corners(p, 0.0, cxx - w / 2, cyy - h / 2, cxx + w / 2, cyy + h / 2)
        self.report.append({"ja": e.dxf.text, "en": en, "drawn": en_drawn, "how": f"boxed title, box widened to {nx1 - nx0:.1f} mm",
                            "h": h, "wf": round(wf, 2), "where": "body"})
        self.report[-1]["ja"] = self._last_src
        return True

    def fit_one(self, e, m, oid, in_title, block_used):
        d = e.dxf
        is_mtext = e.dxftype() == "MTEXT"
        src = e.text if is_mtext else d.text
        en = translate(src)
        p, rot, s = text_frame(e, m)
        ux = Vec3(math.cos(rot), math.sin(rot))
        uy = Vec3(-math.sin(rot), math.cos(rot))
        h_orig = (d.char_height if is_mtext else d.height) * s
        wf_orig = 1.0 if is_mtext else (d.get("width", 1.0) or 1.0)
        plain = mtext_plain(en) if is_mtext else en
        h0 = new_height(h_orig, plain, in_title)
        ob = self._orig_box(e, m)
        loc = [to_local(x, y, p, rot) for x, y in ob]
        ox0, ox1 = min(q[0] for q in loc), max(q[0] for q in loc)
        oy0, oy1 = min(q[1] for q in loc), max(q[1] for q in loc)
        oc = (oy0 + oy1) / 2
        layout = safe_layout(e)
        is_leader = is_mtext and layout is not None and layout.name.startswith("*S")
        ha = va = 0
        if is_mtext:
            ap = d.get("attachment_point", 1)
            col, row = (ap - 1) % 3, (ap - 1) // 3
            mode = {0: "L", 1: "C", 2: "R"}[col]
        else:
            ha, va = d.get("halign", 0), d.get("valign", 0)
            mode = {0: "L", 1: "C", 2: "R", 4: "C", 3: "L", 5: "L"}.get(ha, "L")
        lead = 0.0 if is_mtext else lead_offset(d.text, h_orig, wf_orig)
        start = ox0 + lead
        cx = (ox0 + ox1) / 2
        width = (lambda t, hh: mtext_lines_w(t, hh)) if is_mtext else tw
        exclude = {oid}
        note = ""
        riders = self.find_riders(e, m, rot, ox0, oy0, h_orig, wf_orig, src, en) if (block_used and m is None and (not is_mtext or "\\" not in src)) else []
        gapstr = None
        for r in riders:
            exclude |= r["oids"]
            if r["kind"] == "gap":
                n = max(3, math.ceil((r["w"] + 2.4) / (tw(" ", h0) * 0.7)))
                gapstr = " " * n
        if "{GAP}" in en:
            en = en.replace("{GAP}", gapstr or "    ")
        multiline_ok = (not is_mtext) and layout is not None and block_used and " " in en and "\\P" not in en and not riders

        def line_avail(yb, hh, first, strict=False):
            lo_pad = -0.25 if strict else 0.3
            bl = blocking(self.scene, p, rot, yb + lo_pad, yb + hh + (0.25 if strict else 0), exclude)
            seed = {"L": (start + 0.05, start + 0.3), "C": (cx - 0.15, cx + 0.15), "R": (ox1 - 0.3, ox1 - 0.05)}[mode]
            fi = free_interval(bl, *seed) if block_used else None
            if fi is None:
                if not first:
                    return None
                return (ox0 - 0.2, ox1 + 0.2, True)
            return (fi[0] + 0.4, fi[1] - 0.4, False)

        def span(fi, need):
            lo, hi = fi[0], fi[1]
            if mode == "L":
                if is_leader and hi - start < need:
                    return max(hi - start, hi - lo)
                return hi - start
            if mode == "C":
                return 2 * min(cx - lo, hi - cx)
            return ox1 - lo

        def baselines(n, hh):
            pitch = 1.6 * hh
            if mode == "C" and n > 1:
                return [oc + ((n - 1) / 2 - i) * pitch - hh / 2 for i in range(n)]
            if mode == "C" or (ha == 4 or va == 2):
                b0 = oc - hh / 2
            elif is_mtext:
                b0 = {0: oy1 - hh, 1: oc - hh / 2, 2: oy0}[row]
            else:
                b0 = oy0 if va != 3 else oy1 - hh
            return [b0 - i * pitch for i in range(n)]

        best = None
        hh = h0
        tried_fallback = None
        while hh >= MIN_H - 1e-9:
            for n in ((1, 2, 3, 4) if multiline_ok else (1,)):
                ls = [en] if n == 1 else balanced_split(en, n, hh)
                if ls is None:
                    continue
                ybs = baselines(n, hh)
                wfs, fis, ok = [], [], True
                for i, (t, yb) in enumerate(zip(ls, ybs)):
                    fi = line_avail(yb, hh, i == 0, strict=n > 1)
                    if fi is None or (fi[2] and n > 1):
                        ok = False
                        break
                    need = width(t, hh)
                    av = max(span(fi, need * WF), (ox1 - ox0) * 0.9 if (n == 1 and fi[2]) else 0)
                    wfs.append(av / need if need else WF)
                    fis.append(fi)
                if not ok:
                    continue
                wf = min(WF, min(wfs))
                if n == 1 and tried_fallback is None:
                    tried_fallback = (hh, wf, ls, ybs, fis)
                if wf < MIN_WF:
                    continue
                score = hh * math.sqrt(wf / WF) - 0.35 * (n - 1)
                if best is None or score > best[0] + 1e-6:
                    best = (score, hh, wf, ls, ybs, fis)
            hh = round(hh - 0.1, 2)
        if best is None:
            hh = MIN_H
            ybs = baselines(1, hh)
            fi = line_avail(ybs[0], hh, True)
            need = width(en, hh)
            wf = min(WF, max(span(fi, need * WF), (ox1 - ox0) * 0.9) / need)
            best = (0, hh, wf, [en], ybs, [fi])
            how = f"reduced h={hh} wf={wf:.2f}" + (" REVIEW" if wf < 0.5 else "")
        _, h, wf, lines, ybs, fis = best
        if best[0]:
            how = "fit" if (h == h0 and wf >= WF - 1e-6 and len(lines) == 1) else f"h={h} wf={wf:.2f} lines={len(lines)}"
        if fis[0][2]:
            note = "no free space found; kept original extent"
        inv = None
        if m is not None:
            inv = m.copy()
            inv.inverse()

        def to_block(pt):
            return inv.transform(Vec3(pt)) if inv is not None else Vec3(pt)

        sc = 1.0 / s
        new_boxes = []
        if is_mtext:
            w = width(en, h) * wf
            H = h * (1 + 1.667 * en.count("\\P"))
            if mode == "L":
                x0 = start
                if is_leader and fis[0][1] - start < w:
                    x0 = max(fis[0][0], fis[0][1] - w)
                    d.insert = to_block(p + ux * x0)
            else:
                x0 = {"C": cx - w / 2, "R": ox1 - w}[mode]
            body = en
            if body.startswith("\\A"):
                m_ = re.match(r"^(\\A\d;)(.*)$", body, re.S)
                e.text = r"%s{\W%.2f;%s}" % (m_.group(1), wf, m_.group(2))
            else:
                e.text = r"{\W%.2f;%s}" % (wf, body)
            d.char_height = h * sc
            d.style = ST
            if d.hasattr("width"):
                d.width = 0
            yb = {0: oy1 - H, 1: oc - H / 2, 2: oy0}[row]
            new_boxes.append((x0, yb, x0 + w, yb + H))
        else:
            for i, (t, yb) in enumerate(zip(lines, ybs)):
                w = tw(t, h) * wf
                x0 = {"L": start, "C": cx - w / 2, "R": ox1 - w}[mode]
                target = e if i == 0 else e.copy()
                if i:
                    layout.add_entity(target)
                wp = p + ux * x0 + uy * yb
                target.dxf.text = t
                target.dxf.style = ST
                target.dxf.height = h * sc
                target.dxf.width = wf
                target.dxf.halign = 0
                target.dxf.valign = 0
                target.dxf.insert = to_block(wp)
                if target.dxf.hasattr("align_point"):
                    target.dxf.discard("align_point")
                if inv is not None:
                    u2 = inv.transform_direction(ux)
                    target.dxf.rotation = math.degrees(math.atan2(u2.y, u2.x))
                else:
                    target.dxf.rotation = math.degrees(rot)
                new_boxes.append((x0, yb, x0 + w, yb + h))
        for r in riders:
            if r["kind"] == "sup":
                for i, t in enumerate(lines):
                    k = t.rfind(r["token"])
                    if k >= 0:
                        nx = new_boxes[i][0] + tw(t[:k + len(r["token"])], h) * wf + 0.2
                        sup = r["ent"]
                        sup.dxf.height = sup.dxf.height * h / h_orig
                        sup.dxf.insert = (p + ux * nx + uy * (ybs[i] + r["dy"] * h / h_orig))
                        break
            elif r["kind"] == "gap" and gapstr:
                t = lines[0]
                k = t.find(gapstr)
                if k >= 0:
                    gx = new_boxes[0][0] + tw(t[:k] + " ", h) * wf
                    dxv = (p + ux * gx).x - r["x0"]
                    dyv = (p + uy * ybs[0]).y - (p + uy * oy0).y
                    for g in r["ents"]:
                        g.translate(dxv, dyv, 0)
        # attached underline / strike-through lines
        if block_used and layout is not None and (not is_mtext or is_leader):
            nx0 = min(b[0] for b in new_boxes)
            nx1 = max(b[2] for b in new_boxes)
            for kind, ln, llo, lhi in self.attached_lines(e, m, p, rot, ox0, ox1, oy0, h_orig):
                a, b = Vec3(ln.dxf.start), Vec3(ln.dxf.end)
                if m is not None:
                    a, b = m.transform(a), m.transform(b)
                la, lb = to_local(a.x, a.y, p, rot), to_local(b.x, b.y, p, rot)
                if kind == "strike":
                    first = new_boxes[0]
                    span_o = max(ox1 - ox0, 1e-6)

                    def mapx(x):
                        f = min(1.0, max(0.0, (x - ox0) / span_o))
                        return first[0] + f * (first[2] - first[0])
                    for pt, lp in ((a, la), (b, lb)):
                        nx = mapx(lp[0])
                        nx += -0.5 if lp[0] <= ox0 + 0.5 else (0.5 if lp[0] >= ox1 - 0.5 else 0)
                        self.move_endpoint(ln, pt, p + ux * nx + uy * ((yb_first := ybs[0]) + (lp[1] - oy0) * h / h_orig), m)
                else:
                    right = (la, a) if la[0] > lb[0] else (lb, b)
                    left = (lb, b) if la[0] > lb[0] else (la, a)
                    if nx1 + 0.5 > right[0][0] and right[0][0] - ox1 < 4:
                        self.move_endpoint(ln, right[1], p + ux * (nx1 + 0.5) + uy * right[0][1], m)
                    if nx0 - 0.5 < left[0][0] and ox0 - left[0][0] < 4:
                        self.move_endpoint(ln, left[1], p + ux * (nx0 - 0.5) + uy * left[0][1], m)
        self.scene.boxes[oid] = box_corners(p, rot, *new_boxes[0])
        for k, bx in enumerate(new_boxes[1:], 1):
            self.scene.boxes[(oid, k)] = box_corners(p, rot, *bx)
        drawn = " / ".join(mtext_plain(l) for l in lines)
        if gapstr:
            drawn = drawn.replace(gapstr, " [SYMBOL] ")
        self.report.append({"ja": src, "en": en if not gapstr else en.replace(gapstr, " [SYMBOL] "), "drawn": drawn,
                            "how": how + (("; " + note) if note else ""), "h": round(h, 2), "wf": round(wf, 2),
                            "where": self.tag or ("title" if in_title else "body")})

    def run(self):
        # modelspace + used blocks, via the scene's text list
        done = set()
        for e, m, oid in list(self.scene.texts):
            src = e.text if e.dxftype() == "MTEXT" else e.dxf.text
            if not (JP.search(src) or re.search(r"[＀-￯]", src)):
                continue
            key = id(e)
            if key in done:
                continue
            done.add(key)
            layout = safe_layout(e)
            bname = getattr(layout, "name", "") if layout is not None else ""
            in_title = any(k in bname.lower() for k in TITLE_BLOCK_HINTS)
            self._last_src = src
            if m is None and self.try_box(e, oid):
                continue
            self.fit_one(e, m, oid, in_title, True)
        if self.tag:
            return done
        # unused blocks: fit against the block's own geometry
        for b in self.doc.blocks:
            if b.name.lower().startswith(("*model", "*paper")) or b.name in self.used_blocks:
                continue
            if any(JP.search(e.text if e.dxftype() == "MTEXT" else e.dxf.get("text", ""))
                   for e in b if e.dxftype() in ("TEXT", "MTEXT", "ATTDEF")):
                sub = Fitter(self.doc, root=b, report=self.report, tag="unused")
                done |= sub.run()
        # anything left (hidden layers, ATTDEF): translate in place
        for b in self.doc.blocks:
            if b.name.lower().startswith(("*model", "*paper")):
                continue
            for e in b:
                if id(e) in done or e.dxftype() not in ("TEXT", "ATTDEF", "MTEXT"):
                    continue
                src = e.text if e.dxftype() == "MTEXT" else e.dxf.text
                if JP.search(src):
                    self.fit_one(e, None, id(e), False, False)
        for e in self.msp:
            if id(e) in done or e.dxftype() not in ("TEXT", "MTEXT"):
                continue
            src = e.text if e.dxftype() == "MTEXT" else e.dxf.text
            if JP.search(src):
                self.fit_one(e, None, id(e), False, False)
        self._final()
        return done

    def _final(self):
        # dimension override texts
        for dim in self.doc.entitydb.values():
            if dim.dxftype() == "DIMENSION" and JP.search(dim.dxf.get("text", "")):
                t = dim.dxf.text
                dim.dxf.text = translate(t)
                self.report.append({"ja": t, "en": dim.dxf.text, "drawn": dim.dxf.text, "how": "dimension override",
                                    "h": 0, "wf": 1, "where": "dimension"})
        for ins in self.doc.entitydb.values():
            if ins.dxftype() == "INSERT":
                for a in ins.attribs:
                    if JP.search(a.dxf.text):
                        a.dxf.text = translate(a.dxf.text)
                        a.dxf.style = ST


def wrap(text, h, maxw, wf, nlines):
    words = text.split(" ")
    total = tw(text, h) * wf
    target = max(total / nlines, max(tw(w, h) * wf for w in words))
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if cur and tw(cand, h) * wf > max(target * 1.08, 1) and tw(cand, h) * wf > 0:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    lines.append(cur)
    if len(lines) > nlines or any(tw(l, h) * wf > maxw for l in lines):
        return None
    return lines


def balanced_split(text, n, h):
    words = text.split(" ")
    if len(words) < n:
        return None
    best = None

    def rec(i, k, acc):
        nonlocal best
        if k == 1:
            ls = acc + [" ".join(words[i:])]
            cost = max(tw(l, h) for l in ls)
            if best is None or cost < best[0]:
                best = (cost, ls)
            return
        for j in range(i + 1, len(words) - k + 2):
            rec(j, k - 1, acc + [" ".join(words[i:j])])
    if len(words) > 18 and n > 2:
        return None
    rec(0, n, [])
    return best[1]


def tol_tables(doc):
    """General-tolerance tables: rows 'N を超え M 以下' -> 'OVER N TO M' etc."""
    A = ezdxf.enums.TextEntityAlignment
    for blk in doc.blocks:
        texts = list(blk.query("TEXT"))
        if not any(t.dxf.text.strip() == "を超え" for t in texts):
            continue
        vx = sorted({round(l.dxf.start.x, 2) for l in blk.query("LINE") if abs(l.dxf.start.x - l.dxf.end.x) < 1e-3})
        tol_x = min((t.dxf.insert.x for t in texts if t.dxf.text.startswith("%%p")), default=None)
        if tol_x is None or len(vx) < 3:
            continue
        x_left, x_right = vx[0], vx[-1]
        mids = [v for v in vx if x_left + 10 < v < tol_x + 0.5]
        if not mids:
            continue
        x_mid = mids[-1]
        col_w = x_mid - x_left

        def put(t, s, x, y, maxw, h=2.2):
            wf = min(WF, maxw / tw(s, h))
            t.dxf.text, t.dxf.style, t.dxf.height, t.dxf.width, t.dxf.rotation = s, ST, h, wf, 0
            t.set_placement((x, y), align=A.CENTER)

        rows = {}
        for t in texts:
            rows.setdefault(round(t.dxf.insert.y, 1), []).append(t)
        for y, es in rows.items():
            es.sort(key=lambda t: t.dxf.insert.x)
            words = [norm(t.dxf.text) for t in es]
            rng = [t for t in es if t.dxf.insert.x < tol_x - 0.5]
            rw = [norm(t.dxf.text) for t in rng]
            if any(w in ("以下", "以上", "を超え") for w in rw):
                nums = [w for w in rw if re.fullmatch(r"[\d.]+", w)]
                if "を超え" in rw:
                    txt = f"OVER {nums[0]} TO {nums[1]}"
                elif "以上" in rw and "以下" in rw:
                    txt = f"{nums[0]} TO {nums[1]}"
                elif "以上" in rw:
                    txt = f"{nums[0]} OR MORE"
                else:
                    txt = f"{nums[0]} OR LESS"
                for t in rng[1:]:
                    blk.delete_entity(t)
                put(rng[0], txt, x_left + col_w / 2, y, col_w - 1.2)
            for t in es:
                if t.is_alive and t.dxf.text.startswith("%%p"):
                    v = norm(t.dxf.text).replace("%%p", "").strip()
                    put(t, "%%p " + v, (x_mid + x_right) / 2, y, x_right - x_mid - 1.2)
        for t in blk.query("TEXT"):
            n = norm(t.dxf.text)
            if n in ("B級", "C級", "中級"):
                put(t, G[n], x_left + col_w / 2, t.dxf.insert.y, col_w - 1.2)
            elif JP.search(n):
                put(t, G[n], (x_left + x_right) / 2, t.dxf.insert.y, x_right - x_left - 1.6)
            elif n == "mm":
                put(t, "mm", (x_mid + x_right) / 2, t.dxf.insert.y, 10)


def fix_two_line_cells(doc):
    """Cells holding two stacked notes (HEIGHT ... / NO GOUGES): shrink and centre them in the row."""
    for blk in doc.blocks:
        tops = [t for t in blk.query("TEXT") if t.dxf.text.startswith("HEIGHT:")]
        bots = [t for t in blk.query("TEXT") if t.dxf.text == "NO GOUGES"]
        if not tops or not bots:
            continue
        hl = sorted({round(l.dxf.start.y, 3) for l in blk.query("LINE") if abs(l.dxf.start.y - l.dxf.end.y) < 1e-3})
        for t in tops:
            y = t.dxf.insert.y
            b = min(bots, key=lambda q: abs(q.dxf.insert.y - (y - 3)))
            above = min([v for v in hl if v > y], default=None)
            below = max([v for v in hl if v < b.dxf.insert.y], default=None)
            if above is None or below is None:
                continue
            mid = (above + below) / 2
            h = min(1.8, (above - below - 1.2) / 2.3)
            for q, base in ((t, mid + 0.3), (b, mid - 0.3 - h)):
                q.dxf.height = h
                q.dxf.width = min(WF, (q.dxf.width or WF) * 1.0)
                q.dxf.insert = (q.dxf.insert.x, base)


def pair_stacked(doc):
    """Title-block labels written vertically as separate characters (名/称, 品/番) -> one rotated label."""
    for b in list(doc.blocks) + [doc.modelspace()]:
        texts = [e for e in b.query("TEXT")]
        for top, bot, en in (("名", "称", "NAME"), ("品", "番", "PART NO.")):
            texts = [e for e in texts if e.is_alive]
            tops = [e for e in texts if e.dxf.text.strip() == top]
            bots = [e for e in texts if e.dxf.text.strip() == bot]
            for t in tops:
                cand = [x for x in bots if abs(x.dxf.insert.x - t.dxf.insert.x) < 1.0 and 0 < t.dxf.insert.y - x.dxf.insert.y < 8]
                if not cand:
                    continue
                bt = cand[0]
                cx = t.dxf.insert.x + t.dxf.height * 0.5
                cy = (t.dxf.insert.y + t.dxf.height + bt.dxf.insert.y) / 2
                span = t.dxf.insert.y + t.dxf.height - bt.dxf.insert.y + 1.0
                h = 2.0
                wf = min(WF, (span - 0.4) / tw(en, h))
                t.dxf.text, t.dxf.style, t.dxf.height, t.dxf.width = en, ST, h, wf
                t.dxf.rotation = 90
                t.set_placement((cx, cy), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
                b.delete_entity(bt)
                bots.remove(bt)


BLOCK_NAMES = {"ゴム普通公差": "RUBBER_GENERAL_TOL", "プレス抜き公差": "PRESS_BLANKING_TOL", "削り加工公差": "MACHINING_TOL",
               "品質ランク": "QUALITY_RANK", "質量・体積": "MASS_VOLUME"}


def rename_japanese_names(doc):
    n = 0
    for b in list(doc.blocks):
        if JP.search(b.name) or re.search(r"[\uff61-\uff9f]", b.name):
            new = BLOCK_NAMES.get(b.name)
            if new is None:
                n += 1
                new = f"BLOCK_EN_{n}"
            old = b.name
            doc.blocks.rename_block(old, new)
            for ins in [e for e in doc.entitydb.values() if e.dxftype() == "INSERT" and e.dxf.name == old]:
                ins.dxf.name = new
    for i, lay in enumerate([l for l in doc.layouts if l.name != "Model"], 1):
        if re.search(r"[\u3000-\u30ff\uff61-\uff9f]", lay.name):
            try:
                doc.layouts.rename(lay.name, f"Layout{i}")
            except Exception:
                pass


def main():
    src, out, rep = sys.argv[1:4]
    doc = ezdxf.readfile(src)
    pair_stacked(doc)
    tol_tables(doc)
    f = Fitter(doc)
    f.run()
    fix_two_line_cells(doc)
    import drawing_fixes
    rename_japanese_names(doc)
    drawing_fixes.apply(re.sub(r"_EN$", "", out.rsplit("/", 1)[-1].rsplit(".", 1)[0]), doc)
    doc.saveas(out)
    json.dump(f.report, open(rep, "w"), ensure_ascii=False, indent=1)
    rv = [r for r in f.report if "REVIEW" in r["how"] or "no free" in r["how"]]
    print(f"{out}: {len(f.report)} texts, {len(rv)} need review")


if __name__ == "__main__":
    main()
