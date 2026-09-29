import re, sys
import ezdxf
from ezdxf.enums import TextEntityAlignment as A
from ezdxf.fonts import fonts

SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "V1411-42162_EN.dxf"

doc = ezdxf.readfile(SRC)
msp = doc.modelspace()
db = doc.entitydb
ST = "ARIAL_EN"
doc.styles.add(ST, font="arial.ttf")

WF = 0.85          # default width factor for all English text
_F = {}


def tw(s, h):
    s = s.replace("%%p", "±").replace("%%P", "±").replace("%%c", "Ø").replace("%%C", "Ø")
    if h not in _F:
        _F[h] = fonts.make_font("arial.ttf", cap_height=h)
    return _F[h].text_width(s)


def fit(s, h, maxw, wf=WF, minwf=0.6, minh=2.0):
    if maxw is None or tw(s, h) * wf <= maxw:
        return h, wf
    if maxw / tw(s, h) >= minwf:
        return h, maxw / tw(s, h)
    while h > minh + 1e-9:
        h = round(h - 0.1, 2)
        if tw(s, h) * wf <= maxw:
            return h, wf
        if maxw / tw(s, h) >= minwf:
            return h, maxw / tw(s, h)
    return h, maxw / tw(s, h)


def T(handle, text, pos, align=A.LEFT, h=2.5, maxw=None, wf=WF, rot=0, p2=None, minh=2.0, minwf=0.6):
    e = db[handle]
    if align == A.FIT:
        e.dxf.text, e.dxf.height, e.dxf.style = text, h, ST
        e.set_placement(pos, p2, align=A.FIT)
        return e
    h, wf = fit(text, h, maxw, wf, minwf, minh)
    e.dxf.text, e.dxf.height, e.dxf.width, e.dxf.style = text, h, wf, ST
    e.dxf.rotation = rot
    e.set_placement(pos, align=align)
    return e


def new_like(handle, text, pos, align=A.LEFT, h=2.5, maxw=None, wf=WF):
    src = db[handle]
    c = src.copy()
    src.get_layout().add_entity(c)
    T(c.dxf.handle, text, pos, align, h, maxw, wf)
    return c


def lines_block(handle0, lines, x, y, pitch, h=2.5, maxw=None, indent=0.0):
    """First line reuses handle0; extra lines are copies. lines: list of (text, extra_indent)."""
    out = []
    for i, (t, ind) in enumerate(lines):
        p = (x + ind, y - i * pitch)
        if i == 0:
            out.append(T(handle0, t, p, h=h, maxw=maxw))
        else:
            out.append(new_like(handle0, t, p, h=h, maxw=maxw))
    return out


def wrap(text, h, maxw, first_prefix="", indent_w=0.0, wf=WF):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        limit = maxw - (0 if not lines else indent_w)
        if tw(cand, h) * wf <= limit or not cur:
            cur = cand
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def move_end(handle, old, new):
    e = db[handle]
    s, t = e.dxf.start, e.dxf.end
    if (s.x - old[0]) ** 2 + (s.y - old[1]) ** 2 <= (t.x - old[0]) ** 2 + (t.y - old[1]) ** 2:
        e.dxf.start = (*new, 0)
    else:
        e.dxf.end = (*new, 0)


def set_line(handle, start=None, end=None):
    e = db[handle]
    if start is not None:
        e.dxf.start = (*start, 0)
    if end is not None:
        e.dxf.end = (*end, 0)


# ---------------------------------------------------------------- header
T("68D8", "INSTALLED CONDITION", (236.9, 273.3), h=3.5)
new_like("68D8", "(DEFLECTION DUE TO EQUIPMENT LOAD IS NOT CONSIDERED)", (236.9, 266.6), h=2.5)
# "MANUFACTURING DRAWING" box grows to the left
h_md = 3.5
w_md = tw("MANUFACTURING DRAWING", h_md) * WF
bx0 = 397.6 - w_md - 4.0
T("6CD1", "MANUFACTURING DRAWING", ((bx0 + 397.6) / 2, 278.7), A.MIDDLE_CENTER, h=h_md)
move_end("6CD2", (367.6, 282.2), (bx0, 282.25))
move_end("6CD3", (367.6, 275.2), (bx0, 275.25))
set_line("6CD4", start=(bx0, 275.25), end=(bx0, 282.25))

