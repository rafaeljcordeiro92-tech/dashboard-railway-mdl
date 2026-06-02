# VERSAO: RAILWAY_SCHEDULER_MDL_MONITOR_TELEGRAM_V1
import json
import os
import sys
import time
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram_monitor_mdl import telegram_send, build_daily_summary, tail_file, now_br

BR_TZ = ZoneInfo("America/Sao_Paulo")

TICK_SECONDS = int(os.getenv("SCHED_TICK_SECONDS", "20"))
SALES_INTERVAL_MIN = int(os.getenv("SALES_INTERVAL_MIN", "20"))
DAILY_SUMMARY_HOUR = int(os.getenv("TELEGRAM_DAILY_SUMMARY_HOUR", "19"))
DAILY_SUMMARY_MINUTE_MAX = int(os.getenv("TELEGRAM_DAILY_SUMMARY_MINUTE_MAX", "9"))
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "1") != "0"

# Cobrança/dashboard completo: a cada 2 horas, das 07:00 às 21:00
COBRANCA_HOURS = {7, 9, 11, 13, 15, 17, 19, 21}
COBRANCA_MINUTE_MAX = int(os.getenv("COBRANCA_RUN_MINUTE_MAX", "9"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "monitor_logs")
os.makedirs(LOG_DIR, exist_ok=True)

STATUS_PATH = os.path.join(LOG_DIR, "monitor_status.json")
SCHED_LOG = os.path.join(LOG_DIR, "scheduler.log")
MAIN_LOG = os.path.join(LOG_DIR, "dashboard_completo_cobranca.log")
SALES_LOG = os.path.join(LOG_DIR, "vendas_unificadas.log")

SALES_CMD = [sys.executable, os.path.join(BASE_DIR, "dashboard_sales_worker_headless.py")]
COBRANCA_CMD = [sys.executable, os.path.join(BASE_DIR, "dashboard_railway_main_headless.py")]

_last_sales_slot = None
_last_cobranca_slot = None
_last_summary_date = None
_sales_proc = None
_cobranca_proc = None

_force_main_boot = True
_force_sales_boot = False
_force_sales_after_main = False

STATE = {
    "started_at": None,
    "updated_at": None,
    "scheduler": "starting",
    "telegram_enabled": TELEGRAM_ENABLED,
    "last_summary_date": None,
    "jobs": {
        "dashboard_completo_cobranca": {"running": False, "last_start": None, "last_end": None, "last_exit": None, "last_error": ""},
        "vendas_unificadas": {"running": False, "last_start": None, "last_end": None, "last_exit": None, "last_error": ""},
    },
    "recent_events": [],
}


def br_now():
    return datetime.now(BR_TZ)


def iso_now():
    return br_now().isoformat()


def _save_status():
    try:
        STATE["updated_at"] = iso_now()
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log(msg):
    line = f"[{iso_now()}] {msg}"
    print(line, flush=True)
    try:
        with open(SCHED_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    STATE.setdefault("recent_events", []).append(line)
    STATE["recent_events"] = STATE["recent_events"][-80:]
    _save_status()


def notify(text):
    if not TELEGRAM_ENABLED:
        return False
    ok, resp = telegram_send(text)
    if ok:
        log("📲 Telegram enviado com sucesso")
    else:
        log(f"⚠️ Falha Telegram: {resp}")
    return ok


def is_running(proc):
    return proc is not None and proc.poll() is None


def _job_log_path(name):
    return MAIN_LOG if "cobranca" in name or "dashboard" in name else SALES_LOG


def start_job(name, cmd):
    log_path = _job_log_path(name)
    log(f"▶ Iniciando job: {name}")
    STATE["jobs"].setdefault(name, {})
    STATE["jobs"][name].update({"running": True, "last_start": iso_now(), "last_end": None, "last_exit": None, "last_error": "", "log_path": log_path})
    _save_status()
    with open(log_path, "a", encoding="utf-8") as lf:
        lf.write("\n" + "="*90 + "\n")
        lf.write(f"INÍCIO {name} em {iso_now()}\n")
        lf.write("Comando: " + " ".join(cmd) + "\n")
        lf.write("="*90 + "\n")
    return subprocess.Popen(cmd, cwd=BASE_DIR, stdout=open(log_path, "a", encoding="utf-8"), stderr=subprocess.STDOUT)


def finish_if_done(name, proc):
    if proc is None:
        STATE["jobs"].setdefault(name, {}).update({"running": False})
        return None, False
    code = proc.poll()
    if code is None:
        STATE["jobs"].setdefault(name, {}).update({"running": True})
        _save_status()
        return proc, False

    STATE["jobs"].setdefault(name, {}).update({"running": False, "last_end": iso_now(), "last_exit": code})
    log(f"■ Fim job: {name} | exit={code}")

    if code != 0:
        tail = "\n".join(tail_file(_job_log_path(name), 28))
        STATE["jobs"][name]["last_error"] = tail[-1800:]
        _save_status()
        notify(
            "🚨 ERRO NO RAILWAY / COB+VENDAS\n"
            f"Job: {name}\n"
            f"Exit: {code}\n"
            f"Quando: {br_now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
            "Últimas linhas do log:\n"
            f"{tail[-2300:]}"
        )
    return None, True


def sales_slot_key(dt_now):
    slot_minute = (dt_now.minute // SALES_INTERVAL_MIN) * SALES_INTERVAL_MIN
    return dt_now.strftime("%Y-%m-%d %H:") + f"{slot_minute:02d}"


def cobranca_slot_key(dt_now):
    return dt_now.strftime("%Y-%m-%d %H")


def is_last_day_23_window(dt_now):
    tomorrow = dt_now + timedelta(days=1)
    return tomorrow.day == 1 and dt_now.hour == 23 and 0 <= dt_now.minute <= COBRANCA_MINUTE_MAX


def maybe_send_daily_summary(dt_now):
    global _last_summary_date
    if not TELEGRAM_ENABLED:
        return
    if not (dt_now.hour == DAILY_SUMMARY_HOUR and 0 <= dt_now.minute <= DAILY_SUMMARY_MINUTE_MAX):
        return
    day = dt_now.strftime("%Y-%m-%d")
    if _last_summary_date == day or STATE.get("last_summary_date") == day:
        return
    try:
        text = build_daily_summary(BASE_DIR, day)
        ok = notify(text)
        if ok:
            _last_summary_date = day
            STATE["last_summary_date"] = day
            _save_status()
    except Exception as e:
        notify(f"⚠️ Falha ao montar resumo diário COB+VENDAS: {e}")


def force_summary_now():
    text = build_daily_summary(BASE_DIR, br_now().strftime("%Y-%m-%d"))
    return telegram_send(text)


def force_run(kind):
    global _sales_proc, _cobranca_proc, _force_sales_after_main
    if kind == "main":
        if is_running(_sales_proc) or is_running(_cobranca_proc):
            return False, "Já existe job rodando. Aguarde finalizar."
        _cobranca_proc = start_job("dashboard_completo_cobranca_manual", COBRANCA_CMD)
        return True, "MAIN iniciado manualmente."
    if kind == "sales":
        if is_running(_sales_proc) or is_running(_cobranca_proc):
            return False, "Já existe job rodando. Aguarde finalizar."
        _sales_proc = start_job("vendas_unificadas_manual", SALES_CMD)
        return True, "SALES iniciado manualmente."
    return False, "Tipo inválido."


HTML = r'''
<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>COB+VENDAS Monitor Railway</title>
<style>
:root{--bg:#070a10;--card:#111722;--line:#263244;--txt:#eef2ff;--mut:#94a3b8;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b;--blue:#60a5fa}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#111827,#070a10 55%);font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--txt);padding:24px}.wrap{max-width:1180px;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.brand h1{margin:0;font-size:28px}.brand p{margin:6px 0 0;color:var(--mut)}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:20px 0}.card{background:rgba(17,24,39,.82);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 18px 55px rgba(0,0,0,.25)}.k{font-size:12px;color:var(--mut);font-weight:800;text-transform:uppercase;letter-spacing:.08em}.v{font-size:24px;font-weight:900;margin-top:8px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}button{border:0;border-radius:12px;padding:12px 16px;font-weight:900;cursor:pointer;color:#111827;background:#f59e0b}button.soft{background:#1f2937;color:var(--txt);border:1px solid var(--line)}button.blue{background:#2563eb;color:white}.jobs{display:grid;grid-template-columns:1fr 1fr;gap:14px}.row{display:grid;grid-template-columns:160px 1fr;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06)}pre{white-space:pre-wrap;background:#030712;border:1px solid var(--line);border-radius:14px;padding:14px;color:#d1d5db;max-height:430px;overflow:auto}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}@media(max-width:850px){.grid,.jobs{grid-template-columns:1fr}.row{grid-template-columns:1fr}}
</style></head><body><div class="wrap"><div class="top"><div class="brand"><h1>🚦 COB+VENDAS Monitor Railway</h1><p>Painel operacional do deploy, jobs, logs e Telegram.</p></div><div class="actions"><button onclick="run('main')">Rodar cobrança agora</button><button class="blue" onclick="run('sales')">Rodar vendas agora</button><button class="soft" onclick="sendSummary()">Enviar resumo Telegram</button><button class="soft" onclick="testTelegram()">Teste Telegram</button></div></div><div id="app">Carregando...</div></div>
<script>
const R=(v)=>v==null?'-':String(v).replace('T',' ').slice(0,19);
async function api(p,o){const r=await fetch(p,o);return await r.json()}
async function refresh(){const s=await api('/api/status'); const j=s.jobs||{}; const ev=(s.recent_events||[]).slice(-16).reverse().join('\n'); document.getElementById('app').innerHTML=`
<div class="grid"><div class="card"><div class="k">Scheduler</div><div class="v ok">${s.scheduler||'-'}</div></div><div class="card"><div class="k">Telegram</div><div class="v ${s.telegram_enabled?'ok':'warn'}">${s.telegram_enabled?'Ativo':'Desativado'}</div></div><div class="card"><div class="k">Resumo 19h</div><div class="v">${s.last_summary_date||'pendente'}</div></div><div class="card"><div class="k">Atualizado</div><div class="v" style="font-size:17px">${R(s.updated_at)}</div></div></div>
<div class="jobs">${Object.entries(j).map(([name,x])=>`<div class="card"><h2>${name}</h2><div class="row"><b>Status</b><span class="${x.running?'warn':'ok'}">${x.running?'Rodando':'Parado'}</span></div><div class="row"><b>Início</b><span>${R(x.last_start)}</span></div><div class="row"><b>Fim</b><span>${R(x.last_end)}</span></div><div class="row"><b>Exit</b><span class="${x.last_exit===0?'ok':(x.last_exit?'bad':'')}">${x.last_exit??'-'}</span></div>${x.last_error?`<h3 class="bad">Último erro</h3><pre>${x.last_error}</pre>`:''}</div>`).join('')}</div>
<div class="card" style="margin-top:14px"><h2>Eventos recentes</h2><pre>${ev}</pre></div>
<div class="card" style="margin-top:14px"><h2>Logs</h2><div class="actions"><button class="soft" onclick="loadLog('scheduler')">Scheduler</button><button class="soft" onclick="loadLog('main')">Cobrança/Main</button><button class="soft" onclick="loadLog('sales')">Vendas</button></div><pre id="logbox">Clique em um log.</pre></div>`}
async function loadLog(f){const r=await fetch('/api/logs?file='+f); document.getElementById('logbox').textContent=await r.text()}
async function run(k){const r=await api('/run/'+k,{method:'POST'}); alert(r.message||JSON.stringify(r)); refresh()}
async function sendSummary(){const r=await api('/telegram/summary',{method:'POST'}); alert(r.message||JSON.stringify(r))}
async function testTelegram(){const r=await api('/telegram/test',{method:'POST'}); alert(r.message||JSON.stringify(r))}
setInterval(refresh,5000); refresh();
</script></body></html>
'''


class Handler(BaseHTTPRequestHandler):
    def _send(self, code=200, body="", ctype="text/html; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=2)
            ctype = "application/json; charset=utf-8"
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            self._send(200, STATE)
        elif self.path.startswith("/api/logs"):
            q = self.path.split("?", 1)[-1]
            which = "scheduler"
            for part in q.split("&"):
                if part.startswith("file="):
                    which = part.split("=", 1)[1]
            path = SCHED_LOG if which == "scheduler" else (MAIN_LOG if which == "main" else SALES_LOG)
            self._send(200, "\n".join(tail_file(path, 260)), "text/plain; charset=utf-8")
        elif self.path.startswith("/health"):
            self._send(200, {"ok": True, "updated_at": iso_now()})
        else:
            self._send(200, HTML)

    def do_POST(self):
        if self.path.startswith("/run/main"):
            ok, msg = force_run("main")
            self._send(200, {"ok": ok, "message": msg})
        elif self.path.startswith("/run/sales"):
            ok, msg = force_run("sales")
            self._send(200, {"ok": ok, "message": msg})
        elif self.path.startswith("/telegram/test"):
            ok, resp = telegram_send("✅ Teste Telegram COB+VENDAS OK\n" + br_now().strftime("%d/%m/%Y %H:%M:%S"))
            self._send(200, {"ok": ok, "message": "Telegram enviado" if ok else resp})
        elif self.path.startswith("/telegram/summary"):
            ok, resp = force_summary_now()
            self._send(200, {"ok": ok, "message": "Resumo enviado" if ok else resp})
        else:
            self._send(404, {"ok": False, "message": "not found"})

    def log_message(self, fmt, *args):
        return


def start_http_panel():
    port = int(os.getenv("PORT", "3000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log(f"🌐 Painel monitor iniciado na porta {port}")
    server.serve_forever()


STATE["started_at"] = iso_now()
STATE["scheduler"] = "running"
_save_status()
threading.Thread(target=start_http_panel, daemon=True).start()

log("Scheduler Railway ativo | TZ=America/Sao_Paulo")
log("PRIORIDADE: MAIN/dashboard completo roda primeiro no boot e nas janelas de cobrança")
log(f"VENDAS UNIFICADAS: worker de vendas roda após cada MAIN e depois a cada {SALES_INTERVAL_MIN} minutos")
log("Cobrança/dashboard completo: a cada 2 horas, das 07:00 às 21:00 + fechamento automático no último dia às 23h")
log("Telegram: erro de job + resumo final diário")

while True:
    _sales_proc, _sales_finished = finish_if_done("vendas_unificadas", _sales_proc)
    _cobranca_proc, _cobranca_finished = finish_if_done("dashboard_completo_cobranca", _cobranca_proc)

    if _cobranca_finished:
        _force_sales_after_main = True

    agora = br_now()
    maybe_send_daily_summary(agora)

    sales_running = is_running(_sales_proc)
    cobranca_running = is_running(_cobranca_proc)

    _sales_key = sales_slot_key(agora)
    _cobranca_key = cobranca_slot_key(agora)

    _cobranca_ok = (
        (agora.hour in COBRANCA_HOURS and 0 <= agora.minute <= COBRANCA_MINUTE_MAX)
        or is_last_day_23_window(agora)
    )

    if _force_main_boot and (not sales_running) and (not cobranca_running):
        _force_main_boot = False
        _last_cobranca_slot = _cobranca_key
        _cobranca_proc = start_job("dashboard_completo_cobranca_boot_publica_html", COBRANCA_CMD)
        cobranca_running = True

    elif (
        _cobranca_ok
        and (not sales_running)
        and (not cobranca_running)
        and (_last_cobranca_slot != _cobranca_key)
    ):
        _last_cobranca_slot = _cobranca_key
        _cobranca_proc = start_job("dashboard_completo_cobranca_prioridade", COBRANCA_CMD)
        cobranca_running = True

    elif _force_sales_after_main and (not sales_running) and (not cobranca_running):
        _force_sales_after_main = False
        _force_sales_boot = False
        _last_sales_slot = _sales_key
        _sales_proc = start_job("vendas_unificadas_pos_main", SALES_CMD)
        sales_running = True

    elif (not sales_running) and (not cobranca_running):
        if _force_sales_boot:
            _force_sales_boot = False
            _last_sales_slot = _sales_key
            _sales_proc = start_job("vendas_unificadas_boot", SALES_CMD)
            sales_running = True
        elif _last_sales_slot != _sales_key:
            _last_sales_slot = _sales_key
            _sales_proc = start_job("vendas_unificadas", SALES_CMD)
            sales_running = True

    log(
        f"tick | sales={sales_running} | cobranca={cobranca_running} | "
        f"sales_slot={_last_sales_slot} | cobranca_slot={_last_cobranca_slot} | "
        f"force_sales_after_main={_force_sales_after_main}"
    )
    time.sleep(TICK_SECONDS)
