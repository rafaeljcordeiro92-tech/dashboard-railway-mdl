import os
import sys
import time
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
SALES_INTERVAL_MIN = 20
SALES_START_HOUR = 9
SALES_END_HOUR = 19
COB_TIMES = {(9, 0), (12, 0), (15, 0), (19, 0)}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SALES_SCRIPT = os.path.join(BASE_DIR, "dashboard_sales_worker_headless.py")
FULL_SCRIPT = os.path.join(BASE_DIR, "dashboard_railway_main_headless.py")


def is_business_day(dt):
    return dt.weekday() < 5


def should_run_sales(dt):
    if not is_business_day(dt):
        return False
    if dt.hour < SALES_START_HOUR or dt.hour > SALES_END_HOUR:
        return False
    if dt.hour == SALES_END_HOUR and dt.minute > 0:
        return False
    # dispara durante o minuto válido inteiro (00, 20, 40)
    return (dt.minute % SALES_INTERVAL_MIN == 0)


def should_run_cobranca(dt):
    return (dt.hour, dt.minute) in COB_TIMES


def run_job(script_path, label):
    print(f"[{datetime.now(TZ).isoformat()}] ▶ Iniciando job: {label}")
    result = subprocess.run([sys.executable, script_path], cwd=BASE_DIR)
    print(f"[{datetime.now(TZ).isoformat()}] ■ Fim job: {label} | exit={result.returncode}")


def main():
    print(f"Scheduler Railway ativo | TZ={TZ}")

    force_sales = os.getenv("FORCE_RUN_SALES_ON_BOOT", "0") == "1"
    force_cobranca = os.getenv("FORCE_RUN_COBRANCA_ON_BOOT", "0") == "1"

    if force_sales:
        run_job(SALES_SCRIPT, "vendas_servicos_caminhao_boot")
    if force_cobranca:
        run_job(FULL_SCRIPT, "dashboard_completo_cobranca_boot")

    last_sales_key = None
    last_cob_key = None

    while True:
        now = datetime.now(TZ)
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        sales_due = should_run_sales(now)
        cob_due = should_run_cobranca(now)

        print(f"[{now.isoformat()}] tick | sales={sales_due} | cobranca={cob_due}")

        if sales_due and minute_key != last_sales_key:
            run_job(SALES_SCRIPT, "vendas_servicos_caminhao")
            last_sales_key = minute_key

        if cob_due and minute_key != last_cob_key:
            run_job(FULL_SCRIPT, "dashboard_completo_cobranca")
            last_cob_key = minute_key

        # checa com mais precisão para não perder o minuto exato
        time.sleep(5)


if __name__ == "__main__":
    main()