# ---------------------------------------------------------------- section view
T("9F3F", "SECTION VIEW", (134.2, 145.4), A.CENTER, h=3.5)
# leader labels (exploded multileaders in *S blocks)
LBL_H = 2.5


def leader_label(mt_handle, text, landing_handle, side, right_limit=None):
    mt = db[mt_handle]
    w = tw(text, LBL_H) * WF
    mt.text = r"{\W%.2f;%s}" % (WF, text)
    mt.dxf.char_height = LBL_H
    mt.dxf.style = ST
    ln = db[landing_handle]
    x0 = mt.dxf.insert.x
    if side == "right":          # label sits right of the leader bend; grow landing to the right
        s, e = ln.dxf.start, ln.dxf.end
        far = max(s.x, e.x)
        new_far = x0 + w + 0.6
        if s.x == far:
            ln.dxf.start = (new_far, s.y, 0)
        else:
            ln.dxf.end = (new_far, e.y, 0)
    else:                        # label left of the bend; move label left and grow landing
        s, e = ln.dxf.start, ln.dxf.end
        bend = max(s.x, e.x)
        nx = (right_limit if right_limit else bend - 0.6) - w
        mt.dxf.insert = (nx, mt.dxf.insert.y, 0)
        if s.x < e.x:
            ln.dxf.start = (nx, s.y, 0)
        else:
            ln.dxf.end = (nx, e.y, 0)


leader_label("BC4E", "SURFACE A", "BC49", "right")
leader_label("BC58", "SURFACE A", "BC53", "left", right_limit=134.0)
leader_label("BC62", "SURFACE B", "BC5D", "right")
leader_label("BC6C", "SURFACE A", "BC67", "right")

# dimension "%%C42.3(R9の中心)"
dim = db["81CE"]
dim_txt = "%%C42.3 (CENTER OF R9)"
dim.dxf.text = r"{\W0.80;%s}" % dim_txt
ov = dim.override()
ov["dimtxt"] = 2.5
ov["dimtxsty"] = ST
ov.commit()
mt = db["B515"]
mt.text = r"\A1;{\W0.80;%s}" % dim_txt
mt.dxf.char_height = 2.5
mt.dxf.style = ST

# ---------------------------------------------------------------- right view
T("6632", "STOPPER", (273.9, 248.1), A.RIGHT)
T("6634", "STOPPER", (270.6, 182.7), A.RIGHT)
T("64E1", "P", (261.6, 196.9), h=4.0, wf=1.0)
T("64E3", "Q", (251.7, 216.9), h=4.0, wf=1.0)
T("660F", "(MOUNTING HOLE DIAMETER)", (316.3, 161.1), A.MIDDLE_CENTER)

# ---------------------------------------------------------------- maker mark note
SYM_DX = 12.0
sym_handles = [h for h in db.keys() if re.fullmatch(r"[0-9A-F]+", h) and 0xA0BF <= int(h, 16) <= 0xA116
               and db[h].dxftype() in ("ARC", "LINE", "CIRCLE", "TEXT", "LWPOLYLINE") and db[h].dxf.owner == msp.layout_key]
for h in sym_handles:
    db[h].translate(SYM_DX, 0, 0)
T("A0BD", "EMBOSS THE MANUFACTURER MARK", (211.1, 242.9))
T("A0BC", "AND DATE OF MANUFACTURE.", (211.1, 238.6))
T("A0BA", "EXAMPLE: FEBRUARY 2016:", (211.1, 231.7))
move_end("A0BB", (246.68, 237.17), (211.1 + tw("AND DATE OF MANUFACTURE.", 2.5) * WF + 0.5, 237.17))

# ---------------------------------------------------------------- identification block (top-left)
X0 = 12.9
t_id = "IDENTIFICATION (EMBOSSING + MARKING)"
T("B1E3", t_id, (X0, 242.3))
id_end = X0 + tw(t_id, 2.5) * WF + 0.5
move_end("B283", (64.43, 240.88), (id_end, 240.88))
move_end("B285", (64.43, 240.88), (id_end, 240.88))
pre = "EMBOSSING: V1411-"
T("B28D", pre + "42162", (X0, 231.8))
sx = X0 + tw(pre, 2.5) * WF
sw = tw("42161", 2.5) * WF
T("B8BC", "42161", (sx, 235.8))
set_line("B8C3", start=(sx - 0.3, 238.0), end=(sx + sw + 0.3, 238.0))
set_line("B8C4", start=(sx - 0.3, 236.6), end=(sx + sw + 0.3, 236.6))

