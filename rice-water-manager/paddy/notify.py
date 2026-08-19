"""Webhook 通知（Slack / Discord / LINE 等の Incoming Webhook を想定）。

{"text": "メッセージ"} を JSON で POST するだけの汎用実装。
URL 未設定ならログに出すだけ。同じ内容の連続通知は抑制する。
"""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str = ""):
        self.webhook_url = (webhook_url or "").strip()
        self._last_message: str | None = None

    def alert(self, message: str) -> None:
        if message == self._last_message:
            return  # 同一アラートの連投を抑制
        self._last_message = message
        log.warning("ALERT: %s", message)
        if not self.webhook_url:
            return
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps({"text": message}, ensure_ascii=False).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10).close()
        except Exception:
            log.exception("Webhook 通知の送信に失敗しました")

    def clear(self) -> None:
        """状態が正常に戻ったら呼び、次回の同一アラートを再送可能にする。"""
        self._last_message = None
