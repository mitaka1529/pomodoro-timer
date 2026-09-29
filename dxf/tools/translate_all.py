"""Translate every DXF in a folder to English, make PDFs and a review report.

usage: python dxf/tools/translate_all.py INPUT_DIR OUTPUT_DIR

Steps
  1. Check all drawings for Japanese text missing from glossary.csv.
     If any: write OUTPUT_DIR/missing_terms.csv and stop (exit code 2).
     Fill in the 英語 column, append the rows to glossary.csv, run again.
  2. Translate and fit text      -> OUTPUT_DIR/NAME_EN.dxf
  3. Plot to PDF                 -> OUTPUT_DIR/NAME_EN.pdf
  4. Check overlaps + images     -> OUTPUT_DIR/review/NAME/ and OUTPUT_DIR/review/REPORT.md
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ezdxf  # noqa: E402

import autotranslate as A  # noqa: E402
import check_overlaps as C  # noqa: E402


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    src_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in src_dir.glob("*.dxf") if not p.stem.endswith("_EN"))
    if not files:
        print(f"no .dxf files in {src_dir}")
        sys.exit(1)

    missing_csv = out_dir / "missing_terms.csv"
    missing_csv.unlink(missing_ok=True)
    seen = set()
    for f in files:
        miss = {k: v for k, v in A.find_missing(ezdxf.readfile(f)).items() if k not in seen}
        seen |= set(miss)
        if miss:
            A.write_missing(miss, missing_csv, f.stem)
    if seen:
        print(f"STOP: {len(seen)} Japanese term(s) are not in glossary.csv -> {missing_csv}")
        print("Fill in the 英語 column, add the rows to dxf/tools/glossary.csv, then run again.")
        sys.exit(2)

    review = out_dir / "review"
    report = ["# 英訳図面 確認レポート", "",
              "各図面の「文字と線」「文字と文字」の接触候補です。画像を見て、",
              "元図と同じ作り（取消線・罫線・引出線に沿った文字など）か、直すべき問題かを判断してください。", ""]
    for f in files:
        name = f.stem
        dxf_out = out_dir / f"{name}_EN.dxf"
        pdf_out = out_dir / f"{name}_EN.pdf"
        rep = review / name / "fit_report.json"
        rep.parent.mkdir(parents=True, exist_ok=True)
        A.translate_file(str(f), str(dxf_out), str(rep))
        subprocess.run([sys.executable, str(HERE.parent / "dxf_to_pdf.py"), str(dxf_out), str(pdf_out)], check=True)
        issues = C.check(str(dxf_out))
        tiles = C.write_images(str(dxf_out), str(pdf_out), issues, review / name)
        (review / name / "issues.json").write_text(json.dumps(issues, ensure_ascii=False, indent=1), encoding="utf-8")
        fit = json.loads(rep.read_text(encoding="utf-8"))
        small = [r for r in fit if r["where"] != "unused" and len(r["drawn"]) > 5
                 and ("reduced" in r["how"] or "REVIEW" in r["how"])]
        report += [f"## {name}", "", f"- PDF: `{pdf_out.name}`  / 全体画像: " + ", ".join(f"`{name}/{t}`" for t in tiles),
                   f"- 接触候補: {len(issues)} 件 / 文字を縮小した箇所: {len(small)} 件", ""]
        for n, it in enumerate(issues, 1):
            report.append(f"{n}. [{it['hint']}] 「{it['text']}」 ↔ {it['other']}  → `{name}/{it['image']}`")
        for r in small:
            report.append(f"- 縮小: 「{r['drawn']}」 ({r['how']})")
        report.append("")
        print(f"{name}: {len(issues)} contact candidate(s)")
    (review / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    print(f"done -> {out_dir}  (review: {review / 'REPORT.md'})")


if __name__ == "__main__":
    main()