ID_W = 56.0
PITCH = 4.4
items = [("B78D", "MARKING:", "AROUND THE ENTIRE CIRCUMFERENCE"),
         ("B78E", "COLOR:", "BLUE; LINE WIDTH: OPTIONAL"),
         ("B79D", "POSITION:", "OVER THE EMBOSSING (OVERHANG IS ACCEPTABLE)"),
         ("B78F", "", "LINE DISTORTION, UNEVENNESS, FADING, AND RUNS ARE ACCEPTABLE.")]
y = 221.6
for hnd, label, body in items:
    full = (label + " " + body).strip()
    ind = 3.0
    ls = wrap(full, 2.5, ID_W, indent_w=ind)
    lines_block(hnd, [(l, 0 if i == 0 else ind) for i, l in enumerate(ls)], X0, y, PITCH, maxw=ID_W)
    y -= PITCH * len(ls) + 0.6

# ---------------------------------------------------------------- specifications
T("46F5", "SPECIFICATIONS", (22.4, 126.4), h=3.5)
T("46F6", "1. STATIC SPRING RATE", (24.5, 121.4), h=3.0)
C = lambda hnd, s, x, y, w, **k: T(hnd, s, (x, y), A.MIDDLE_CENTER, maxw=w, **k)
C("887A", "STATIC SPRING RATE", 46.1, 116.4, 37)
new_like("887A", "IN P DIRECTION", (46.1, 112.0), A.MIDDLE_CENTER, maxw=37)
C("4735", "KsP (N/mm) %%p15%", 46.1, 107.6, 37)
C("683D", "STATIC SPRING RATE", 86.1, 116.4, 37)
new_like("683D", "IN Q DIRECTION (REF.)", (86.1, 112.0), A.MIDDLE_CENTER, maxw=37)
C("683E", "KsQ (N/mm)", 86.1, 107.6, 37)
C("76E0", "1026", 46.1, 101.0, 37)
C("76E3", "850", 86.1, 101.0, 37)
C("A426", "MEASUREMENT RANGE", 146.1, 115.5, 77)
C("A427", "P DIRECTION", 126.1, 108.5, 37)
C("A429", "Q DIRECTION", 166.1, 108.5, 37)
C("A439", "BETWEEN 809 AND 2427 N", 126.1, 101.0, 37)
C("A43A", "BETWEEN 809 AND 1618 N", 166.1, 101.0, 37)
C("A421", "1W", 196.1, 115.5, 17)
C("A422", "(N)", 196.1, 108.5, 17)
C("A438", "1618", 196.1, 101.0, 17)
C("A42B", "PRELOAD (N)", 226.1, 115.5, 37)
C("A42C", "P DIR.", 216.1, 108.5, 17)
C("A42F", "Q DIR.", 236.1, 108.5, 17)
C("A43B", "6472", 216.1, 101.0, 17)
C("A43C", "4854", 236.1, 101.0, 17)
C("A432", "TEST SPEED (mm/min)", 276.1, 115.5, 57)
C("A433", "P DIRECTION", 261.1, 108.5, 27)
C("A434", "Q DIRECTION", 291.1, 108.5, 27)
C("A436", "10", 261.1, 101.0, 27)
C("A437", "10", 291.1, 101.0, 27)

IND = 31.5
T("7131", "MEASURE IN THE INSTALLED CONDITION. (A DISC-TYPE STOPPER IS ACCEPTABLE.)", (IND, 89.9))
T("7133", "2. SURFACE TREATMENT", (24.5, 81.2), h=3.0)
T("85A4", "METAL PRETREATMENT: No. 2 OR 21", (IND, 76.2))
lab = "METAL PART SURFACE TREATMENT: "
T("85A2", lab + "BLACK COATING (ACRYLIC WATER-BASED EMULSION PAINT / ASUKA KK)", (IND, 71.6))
vx = IND + tw(lab, 2.5) * WF
T("85A3", "FILM THICKNESS: 15 µm MIN. / ADHESION TO RUBBER IS ACCEPTABLE.", (vx, 67.0))
new_like("85A3", "EXCLUDING THE INNER SURFACE OF THE INNER SLEEVE.", (vx, 62.4))

