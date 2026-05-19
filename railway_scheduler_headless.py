import os
import sys
import time
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo("America/Sao_Paulo")

TICK_SECONDS = int(os.getenv("SCHED_TICK_SECONDS", "20"))
SALES_INTERVAL_MIN = int(os.getenv("SALES_INTERVAL_MIN", "20"))

# Cobrança/dashboard completo: a cada 2 horas, das 07:00 às 21:00
COBRANCA_HOURS = {7, 9, 11, 13, 15, 17, 19, 21}
COBRANCA_MINUTE_MAX = int(os.getenv("COBRANCA_RUN_MINUTE_MAX", "9"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SALES_CMD = [sys.executable, os.path.join(BASE_DIR, "dashboard_sales_worker_headless.py")]
COBRANCA_CMD = [sys.executable, os.path.join(BASE_DIR, "dashboard_railway_main_headless.py")]

_last_sales_slot = None
_last_cobranca_slot = None
_sales_proc = None
_cobranca_proc = None

_force_main_boot = True
_force_sales_boot = True


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


def sales_slot_key(dt_now):
    slot_minute = (dt_now.minute // SALES_INTERVAL_MIN) * SALES_INTERVAL_MIN
    return dt_now.strftime("%Y-%m-%d %H:") + f"{slot_minute:02d}"


def cobranca_slot_key(dt_now):
    return dt_now.strftime("%Y-%m-%d %H")


log("Scheduler Railway ativo | TZ=America/Sao_Paulo")
log("PRIORIDADE: MAIN/dashboard completo roda primeiro no boot e nas janelas de cobrança")
log(f"Vendas configuradas: depois do MAIN de boot + a cada {SALES_INTERVAL_MIN} minutos")
log("Cobrança/dashboard completo: a cada 2 horas, das 07:00 às 21:00")

while True:
    _sales_proc = maybe_finish_logs("vendas_servicos_caminhao", _sales_proc)
    _cobranca_proc = maybe_finish_logs("dashboard_completo_cobranca", _cobranca_proc)

    agora = now_br()
    sales_running = is_running(_sales_proc)
    cobranca_running = is_running(_cobranca_proc)

    _sales_key = sales_slot_key(agora)
    _cobranca_key = cobranca_slot_key(agora)

    _cobranca_ok = (
        agora.hour in COBRANCA_HOURS
        and 0 <= agora.minute <= COBRANCA_MINUTE_MAX
    )

    # PRIORIDADE 0: sempre publicar/gerar o dashboard completo primeiro ao subir o container.
    if _force_main_boot and (not sales_running) and (not cobranca_running):
        _force_main_boot = False
        _last_cobranca_slot = _cobranca_key
        _cobranca_proc = start_job("dashboard_completo_cobranca_boot_publica_html", COBRANCA_CMD)
        cobranca_running = True

    # PRIORIDADE 1: se chegou janela de cobrança/dashboard completo, MAIN passa na frente de vendas.
    elif (
        _cobranca_ok
        and (not sales_running)
        and (not cobranca_running)
        and (_last_cobranca_slot != _cobranca_key)
    ):
        _last_cobranca_slot = _cobranca_key
        _cobranca_proc = start_job("dashboard_completo_cobranca_prioridade", COBRANCA_CMD)
        cobranca_running = True

    # PRIORIDADE 2: vendas/serviços só roda quando MAIN não está rodando e não tem janela de cobrança pendente.
    elif (not _force_main_boot) and (not sales_running) and (not cobranca_running):
        if _force_sales_boot:
            _force_sales_boot = False
            _last_sales_slot = _sales_key
            _sales_proc = start_job("vendas_servicos_caminhao_boot", SALES_CMD)
            sales_running = True
        elif _last_sales_slot != _sales_key:
            _last_sales_slot = _sales_key
            _sales_proc = start_job("vendas_servicos_caminhao", SALES_CMD)
            sales_running = True

    log(
        f"tick | sales={sales_running} | cobranca={cobranca_running} | "
        f"sales_slot={_last_sales_slot} | cobranca_slot={_last_cobranca_slot}"
    )
    time.sleep(TICK_SECONDS)
