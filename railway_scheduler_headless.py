import os
import sys
import time
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo('America/Sao_Paulo')
TICK_SECONDS = int(os.getenv('SCHED_TICK_SECONDS', '20'))
RUN_HOURS = {7, 9, 11, 13, 15, 17, 19, 21}
RUN_MINUTE_MAX = int(os.getenv('SCHED_RUN_MINUTE_MAX', '9'))  # executa nos primeiros 10 min da hora-alvo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SALES_CMD = [sys.executable, os.path.join(BASE_DIR, 'dashboard_sales_worker_headless.py')]
COBRANCA_CMD = [sys.executable, os.path.join(BASE_DIR, 'dashboard_railway_main_headless.py')]

_last_run_key = None
_sales_proc = None
_cobranca_proc = None


def now_br():
    return datetime.now(BR_TZ)


def log(msg):
    print(f"[{now_br().isoformat()}] {msg}", flush=True)


def is_running(proc):
    return proc is not None and proc.poll() is None


def start_job(name, cmd):
    log(f"▶ Iniciando job: {name}")
    return subprocess.Popen(cmd, cwd=BASE_DIR)


def maybe_finish_logs(name, proc):
    if proc is None:
        return None
    code = proc.poll()
    if code is None:
        return proc
    log(f"■ Fim job: {name} | exit={code}")
    return None


log('Scheduler Railway ativo | TZ=America/Sao_Paulo')
log('Janela configurada: a cada 2 horas, das 07:00 às 21:00')

while True:
    _sales_proc = maybe_finish_logs('vendas_servicos_caminhao', _sales_proc)
    _cobranca_proc = maybe_finish_logs('dashboard_completo_cobranca', _cobranca_proc)

    agora = now_br()
    slot_key = agora.strftime('%Y-%m-%d %H')
    slot_ok = agora.hour in RUN_HOURS and 0 <= agora.minute <= RUN_MINUTE_MAX

    sales_running = is_running(_sales_proc)
    cobranca_running = is_running(_cobranca_proc)

    if slot_ok and _last_run_key != slot_key and not sales_running and not cobranca_running:
        _last_run_key = slot_key
        _sales_proc = start_job('vendas_servicos_caminhao', SALES_CMD)
        # roda cobrança logo depois de vendas terminar; não inicia junto para não sobrecarregar
    elif (_last_run_key == slot_key) and (_sales_proc is None) and (_cobranca_proc is None):
        # depois que vendas terminou no mesmo slot, inicia cobrança uma vez
        _cobranca_proc = start_job('dashboard_completo_cobranca', COBRANCA_CMD)
        # marca com sufixo para não repetir cobrança no mesmo slot
        _last_run_key = slot_key + ':done'

    log(f"tick | sales={sales_running} | cobranca={cobranca_running}")
    time.sleep(TICK_SECONDS)
