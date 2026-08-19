"""ダッシュボード Web アプリ (Flask)。"""

from __future__ import annotations

from flask import Flask, abort, jsonify, render_template_string, request, send_file

from .controller import MODE_AUTO, MODE_FORCE_CLOSE, MODE_FORCE_OPEN, Controller
from .storage import Storage

PAGE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>田んぼ水管理</title>
<style>
  :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
  body { margin: 0 auto; max-width: 720px; padding: 16px; }
  h1 { font-size: 1.3rem; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
  .card { border: 1px solid #8886; border-radius: 10px; padding: 12px; }
  .card .label { font-size: .8rem; opacity: .7; }
  .card .value { font-size: 1.6rem; font-weight: 700; }
  .open { color: #0a7; } .closed { color: #888; }
  button { padding: 8px 14px; margin-right: 8px; border-radius: 8px; border: 1px solid #8886; cursor: pointer; }
  button.active { background: #0a7; color: #fff; border-color: #0a7; }
  img { max-width: 100%; border-radius: 10px; margin-top: 8px; }
  canvas { width: 100%; height: 220px; }
  .err { color: #c33; }
</style>
</head>
<body>
<h1 id="title">田んぼ水管理</h1>
<div class="cards">
  <div class="card"><div class="label">水位</div><div class="value" id="level">--</div></div>
  <div class="card"><div class="label">目標水位</div><div class="value" id="target">--</div></div>
  <div class="card"><div class="label">バルブ</div><div class="value" id="valve">--</div></div>
  <div class="card"><div class="label">生育ステージ</div><div class="value" id="stage" style="font-size:1.1rem">--</div></div>
</div>
<p class="err" id="error"></p>
<h2 style="font-size:1.05rem">運転モード</h2>
<div id="modes">
  <button data-mode="auto">自動</button>
  <button data-mode="open">強制開</button>
  <button data-mode="close">強制閉</button>
</div>
<h2 style="font-size:1.05rem">水位の履歴（24時間）</h2>
<canvas id="chart" width="700" height="220"></canvas>
<h2 style="font-size:1.05rem">最新の写真</h2>
<img id="photo" alt="最新の田んぼの写真" src="/photo/latest">
<script>
async function refresh() {
  const s = await (await fetch('/api/status')).json();
  document.getElementById('title').textContent = (s.field_name || '田んぼ') + ' 水管理';
  document.getElementById('level').textContent = s.level_mm == null ? '--' : s.level_mm + ' mm';
  document.getElementById('target').textContent = s.target_mm + ' mm';
  const v = document.getElementById('valve');
  v.textContent = s.valve_open ? '開' : '閉';
  v.className = 'value ' + (s.valve_open ? 'open' : 'closed');
  document.getElementById('stage').textContent =
    (s.stage || '通常') + (s.stage_locked_closed ? '（給水停止中）' : '');
  document.getElementById('error').textContent = s.error ? '計測エラー: ' + s.error : '';
  for (const b of document.querySelectorAll('#modes button'))
    b.classList.toggle('active', b.dataset.mode === s.mode);
  drawChart(await (await fetch('/api/history?hours=24')).json());
}
function drawChart(rows) {
  const c = document.getElementById('chart'), ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);
  if (!rows.length) return;
  const pad = 30, w = c.width - pad * 2, h = c.height - pad * 2;
  const max = Math.max(...rows.map(r => Math.max(r.level_mm, r.target_mm)), 10) * 1.15;
  const x = i => pad + w * i / Math.max(1, rows.length - 1);
  const y = mm => pad + h * (1 - mm / max);
  ctx.strokeStyle = '#8888'; ctx.strokeRect(pad, pad, w, h);
  ctx.fillStyle = '#888'; ctx.font = '11px sans-serif';
  ctx.fillText(Math.round(max) + 'mm', 2, pad + 8); ctx.fillText('0', 2, pad + h);
  ctx.setLineDash([5, 4]); ctx.strokeStyle = '#e90';
  ctx.beginPath(); rows.forEach((r, i) => i ? ctx.lineTo(x(i), y(r.target_mm)) : ctx.moveTo(x(i), y(r.target_mm))); ctx.stroke();
  ctx.setLineDash([]); ctx.strokeStyle = '#09c'; ctx.lineWidth = 2;
  ctx.beginPath(); rows.forEach((r, i) => i ? ctx.lineTo(x(i), y(r.level_mm)) : ctx.moveTo(x(i), y(r.level_mm))); ctx.stroke();
  ctx.lineWidth = 1;
}
document.getElementById('modes').addEventListener('click', async e => {
  const mode = e.target.dataset.mode;
  if (!mode) return;
  await fetch('/api/mode', { method: 'POST', headers: {'Content-Type': 'application/json'},
                             body: JSON.stringify({ mode }) });
  refresh();
});
refresh();
setInterval(refresh, 15000);
document.getElementById('photo').addEventListener('error', e => e.target.style.display = 'none');
</script>
</body>
</html>"""


def create_app(controller: Controller, storage: Storage) -> Flask:
    app = Flask(__name__)

    @app.get("/")
    def index():
        return render_template_string(PAGE)

    @app.get("/api/status")
    def status():
        return jsonify(controller.last_status or {"level_mm": None})

    @app.get("/api/history")
    def history():
        hours = float(request.args.get("hours", 24))
        return jsonify(storage.history(hours=min(hours, 24 * 31)))

    @app.get("/photo/latest")
    def latest_photo():
        if not controller.camera:
            abort(404)
        photo = controller.camera.latest_photo()
        if not photo:
            abort(404)
        return send_file(photo)

    @app.post("/api/mode")
    def set_mode():
        data = request.get_json(silent=True) or {}
        mode = data.get("mode")
        if mode not in (MODE_AUTO, MODE_FORCE_OPEN, MODE_FORCE_CLOSE):
            abort(400)
        controller.set_mode(mode)
        return jsonify({"ok": True, "mode": controller.mode})

    return app
