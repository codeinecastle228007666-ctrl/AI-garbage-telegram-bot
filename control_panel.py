"""
Веб-панель управления ботом уведомлений.
Запуск: python control_panel.py
Открыть: http://localhost:8654

Можно добавить как закладку в OSP:
  Меню -> Настройки -> Закладки
  Имя: Панель бота
  Ссылка: http://localhost:8654
"""

import json
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HOST = "localhost"
PORT = 8654
PROJECT_DIR = Path(__file__).resolve().parent
CONTROL_SCRIPT = PROJECT_DIR / "bot_control.ps1"

PAGE = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bot Control</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
    background: #1a1a2e; color: #eee; display: flex;
    min-height: 100vh; align-items: center; justify-content: center;
  }}
  .card {{
    background: #16213e; border-radius: 16px; padding: 40px;
    box-shadow: 0 8px 32px rgba(0,0,0,0.4); text-align: center;
    min-width: 320px;
  }}
  h1 {{ font-size: 22px; margin-bottom: 24px; color: #e94560; }}
  .status {{
    font-size: 18px; margin: 20px 0; padding: 12px;
    border-radius: 8px;
  }}
  .status.running {{ background: #1b4332; color: #95d5b2; }}
  .status.stopped {{ background: #3d1c1c; color: #f5a5a5; }}
  .status.checking {{ background: #3d3520; color: #ffe066; }}
  .btn {{
    display: inline-block; padding: 14px 48px; margin: 12px 4px;
    font-size: 18px; font-weight: 600; border: none; border-radius: 8px;
    cursor: pointer; text-decoration: none; transition: all 0.2s;
  }}
  .btn:hover {{ transform: scale(1.03); }}
  .btn.start {{ background: #2d6a4f; color: #fff; }}
  .btn.start:hover {{ background: #40916c; }}
  .btn.stop {{ background: #9b2226; color: #fff; }}
  .btn.stop:hover {{ background: #c1121f; }}
  .btn:disabled {{ opacity: 0.5; cursor: not-allowed; transform: none; }}

  .pid {{ font-size: 12px; color: #888; margin-top: 16px; }}
  .links {{ margin-top: 20px; font-size: 13px; }}
  .links a {{ color: #4ea8de; text-decoration: none; }}
  .links a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="card">
  <h1>Bot Control</h1>
  <div id="status" class="status checking">Проверка...</div>
  <div>
    <button id="toggleBtn" class="btn" onclick="toggleBot()">...</button>
  </div>
  <div id="pid" class="pid"></div>
  <div class="links">
    <a href="https://t.me/stayproductivebot" target="_blank">Telegram</a>
    &middot;
    <a href="/api?action=status" target="api">API</a>
  </div>
</div>
<script>
async function getStatus() {{
  const r = await fetch('/api?action=status');
  return r.json();
}}

async function toggleBot() {{
  const btn = document.getElementById('toggleBtn');
  btn.disabled = true;
  const statusEl = document.getElementById('status');
  statusEl.textContent = 'Выполнение...';
  statusEl.className = 'status checking';

  const isRunning = btn.dataset.running === 'true';
  const action = isRunning ? 'stop' : 'start';
  const r = await fetch('/api?action=' + action);
  const data = await r.json();
  updateUI(data);
  btn.disabled = false;
}}

function updateUI(data) {{
  const statusEl = document.getElementById('status');
  const btn = document.getElementById('toggleBtn');
  const pidEl = document.getElementById('pid');

  if (data.status === 'BOT_RUNNING' || data.status === 'STARTED' || data.status === 'ALREADY_RUNNING') {{
    statusEl.textContent = 'Запущен';
    statusEl.className = 'status running';
    btn.textContent = 'Остановить';
    btn.className = 'btn stop';
    btn.dataset.running = 'true';
    pidEl.textContent = data.pid ? 'PID: ' + data.pid : data.message || '';
  }} else if (data.status === 'BOT_STOPPED' || data.status === 'STOPPED' || data.status === 'NOT_RUNNING') {{
    statusEl.textContent = 'Остановлен';
    statusEl.className = 'status stopped';
    btn.textContent = 'Запустить';
    btn.className = 'btn start';
    btn.dataset.running = 'false';
    pidEl.textContent = '';
  }} else {{
    statusEl.textContent = data.message || 'Неизвестно';
    statusEl.className = 'status stopped';
    btn.textContent = 'Запустить';
    btn.className = 'btn start';
    btn.dataset.running = 'false';
  }}
}}

getStatus().then(updateUI);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/api":
            action = params.get("action", ["status"])[0]
            result = self._run_control(action)
            self._json(result)
        else:
            self._html(PAGE)

    def _run_control(self, action: str) -> dict:
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy", "Bypass",
                    "-File", str(CONTROL_SCRIPT),
                    "-Action", action,
                ],
                capture_output=True, text=True, timeout=15,
                cwd=str(PROJECT_DIR),
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    data = json.loads(line)
                    return data

            return {"status": "ERROR", "message": result.stderr.strip() or "No JSON output"}

        except subprocess.TimeoutExpired:
            return {"status": "TIMEOUT", "message": "Команда не выполнена за 15 сек"}
        except Exception as e:
            return {"status": "EXCEPTION", "message": str(e)}

    def _json(self, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def main():
    server = HTTPServer((HOST, PORT), Handler)
    print(f"Панель управления: http://{HOST}:{PORT}")
    print("Нажми Ctrl+C для остановки панели")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nПанель остановлена")
        server.server_close()


if __name__ == "__main__":
    main()
