---
description: 日本語DXF図面を英訳し、DXF・PDFを作って配置を確認する
agent: agent
---
日本語のDXF図面を英語版に変換してください。

- 入力フォルダ: ${input:inputFolder:入力フォルダ（例 C:\Users\USER\Downloads\DXF_ENG）}
- 出力フォルダ: ${input:outputFolder:出力フォルダ（例 C:\Users\USER\Downloads\DXF_ENG\EN）}

[copilot-instructions](../copilot-instructions.md) の「手順」「訳語のルール」「確認の判断基準」「直し方」に従って進めること。

1. `python dxf/tools/translate_all.py <入力> <出力>` を実行する。
2. 未登録語で止まったら、`missing_terms.csv` に英訳を付けて `dxf/tools/glossary.csv` に追記し、再実行する。追記した語の一覧は最後に報告する。
3. `<出力>/review/REPORT.md` の候補を1件ずつ確認し、直すべきものは直して再実行する。
4. 完了したら、次を短く報告する:
   - 作成したDXF・PDFのファイル一覧
   - 追加した訳語（特に推定した氏名の読み）
   - 直した箇所と、元図の作りなので残した箇所
   - 人が確認すべき点
