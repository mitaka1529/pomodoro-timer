# 田んぼ自動水管理デバイス（rice-water-manager）

水田の水位をセンサーで常時計測し、目標水位を下回ったら電磁弁（給水バルブ）を自動で開閉するデバイスのソフトウェア一式です。カメラを接続して田んぼの様子を定期撮影し、スマホ・PC のブラウザから水位・バルブ状態・写真を確認できます。

実機（Raspberry Pi）がなくても **シミュレーションモード** で全機能が動作するので、まず手元の PC で挙動を確認してから実機に載せられます。

## 全体構成

```
[水位センサー HC-SR04] ──┐
[カメラモジュール]      ──┤                    ┌── ブラウザ (スマホ/PC)
[水温センサー(任意)]    ──┼── Raspberry Pi ────┤     ダッシュボード
                          │   (制御ループ+Web) └── Webhook 通知 (任意)
[リレー] ── [電磁弁] ─────┘
              │
        給水パイプ/水口
```

- **制御ループ**: 一定間隔で水位を計測し、「目標水位 − ヒステリシス」を下回ったらバルブを開き、目標水位に達したら閉じます。連続開弁時間の上限（フェイルセーフ）付き。
- **生育ステージ対応**: 活着期・分げつ期・中干し・出穂期などの期間ごとに目標水位を設定できます。中干し期間はバルブを閉じたままロックできます。
- **カメラ**: 一定間隔で静止画を撮影して保存。最新の写真をダッシュボードに表示します。Raspberry Pi カメラモジュール（picamera2）、USB カメラ（OpenCV）、シミュレーションの 3 方式に自動対応。
- **記録**: 水位・バルブ状態を SQLite に記録し、履歴グラフを表示します。
- **通知**: 水位の異常（渇水・冠水）や長時間開弁を Webhook（Slack / Discord / LINE 等）に通知できます。

## 推奨ハードウェア（部品表）

| 部品 | 例 | 用途 |
|---|---|---|
| Raspberry Pi Zero 2 W / 4 | — | 本体。Wi-Fi でダッシュボード配信 |
| 防水超音波センサー | HC-SR04（防水型は JSN-SR04T） | 水面までの距離から水位を算出 |
| カメラ | Raspberry Pi Camera Module 3 または USB カメラ | 定点観測 |
| リレーモジュール | 5V 1ch リレー（アクティブLOW が一般的） | 電磁弁の開閉 |
| 電磁弁 | DC12V ソレノイドバルブ（口径は水口に合わせる） | 給水制御 |
| 電源 | AC アダプタ or ソーラー + 12V バッテリー + 5V 降圧 | 屋外運用ならソーラー推奨 |
| 防水ケース | IP65 以上のボックス | 屋外設置用 |
| （任意）水温センサー | DS18B20（防水型） | 水温記録 |

### 配線（デフォルト設定）

| 信号 | GPIO (BCM) | 備考 |
|---|---|---|
| 超音波 Trig | GPIO23 | 3.3V 出力でそのまま接続可 |
| 超音波 Echo | GPIO24 | **5V センサーの場合は分圧抵抗(例 1kΩ/2kΩ)で 3.3V に落とすこと** |
| リレー IN | GPIO17 | `active_low: true`（LOW で開弁）を既定とする |

超音波センサーは田面（土の面）から `mount_height_mm` の高さに水面へ向けて固定します。水位 = 設置高 − 計測距離 で算出します。

## セットアップ

```bash
cd rice-water-manager
pip install -r requirements.txt          # 実機では追加で: pip install RPi.GPIO picamera2
python -m paddy.main --config config.yaml
```

起動すると制御ループが回り始め、`http://<デバイスのIP>:8000/` でダッシュボードが開きます。

手元の PC で試す場合（センサー・バルブ・カメラをすべて疑似動作させる）:

```bash
python -m paddy.main --config config.yaml --simulate
```

1 回だけ計測・判断して終了する場合（cron 運用向け）:

```bash
python -m paddy.main --config config.yaml --once
```

### 常駐化（systemd）

```bash
sudo cp deploy/paddy-water.service /etc/systemd/system/
sudo systemctl enable --now paddy-water
```

## 設定（config.yaml）

主な項目だけ抜粋します。詳細は `config.yaml` のコメントを参照してください。

```yaml
control:
  interval_seconds: 60      # 計測間隔
  target_level_mm: 50       # 目標水位
  hysteresis_mm: 10         # これだけ下回ったら開弁
  max_open_minutes: 120     # 連続開弁の上限（フェイルセーフ）
stage_overrides:            # 期間ごとの目標水位（月-日で指定）
  - {name: 中干し, start: "06-21", end: "07-01", target_level_mm: 0, valve_locked_closed: true}
camera:
  interval_minutes: 30      # 撮影間隔
notify:
  webhook_url: ""           # 異常時に POST する URL（空なら通知なし）
```

## Web API

| メソッド/パス | 内容 |
|---|---|
| `GET /` | ダッシュボード（水位・バルブ・最新写真・履歴グラフ） |
| `GET /api/status` | 現在の状態 JSON |
| `GET /api/history?hours=24` | 水位履歴 JSON |
| `GET /photo/latest` | 最新の写真 |
| `POST /api/mode` | `{"mode": "auto" \| "open" \| "close"}` 手動オーバーライド |

## テスト

```bash
python -m unittest discover -s rice-water-manager/tests -v
```

## 安全上の注意

- 電磁弁・リレーの駆動電源（12V 系）と Raspberry Pi の 5V/3.3V 系は必ず分離し、GND のみ共通にしてください。
- 開弁したまま通信やソフトが停止する事態に備え、`max_open_minutes` は必ず妥当な値にしてください。可能なら手動の止水手段（ボールバルブ等）を併設してください。
- 屋外設置では防水・落雷・鳥獣害対策を行い、電源系統には適切なヒューズを入れてください。
