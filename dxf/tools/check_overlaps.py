"""Find English text that touches other text or drawing lines in a translated DXF.

usage: python check_overlaps.py DRAWING_EN.dxf [--pdf DRAWING_EN.pdf --out review_dir]

Text size is measured from the actual PDF glyph strokes (same routine as dxf_to_pdf.py).
Each hit gets a hint so a reviewer can tell design features from real problems:
  取消線の可能性   horizontal line through the middle of the text (revision strike-through)
  罫線/下線の可能性 horizontal line at the text baseline (ruled notes, leader landing)
  線と交差         any other line crossing the text
With --pdf, a zoomed PNG of every hit and tiles of the whole sheet are written to --out.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import ezdxf  # noqa: E402

import autotranslate as A  # noqa: E402
import dxf_to_pdf as R  # noqa: E402

MARGIN = 0.15


def _seg_box(x1, y1, x2, y2, b):
    bx0, by0, bx1, by1 = b
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - bx0), (dx, bx1 - x1), (-dy, y1 - by0), (dy, by1 - y1)):
        if p == 0:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
            if t0 > t1:
                return None
    return t0, t1


def _hint(x1, y1, x2, y2, box):
    if abs(y1 - y2) > 0.05:
        return "線と交差"
    f = (y1 - box[1]) / max(box[3] - box[1], 1e-6)
    if 0.25 <= f <= 0.75:
        return "取消線の可能性"
    return "罫線/下線の可能性"


def check(path):
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    hidden = {l.dxf.name for l in doc.layers if l.is_off() or l.is_frozen()}
    boxes = []
    for e in R.iter_texts(doc, msp, hidden):
        segs = R.mtext_segments(e) if e.dxftype() == "MTEXT" else R.text_segments(e)
        pts = [p for s in segs for p in s]
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        txt = A.mtext_plain(e.text) if e.dxftype() == "MTEXT" else e.dxf.text
        boxes.append(((min(xs), min(ys), max(xs), max(ys)), txt, e.dxf.get("style", "") == A.ST))
    sc = A.Scene(doc)
    sc.walk(msp, None)
    issues = []
    for i, (bb, t, en) in enumerate(boxes):
        if not en:
            continue
        b = (bb[0] + MARGIN, bb[1] + MARGIN, bb[2] - MARGIN, bb[3] - MARGIN)
        if b[0] >= b[2] or b[1] >= b[3]:
            continue
        for j, (ob, ot, oen) in enumerate(boxes):
            if j == i or (oen and j < i):
                continue
            if ob[0] < b[2] and ob[2] > b[0] and ob[1] < b[3] and ob[3] > b[1]:
                issues.append({"type": "文字と文字", "text": t, "other": ot, "box": [round(v, 1) for v in bb],
                               "hint": "同じ文字の重複の可能性" if ot == t else "文字の重なり"})
        hints = {}
        for x1, y1, x2, y2, _ in sc.segs:
            if _seg_box(x1, y1, x2, y2, b):
                h = _hint(x1, y1, x2, y2, bb)
                hints[h] = hints.get(h, 0) + 1
        if hints:
            issues.append({"type": "文字と線", "text": t, "other": ", ".join(f"{k}×{v}" for k, v in hints.items()),
                           "box": [round(v, 1) for v in bb], "hint": max(hints, key=hints.get)})
    return issues


def page_image(dxf_path, pdf_path, dpi=200):
    import fitz
    from PIL import Image
    doc = ezdxf.readfile(dxf_path)
    pg = R.find_page(doc, doc.modelspace())
    w, h = pg[2] - pg[0], pg[3] - pg[1]
    pw, ph = (420, 297) if max(w, h) > 305 else (297, 210)
    if h > w:
        pw, ph = ph, pw
    cx, cy = (pg[0] + pg[2]) / 2, (pg[1] + pg[3]) / 2
    pix = fitz.open(pdf_path)[0].get_pixmap(dpi=dpi)
    im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    k = dpi / 25.4

    def to_px(x, y):
        return (x - (cx - pw / 2)) * k, (cy + ph / 2 - y) * k
    return im, to_px, (pw, ph)


def write_images(dxf_path, pdf_path, issues, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    im, to_px, (pw, ph) = page_image(dxf_path, pdf_path)
    W, H = im.size
    tiles = [(0, 0, .52, .52), (.48, 0, 1, .52), (0, .48, .52, 1), (.48, .48, 1, 1)] if pw > ph else [(0, 0, 1, .52), (0, .48, 1, 1)]
    tile_files = []
    for n, (a, b, c, d) in enumerate(tiles, 1):
        f = out / f"tile_{n}.png"
        im.crop((int(a * W), int(b * H), int(c * W), int(d * H))).save(f)
        tile_files.append(f.name)
    for n, it in enumerate(issues, 1):
        x0, y0, x1, y1 = it["box"]
        p = to_px(x0 - 10, y1 + 8)
        q = to_px(x1 + 10, y0 - 8)
        f = out / f"issue_{n:02d}.png"
        im.crop((int(p[0]), int(p[1]), int(q[0]), int(q[1]))).save(f)
        it["image"] = f.name
    return tile_files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dxf")
    ap.add_argument("--pdf")
    ap.add_argument("--out")
    a = ap.parse_args()
    issues = check(a.dxf)
    if a.pdf and a.out:
        write_images(a.dxf, a.pdf, issues, a.out)
    print(json.dumps(issues, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