t_rv = "RUBBER VOLUME: 230 cm"
T("9C75", t_rv, (281.5, 77.5))
T("9C76", "3", (281.5 + tw(t_rv, 2.5) * WF + 0.2, 79.1), h=1.5, wf=1.0)

# ---------------------------------------------------------------- notes
T("8808", "NOTES", (22.4, 41.5), h=3.5)
NX, NIND, NW, NP = 24.6, 5.2, 186.0, 4.9
notes = [
    ("880A", "1.", "THIS PART DIFFERS FROM V1411-4215A IN STATIC SPRING RATE AND RUBBER SHAPE."),
    ("A70B", "2.", "THIS PART DIFFERS FROM V1411-42151 AND V1411-4219A IN RUBBER HARDNESS."),
    ("B790", "3.", "THIS PART DIFFERS FROM V1411-42161 IN IDENTIFICATION MARKING."),
    ("8A8B", "4.", "SURFACE A (ENTIRE SURFACE) IS A FASTENING SURFACE (SEE INSTALLATION DRAWING);|NO RUBBER FLASH IS PERMITTED."),
    ("8A8C", "", "MARKING RUNS ON SURFACE A (ENTIRE SURFACE) ARE ACCEPTABLE."),
    ("B79C", "", "NO LOOSE RUBBER FLASH IS PERMITTED ON SURFACE B (ENTIRE CIRCUMFERENCE)."),
]
y = 34.7
for hnd, num, body in notes:
    ls = body.split("|") if "|" in body else wrap(body, 2.5, NW - NIND)
    if num:
        new_like(hnd, num, (NX, y))
    first = lines_block(hnd, [(l, NIND) for l in ls], NX, y, NP)
    if hnd == "B790":                 # struck-out note 3 + its revision triangle
        wend = NX + NIND + tw(ls[0], 2.5) * WF
        set_line("B8C8", start=(NX - 0.9, y + 1.7), end=(wend + 0.6, y + 1.7))
        set_line("B8C9", start=(NX - 0.9, y + 0.8), end=(wend + 0.6, y + 0.8))
        for ins in msp.query("INSERT[name=='rireki']"):
            if abs(ins.dxf.insert.x - 20.5) < 0.2 and abs(ins.dxf.insert.y - 25.3) < 0.2:
                ins.dxf.insert = (20.5, y + 1.4, 0)
    y -= NP * len(ls)

# ---------------------------------------------------------------- title block: modelspace texts
T("804", "ENGINE MOUNT", (319.7, 11.6), h=4.0)
T("692C", "RUBBER", (236.0, 54.0), maxw=23)
T("692F", "INNER SLEEVE", (323.0, 60.0), maxw=23)
T("6930", "HEAT-RES. NR", (271.0, 54.0), maxw=18.5)
T("6937", "PLATE", (323.0, 54.0), maxw=23)
for hnd, s, x, y in [("692D", "1", 230.0, 54.0), ("6931", "1", 265.0, 54.0), ("692E", "2", 317.0, 60.0),
                     ("6933", "1", 352.0, 60.0), ("6934", "3", 317.0, 54.0), ("6936", "1", 352.0, 54.0)]:
    T(hnd, s, (x, y), A.CENTER)
T("6932", "STKM12C", (358.0, 60.0), maxw=19.5)
T("6935", "SPHC-P", (358.0, 54.0), maxw=19.5)
T("7427", "V0511-42151-2", (379.0, 60.0), maxw=19.5)
T("7428", "V0511-42151-3", (379.0, 54.0), maxw=19.5)
for hnd, s_, base in [("8497", "T.P.Hs=56 (REF.)", 53.0), ("BB0F", "T.P.Hs=57 (REF.)", 59.0)]:
    T(hnd, s_, (301.5, base + 0.7), A.CENTER, h=1.8, maxw=19.5)
for hnd, s_, base in [("72B7", "G1756K", 53.0), ("BB0E", "G1757K", 59.0)]:
    T(hnd, s_, (301.5, base + 3.3), A.CENTER, h=2.0, maxw=19.5)
