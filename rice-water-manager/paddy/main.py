"""エントリポイント。

    python -m paddy.main --config config.yaml            # 実機 or 自動判別
    python -m paddy.main --config config.yaml --simulate # 全部シミュレーション
    python -m paddy.main --config config.yaml --once     # 1回だけ実行 (cron 向け)
"""

from __future__ import annotations

import argparse
import json
import logging

from .camera import create_camera
from .config import Config
from .controller import Controller
from .notify import Notifier
from .sensors import create_sensor
from .storage import Storage
from .valve import create_valve


def build_controller(config: Config, simulate: bool = False) -> tuple[Controller, Storage]:
    sensor_cfg = config.section("sensor")
    valve_cfg = config.section("valve")
    camera_cfg = config.section("camera")
    if simulate:
        sensor_cfg["kind"] = "simulation"
        valve_cfg["kind"] = "simulation"
        if camera_cfg.get("kind") != "none":
            camera_cfg["kind"] = "simulation"

    storage = Storage(config.resolve_path(
        config.section("storage").get("db_path", "data/paddy.db")))
    controller = Controller(
        config=config,
        sensor=create_sensor(sensor_cfg),
        valve=create_valve(valve_cfg),
        storage=storage,
        notifier=Notifier(config.section("notify").get("webhook_url", "")),
        camera=create_camera(camera_cfg, base_dir=config.path.parent),
    )
    return controller, storage


def main() -> None:
    parser = argparse.ArgumentParser(description="田んぼ自動水管理デバイス")
    parser.add_argument("--config", default="config.yaml", help="設定ファイル")
    parser.add_argument("--simulate", action="store_true",
                        help="センサー・バルブ・カメラをすべて疑似動作させる")
    parser.add_argument("--once", action="store_true",
                        help="1 サイクルだけ実行して終了 (cron 運用向け)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    config = Config.load(args.config)
    controller, storage = build_controller(config, simulate=args.simulate)

    if args.once:
        try:
            print(json.dumps(controller.run_once(), ensure_ascii=False, indent=2))
        finally:
            controller.shutdown()
            storage.close()
        return

    controller.run_once()
    controller.start_background()

    from .webapp import create_app  # Flask 未導入でも --once は動くよう遅延 import
    web = config.section("web")
    app = create_app(controller, storage)
    try:
        app.run(host=web.get("host", "0.0.0.0"), port=int(web.get("port", 8000)))
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
