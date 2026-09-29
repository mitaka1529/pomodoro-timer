# DXF図面 英訳ツール

日本語のCAD図面（DXF）を英語版のDXFとPDFに変換します。
文字は周りの空きに合わせて自動で大きさ・折り返しを調整し、重なりをチェックします。

## 準備（初回のみ）
1. Python 3.10以降をインストール（python.org。インストール時に「Add Python to PATH」にチェック）
2. コマンドプロンプトで:
   ```
   pip install -r dxf\tools\requirements.txt
   ```

## 使い方
```
python dxf\tools\translate_all.py 入力フォルダ 出力フォルダ
```
または `dxf\tools\convert.bat 入力フォルダ 出力フォルダ`

出力フォルダにできるもの:
| ファイル | 内容 |
|---|---|
| `図面名_EN.dxf` | 英語版DXF（文字は romans.shx の細い一本線） |
| `図面名_EN.pdf` | A3/A4 原寸のPDF |
| `review/REPORT.md` | 文字と線・文字の接触候補と、縮小した文字の一覧 |
| `review/図面名/` | 接触候補の拡大画像、図面全体の分割画像 |

## 未登録の日本語があったとき
`STOP: ... not in glossary.csv` と出て止まり、出力フォルダに `missing_terms.csv` ができます。
1. `missing_terms.csv` の「英語」列を埋める
2. その行を `dxf\tools\glossary.csv` に追記する（**日本語キーは変えずにそのままコピー**）
3. もう一度実行する

## Copilot（エージェント）で使う
VS Code の Copilot Chat をエージェントモードにして、次のどちらかで実行します。
- チャットで `/dxf-translate` と入力（`.github/prompts/dxf-translate.prompt.md`）
- エージェントの選択で `dxf-translator` を選び、「このフォルダの図面を英訳して」と依頼（`.github/agents/dxf-translator.agent.md`）

Copilot は Python ツールで変換し、未登録語の英訳、`REPORT.md` の確認と手直しを行います。
作業ルールは `.github/copilot-instructions.md` に書いてあります。

## 最後に人が確認すること
- AutoCAD で開いて表示を確認（PDFは代替描画です）
- 推定した氏名の読み（`glossary.csv` の備考に「要確認」とあるもの）