for hnd, y_ in [("BB22", 59.0 + 0.7 + 0.55), ("BB2B", 59.0 + 0.7 + 1.25), ("BB10", 59.0 + 3.3 + 0.6), ("BB19", 59.0 + 3.3 + 1.4)]:
    l = db[hnd]
    l.dxf.start = (l.dxf.start.x, y_, 0)
    l.dxf.end = (l.dxf.end.x, y_, 0)
# revision table rows
T("BAF3", "RUBBER HARDNESS CHANGED", (250.5, 32.0), A.MIDDLE_CENTER, maxw=55)
T("B8B7", "EMBOSSING CHANGED", (250.5, 26.0), A.MIDDLE_CENTER, maxw=55)
NAME_KW = dict(maxw=8.2, minh=1.8, minwf=0.5)
T("BAF5", "KAGEYAMA", (294.5, 32.0), A.MIDDLE_CENTER, **NAME_KW)
T("BAF6", "KATAYAMA", (303.5, 32.0), A.MIDDLE_CENTER, **NAME_KW)
T("B8B9", "KAGEYAMA", (294.5, 26.0), A.MIDDLE_CENTER, **NAME_KW)
T("B8BA", "TOMIWA", (303.5, 26.0), A.MIDDLE_CENTER, **NAME_KW)
# sign-off row
T("5117", "KAGEYAMA", (224.5, 6.0), A.MIDDLE_CENTER, maxw=17)
T("5116", "YOKOBE", (243.5, 6.0), A.MIDDLE_CENTER, maxw=17)
T("2412", "TOMIWA", (262.5, 6.0), A.MIDDLE_CENTER, maxw=17)

# ---------------------------------------------------------------- WAKU (title block frame)
for hnd, s, x, y, w in [("8621", "NO.", 230.0, 50.0, 9), ("868E", "NO.", 317.0, 50.0, 9),
                        ("8613", "DESCRIPTION", 247.5, 50.0, 23), ("85FE", "DESCRIPTION", 334.5, 50.0, 23),
                        ("862C", "QTY", 265.0, 50.0, 9), ("86C8", "QTY", 352.0, 50.0, 9),
                        ("8608", "MATERIAL", 280.5, 50.0, 19), ("86B8", "MATERIAL", 367.5, 50.0, 19),
                        ("8636", "REMARKS", 301.5, 50.0, 19), ("86DE", "REMARKS", 388.5, 50.0, 19),
                        ("86B3", "THIRD", 220.0, 61.3, 8.8), ("85FF", "ANGLE", 220.0, 56.0, 8.8),
                        ("862A", "PROJ.", 220.0, 50.7, 8.8),
                        ("861B", "CODE", 218.5, 20.0, 6.2), ("8615", "REVISION HISTORY / CHANGES", 250.5, 20.0, 55),
                        ("863C", "DATE", 284.5, 20.0, 10), ("863B", "APPD", 294.5, 20.0, 8.2),
                        ("863D", "REV.", 303.5, 20.0, 8.2),
                        ("861A", "APPROVED", 224.5, 14.5, 17), ("8614", "CHECKED", 243.5, 14.5, 17),
                        ("862B", "DRAWN", 262.5, 14.5, 17), ("860B", "DATE CREATED", 283.5, 14.5, 21.5),
                        ("863E", "SCALE", 301.5, 14.5, 11.5)]:
    T(hnd, s, (x, y), A.MIDDLE_CENTER, maxw=w, h=2.2 if hnd in ("86B3", "85FF", "862A") else 2.5)
for hnd, s, x in [("862D", "YEAR", 279.3), ("862E", "MONTH", 286.2), ("862F", "DAY", 292.6)]:
    T(hnd, s, (x, 9.6), A.MIDDLE_CENTER, h=1.8, wf=0.7)
T("8646", "NAME", (310.6, 15.0), A.MIDDLE_CENTER, h=2.0, maxw=9.0, rot=90)
T("8634", "PART NO.", (310.6, 5.0), A.MIDDLE_CENTER, h=2.0, maxw=9.0, rot=90)
for hnd in ("8645", "8635"):
    doc.blocks.get("WAKU").delete_entity(db[hnd])
T("86BA", "INDUSTRIAL MACHINERY DIVISION", (360.5, 34.1), A.MIDDLE_CENTER, h=3.0, maxw=64)
for hnd, s, base in [("8620", "1", 23.78), ("8616", "2", 30.13), ("8627", "3", 36.04), ("8622", "4", 41.74)]:
    T(hnd, s, (218.7, base + 0.6), A.CENTER, h=1.8, wf=1.0)

# ---------------------------------------------------------------- misc blocks
T("89A4", "A", db["89A4"].dxf.align_point if db["89A4"].dxf.halign else db["89A4"].dxf.insert, A.MIDDLE_CENTER, h=4.0, wf=1.0)
T("85EB", "* DIMENSIONAL TOLERANCES NOT SPECIFIED ON THIS DRAWING SHALL CONFORM TO SANKI STANDARD KSS11-3 AND 4.",
  (215.0, 67.0))


# ---------------------------------------------------------------- general tolerance tables (blocks)
def tol_table(bname, title, klass, klass_h, tol_x):
    blk = doc.blocks.get(bname)
    vx = sorted({round(l.dxf.start.x, 2) for l in blk.query("LINE") if abs(l.dxf.start.x - l.dxf.end.x) < 1e-3})
    x_left, x_mid, x_right = vx[0], [v for v in vx if 15 < v < tol_x][0], vx[-1]
    rows = {}
    for e in list(blk.query("TEXT")):
        y = round(e.dxf.insert.y, 1)
        rows.setdefault(y, []).append(e)
    col_w = x_mid - x_left
    for y, es in rows.items():
        es.sort(key=lambda e: e.dxf.insert.x)
        txt = [e.dxf.text.strip() for e in es]
        if any(t in ("以下", "以上", "を超え") for t in txt):
            rng = [e for e in es if e.dxf.insert.x < tol_x - 0.5]
            words = [e.dxf.text.strip() for e in rng]
            nums = [w for w in words if re.fullmatch(r"[\d.]+", w)]
            if "を超え" in words:
                s = f"OVER {nums[0]} TO {nums[1]}"
            elif "以上" in words and "以下" in words:
                s = f"{nums[0]} TO {nums[1]}"
            elif "以上" in words:
                s = f"{nums[0]} OR MORE"
            else:
                s = f"{nums[0]} OR LESS"
            keep = rng[0]
            for e in rng[1:]:
                blk.delete_entity(e)
            T(keep.dxf.handle, s, (x_left + col_w / 2, y), A.CENTER, h=2.2, maxw=col_w - 1.2)
        for e in es:
            if not e.is_alive:
                continue
            t = e.dxf.text
            if t.startswith("%%p"):
                v = t.replace("　", "").replace("%%p", "")
                import unicodedata
                v = unicodedata.normalize("NFKC", v)
                T(e.dxf.handle, "%%p " + v, ((x_mid + x_right) / 2, y), A.CENTER, h=2.2, maxw=x_right - x_mid - 1.2)
    for e in blk.query("TEXT"):
        t = e.dxf.text
        if t in ("B級", "C級", "中級"):
            T(e.dxf.handle, klass, (x_left + col_w / 2, klass_h), A.CENTER, h=2.2, maxw=col_w - 1.2)
        elif re.search(r"[　-ヿ一-鿿]", t):
            T(e.dxf.handle, title, ((x_left + x_right) / 2, e.dxf.insert.y), A.CENTER, h=2.2, maxw=x_right - x_left - 1.6)
        elif t == "mm":
            T(e.dxf.handle, "mm", ((x_mid + x_right) / 2, klass_h), A.CENTER, h=2.2)


tol_table("ゴム普通公差", "GENERAL RUBBER TOLERANCES", "CLASS B", 46.2, 26.2)
tol_table("プレス抜き公差", "PRESS-BLANKING TOLERANCES", "CLASS C", 30.8, 27.2)
tol_table("削り加工公差", "MACHINING TOLERANCES", "MEDIUM CLASS", 30.8, 27.0)

# ---------------------------------------------------------------- names, code page
for old, new in [("ゴム普通公差", "RUBBER_GENERAL_TOL"), ("プレス抜き公差", "PRESS_BLANKING_TOL"),
                 ("削り加工公差", "MACHINING_TOL")]:
    doc.blocks.rename_block(old, new)
    for ins in [e for e in db.values() if e.dxftype() == "INSERT" and e.dxf.name == old]:
        ins.dxf.name = new
try:
    doc.layouts.rename("ﾚｲｱｳﾄ1", "Layout1")
except Exception as ex:
    print("layout rename:", ex)

doc.saveas(OUT)
print("saved", OUT)
