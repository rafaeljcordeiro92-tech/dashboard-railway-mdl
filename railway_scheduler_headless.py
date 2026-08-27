# V10_88_COB_EXTERNA_TESTE30_NOTIFICACAO
# V10_84_COB_HEADER_ROBUSTO
# VERSAO: RAILWAY_SCHEDULER_MDL_V10_82_COBRANCA_TERCEIRA_BACKOFF
import json
import os
import sys
import time
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ===== UTF-8 LOGS WINDOWS/RAILWAY =====
# Garante que subprocessos Python imprimam emojis/logs sem quebrar no cp1252.
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


try:
    from whatsapp_master_notificacoes import (
        whatsapp_send, build_whatsapp_daily_summary, tail_file, now_br,
        load_active_general_messages, build_general_message_alert,
        load_meta_diaria_batidas, build_meta_diaria_alert,
        load_meta_mercantil_100, build_meta_mercantil_100_alert,
        load_auditorias_master, build_audit_master_alert,
    )
    from telegram_monitor_mdl import telegram_send, build_daily_collection_summary
except Exception as e:
    def whatsapp_send(text, *a, **k): return (False, f"whatsapp notificações import erro: {e}")
    def build_whatsapp_daily_summary(base_dir, date_str=None): return f"Resumo indisponível: {e}"
    def tail_file(path, lines=60):
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f: return f.read().splitlines()[-lines:]
        except Exception: return []
    def now_br(): return datetime.now(ZoneInfo('America/Sao_Paulo'))
    def load_active_general_messages(base_dir): return []
    def build_general_message_alert(m): return 'Aviso geral indisponível'
    def load_meta_diaria_batidas(base_dir): return []
    def build_meta_diaria_alert(item, base_dir=None): return 'Meta diária indisponível'
    def load_meta_mercantil_100(base_dir): return []
    def build_meta_mercantil_100_alert(item, base_dir=None): return 'Meta mercantil 100% indisponível'
    def load_auditorias_master(base_dir): return []
    def build_audit_master_alert(item, base_dir=None): return 'Auditoria pendente no Dashboard'
    def telegram_send(text, *a, **k): return (False, f'telegram notificações import erro: {e}')
    def build_daily_collection_summary(base_dir, date_str=None): return f'Relatório diário de cobrança indisponível: {e}'

BR_TZ = ZoneInfo(os.getenv('APP_TZ', 'America/Sao_Paulo'))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, 'monitor_logs')
os.makedirs(LOG_DIR, exist_ok=True)

TICK_SECONDS = int(os.getenv('SCHED_TICK_SECONDS', '20'))
SALES_INTERVAL_MIN = int(os.getenv('SALES_INTERVAL_MIN', '20'))
COBRANCA_HOURS = {7, 9, 11, 13, 15, 17, 19, 21}
COBRANCA_MINUTE_MAX = int(os.getenv('COBRANCA_RUN_MINUTE_MAX', '9'))
COBRANCA_MIN_GAP_MIN = int(os.getenv('COBRANCA_MIN_GAP_MIN', '90'))
DAILY_SUMMARY_HOUR = int(os.getenv('TELEGRAM_DAILY_SUMMARY_HOUR', os.getenv('WHATSAPP_MASTER_DAILY_SUMMARY_HOUR', '19')))
DAILY_SUMMARY_MINUTE_MAX = int(os.getenv('TELEGRAM_DAILY_SUMMARY_MINUTE_MAX', os.getenv('WHATSAPP_MASTER_DAILY_SUMMARY_MINUTE_MAX', '9')))
DAILY_LISTS_HOUR = int(os.getenv('RELATORIOS_DIARIOS_HOUR', '7'))
DAILY_LISTS_MINUTE_MAX = int(os.getenv('RELATORIOS_DIARIOS_MINUTE_MAX', '20'))
COB_TERCEIRA_HOUR = int(os.getenv('COB_TERCEIRA_RUN_HOUR', '6'))
COB_TERCEIRA_MINUTE = int(os.getenv('COB_TERCEIRA_RUN_MINUTE', '30'))
COB_TERCEIRA_ENABLED = os.getenv('COB_TERCEIRA_ENABLED', '1') == '1'
COB_TERCEIRA_MANUAL_ONLY = os.getenv('COB_TERCEIRA_MANUAL_ONLY', '0') == '1'
COB_TERCEIRA_RETRY_MINUTES = max(5, int(os.getenv('COB_TERCEIRA_RETRY_MINUTES', '15')))
WHATSAPP_ALERTAS_ENABLED = os.getenv('WHATSAPP_MASTER_NOTIFICACOES_ALERTAS_ENABLED', '0') != '0'
WHATSAPP_ENABLED = os.getenv('WHATSAPP_MASTER_NOTIFICACOES_ENABLED', '0') != '0'
TELEGRAM_ENABLED = os.getenv('TELEGRAM_NOTIFICACOES_ENABLED', '1') != '0'
NOTIFICATION_CHANNEL = os.getenv('NOTIFICATION_CHANNEL', 'telegram').strip().lower() or 'telegram'
PREVENTIVA_ENABLED = os.getenv('WHATSAPP_MASTER_PREVENTIVA_ENABLED', '0') == '1'
FORCE_DAILY_LISTS_ON_BOOT = os.getenv('FORCE_DAILY_LISTS_ON_BOOT', os.getenv('FORCE_RUN_DAILY_LISTS_ON_BOOT', '0')) == '1'

SCHED_LOG = os.path.join(LOG_DIR, 'scheduler.log')
MAIN_LOG = os.path.join(LOG_DIR, 'dashboard_completo_cobranca.log')
SALES_LOG = os.path.join(LOG_DIR, 'vendas_unificadas.log')
PREVENTIVA_LOG = os.path.join(LOG_DIR, 'whatsapp_master_preventiva.log')
COB_TERCEIRA_LOG = os.path.join(LOG_DIR, 'cobranca_terceira.log')
PREVENTIVA_STATUS = os.path.join(BASE_DIR, 'whatsapp_master_preventiva_status.json')
PREVENTIVA_PREVIEW = os.path.join(BASE_DIR, 'whatsapp_master_preventiva_preview.json')
PREVENTIVA_HISTORY = os.path.join(BASE_DIR, 'whatsapp_master_preventiva_historico.json')
STATUS_PATH = os.path.join(LOG_DIR, 'monitor_status.json')

SALES_CMD = [sys.executable, os.path.join(BASE_DIR, 'dashboard_sales_worker_headless.py')]
COBRANCA_CMD = [sys.executable, os.path.join(BASE_DIR, 'dashboard_railway_main_headless.py')]
PREVENTIVA_CMD = [sys.executable, os.path.join(BASE_DIR, 'whatsapp_master_preventiva_worker.py')]
COB_TERCEIRA_CMD = [sys.executable, os.path.join(BASE_DIR, 'cobranca_terceira_worker_v1096.py')]

_sales_proc = None
_cobranca_proc = None
_preventiva_proc = None
_cob_terceira_proc = None
_last_sales_slot = None
_last_cobranca_slot = None
_last_cobranca_end = None
_last_summary_date = None
_last_cobranca_diaria_date = None
_force_main_boot = True
_force_sales_after_main = False

STATE = {
    'version': 'V10.99_TELEGRAM_COBRANCA_DIARIA_UPDATE_GUARD',
    'started_at': None,
    'updated_at': None,
    'scheduler': 'starting',
    'notification_channel': NOTIFICATION_CHANNEL,
    'telegram_notificacoes_enabled': TELEGRAM_ENABLED,
    'whatsapp_notificacoes_enabled': WHATSAPP_ENABLED,
    'last_summary_date': None,
    'last_cobranca_diaria_date': None,
    'last_daily_lists_date': None,
    'last_cob_terceira_date': None,
    'last_cob_terceira_attempt_at': None,
    'whatsapp_sent_message_ids': [],
    'whatsapp_sent_meta_keys': [],
    'whatsapp_sent_meta100_keys': [],
    'whatsapp_sent_audit_ids': [],
    'whatsapp_audit_watcher_initialized': False,
    'next_daily_lists_label': '',
    'next_sales_label': '',
    'next_cobranca_label': '',
    'jobs': {
        'dashboard_completo_cobranca': {'running': False, 'last_start': None, 'last_end': None, 'last_exit': None, 'last_error': ''},
        'vendas_unificadas': {'running': False, 'last_start': None, 'last_end': None, 'last_exit': None, 'last_error': ''},
        'whatsapp_master_preventiva': {'running': False, 'last_start': None, 'last_end': None, 'last_exit': None, 'last_error': ''},
        'cobranca_terceira': {'running': False, 'last_start': None, 'last_end': None, 'last_exit': None, 'last_error': ''},
    },
    'recent_events': []
}

# Carrega estado anterior para não reenviar alertas após restart.
try:
    if os.path.exists(STATUS_PATH):
        with open(STATUS_PATH, 'r', encoding='utf-8') as _f:
            _old_state = json.load(_f)
        for _k in ['last_summary_date','last_cobranca_diaria_date','last_daily_lists_date','last_cob_terceira_date','last_cob_terceira_attempt_at','whatsapp_sent_message_ids','whatsapp_sent_meta_keys','whatsapp_sent_meta100_keys','whatsapp_sent_audit_ids','whatsapp_audit_watcher_initialized']:
            if _k in _old_state:
                STATE[_k] = _old_state.get(_k)
except Exception:
    pass

def br_now(): return datetime.now(BR_TZ)
def iso_now(): return br_now().isoformat()

def _save_status():
    try:
        STATE['updated_at'] = iso_now()
        with open(STATUS_PATH, 'w', encoding='utf-8') as f: json.dump(STATE, f, ensure_ascii=False, indent=2)
    except Exception: pass

def log(msg):
    line = f"[{iso_now()}] {msg}"
    print(line, flush=True)
    try:
        with open(SCHED_LOG, 'a', encoding='utf-8') as f: f.write(line + '\n')
    except Exception: pass
    STATE.setdefault('recent_events', []).append(line)
    STATE['recent_events'] = STATE['recent_events'][-120:]
    _save_status()

def notify(text, alert_type='erros'):
    channel = NOTIFICATION_CHANNEL
    if channel == 'telegram':
        if not TELEGRAM_ENABLED: return False
        try: ok, resp = telegram_send(text, alert_type=alert_type, base_dir=BASE_DIR)
        except TypeError: ok, resp = telegram_send(text, alert_type=alert_type)
        log(f'📲 Telegram enviado ({alert_type})' if ok else f'⚠️ Falha Telegram ({alert_type}): {resp}')
        return ok
    if channel == 'whatsapp':
        if not WHATSAPP_ENABLED: return False
        try: ok, resp = whatsapp_send(text, alert_type=alert_type, base_dir=BASE_DIR)
        except TypeError: ok, resp = whatsapp_send(text, alert_type=alert_type)
        log(f'💬 WhatsApp Master enviado ({alert_type})' if ok else f'⚠️ Falha WhatsApp Master ({alert_type}): {resp}')
        return ok
    if channel == 'dual':
        ok_t = ok_w = False
        if TELEGRAM_ENABLED:
            try: ok_t, _ = telegram_send(text, alert_type=alert_type, base_dir=BASE_DIR)
            except Exception: ok_t = False
        if WHATSAPP_ENABLED:
            try: ok_w, _ = whatsapp_send(text, alert_type=alert_type, base_dir=BASE_DIR)
            except Exception: ok_w = False
        log(f'📣 Canal dual ({alert_type}) Telegram={ok_t} WhatsApp={ok_w}')
        return ok_t or ok_w
    return False

def is_running(proc): return proc is not None and proc.poll() is None

def _job_log_path(name):
    if 'terceira' in name or 'cob_externa' in name: return COB_TERCEIRA_LOG
    if 'preventiva' in name or 'whatsapp_master' in name: return PREVENTIVA_LOG
    return MAIN_LOG if 'cobranca' in name or 'dashboard' in name else SALES_LOG

def _state_job_key(name):
    if 'terceira' in name or 'cob_externa' in name: return 'cobranca_terceira'
    if 'preventiva' in name or 'whatsapp_master' in name: return 'whatsapp_master_preventiva'
    return 'dashboard_completo_cobranca' if 'cobranca' in name or 'dashboard' in name else 'vendas_unificadas'

def start_job(name, cmd, extra_env=None):
    key = _state_job_key(name)
    log_path = _job_log_path(name)
    log(f'▶ Iniciando job: {name}')
    STATE['jobs'][key].update({'running': True, 'last_start': iso_now(), 'last_end': None, 'last_exit': None, 'last_error': '', 'display_name': name, 'log_path': log_path})
    _save_status()
    with open(log_path, 'a', encoding='utf-8') as lf:
        lf.write('\n' + '='*90 + '\n')
        lf.write(f'INÍCIO {name} em {iso_now()}\n')
        lf.write('Comando: ' + ' '.join(cmd) + '\n')
        if extra_env:
            lf.write('Env extra: ' + json.dumps(extra_env, ensure_ascii=False) + '\n')
        lf.write('='*90 + '\n')
    
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    if key == 'whatsapp_master_preventiva':
        env['WHATSAPP_MASTER_STDOUT_CAPTURED'] = '1'
    return subprocess.Popen(cmd, cwd=BASE_DIR, env=env, stdout=open(log_path, 'a', encoding='utf-8'), stderr=subprocess.STDOUT)

def finish_if_done(name, proc):
    global _last_cobranca_end
    key = _state_job_key(name)
    if proc is None:
        STATE['jobs'][key]['running'] = False
        return None, False
    code = proc.poll()
    if code is None:
        STATE['jobs'][key]['running'] = True
        _save_status()
        return proc, False
    STATE['jobs'][key].update({'running': False, 'last_end': iso_now(), 'last_exit': code})
    log(f'■ Fim job: {name} | exit={code}')
    if key == 'dashboard_completo_cobranca': _last_cobranca_end = br_now()
    if key == 'cobranca_terceira' and code == 0:
        STATE['last_cob_terceira_date'] = br_now().strftime('%Y-%m-%d')
        _save_status()
    if code != 0:
        tail = '\n'.join(tail_file(_job_log_path(name), 35))
        STATE['jobs'][key]['last_error'] = tail[-2500:]
        _save_status()
        notify('🚨 ERRO NO RAILWAY / COB+VENDAS\n' + f'Job: {name}\nExit: {code}\nQuando: {br_now().strftime("%d/%m/%Y %H:%M:%S")}\n\nÚltimas linhas:\n{tail[-2500:]}')
    return None, True

def sales_slot_key(dt):
    slot = (dt.minute // SALES_INTERVAL_MIN) * SALES_INTERVAL_MIN
    return dt.strftime('%Y-%m-%d %H:') + f'{slot:02d}'

def cobranca_slot_key(dt): return dt.strftime('%Y-%m-%d %H')

def is_last_day_23_window(dt):
    return (dt + timedelta(days=1)).day == 1 and dt.hour == 23 and 0 <= dt.minute <= COBRANCA_MINUTE_MAX

def next_sales_time(dt):
    minute = ((dt.minute // SALES_INTERVAL_MIN) + 1) * SALES_INTERVAL_MIN
    nxt = dt.replace(second=0, microsecond=0)
    if minute >= 60: return (nxt + timedelta(hours=1)).replace(minute=0)
    return nxt.replace(minute=minute)

def next_cobranca_time(dt):
    for d in range(0, 4):
        base = (dt + timedelta(days=d)).date()
        for h in sorted(COBRANCA_HOURS):
            cand = datetime(base.year, base.month, base.day, h, 0, 0, 0, tzinfo=BR_TZ)
            if cand > dt: return cand
    return dt + timedelta(hours=2)

def next_cob_terceira_time(dt):
    for d in range(0, 4):
        base = (dt + timedelta(days=d)).date()
        cand = datetime(base.year, base.month, base.day, COB_TERCEIRA_HOUR, COB_TERCEIRA_MINUTE, 0, 0, tzinfo=BR_TZ)
        if cand > dt and (d > 0 or STATE.get('last_cob_terceira_date') != dt.strftime('%Y-%m-%d')):
            return cand
    return dt + timedelta(days=1)

def _parse_iso_state_dt(v):
    try:
        x = datetime.fromisoformat(str(v or '').replace('Z', '+00:00'))
        if x.tzinfo is None:
            x = x.replace(tzinfo=BR_TZ)
        return x.astimezone(BR_TZ)
    except Exception:
        return None

def cob_terceira_due(dt):
    if not COB_TERCEIRA_ENABLED:
        return False
    day = dt.strftime('%Y-%m-%d')
    scheduled = dt.replace(hour=COB_TERCEIRA_HOUR, minute=COB_TERCEIRA_MINUTE, second=0, microsecond=0)
    if dt < scheduled or STATE.get('last_cob_terceira_date') == day:
        return False
    last_attempt = _parse_iso_state_dt(STATE.get('last_cob_terceira_attempt_at'))
    if last_attempt and (dt - last_attempt).total_seconds() < COB_TERCEIRA_RETRY_MINUTES * 60:
        return False
    return True

def next_daily_lists_time(dt):
    for d in range(0, 4):
        base = (dt + timedelta(days=d)).date()
        cand = datetime(base.year, base.month, base.day, DAILY_LISTS_HOUR, 0, 0, tzinfo=BR_TZ)
        if cand > dt:
            return cand
    return dt + timedelta(days=1)

def daily_lists_due(dt):
    day = dt.strftime('%Y-%m-%d')
    return (dt.hour == DAILY_LISTS_HOUR and 0 <= dt.minute <= DAILY_LISTS_MINUTE_MAX and STATE.get('last_daily_lists_date') != day)

def main_job_env(with_daily_lists=False):
    return {
        'BAIXAR_CLIENTES_SEM_MOVIMENTO': '1' if with_daily_lists else '0',
        'BAIXAR_ANIVERSARIANTES': '1' if with_daily_lists else '0',
    }

def fmt_delta(target):
    sec = max(0, int((target - br_now()).total_seconds()))
    h, rem = divmod(sec, 3600); m, s = divmod(rem, 60)
    return f'{h}h {m:02d}m {s:02d}s' if h else f'{m:02d}m {s:02d}s'

def maybe_send_daily_summary(now):
    global _last_summary_date
    if NOTIFICATION_CHANNEL == 'telegram' and not TELEGRAM_ENABLED: return
    if NOTIFICATION_CHANNEL == 'whatsapp' and not WHATSAPP_ENABLED: return
    if not (now.hour == DAILY_SUMMARY_HOUR and 0 <= now.minute <= DAILY_SUMMARY_MINUTE_MAX): return
    day = now.strftime('%Y-%m-%d')
    if _last_summary_date == day or STATE.get('last_summary_date') == day: return
    try:
        ok = notify(build_whatsapp_daily_summary(BASE_DIR, day), 'resumo')
        if ok:
            _last_summary_date = day
            STATE['last_summary_date'] = day
            _save_status()
    except Exception as e:
        notify(f'⚠️ Falha ao montar resumo diário COB+VENDAS para Telegram: {e}', 'erros')


def maybe_send_daily_collection_report(now):
    """V10.99: relatório separado de cobrança diária, roteado pelo checkbox 'Cobrança diária' de cada Chat ID."""
    global _last_cobranca_diaria_date
    if not TELEGRAM_ENABLED:
        return
    if not (now.hour == DAILY_SUMMARY_HOUR and 0 <= now.minute <= DAILY_SUMMARY_MINUTE_MAX):
        return
    day = now.strftime('%Y-%m-%d')
    if _last_cobranca_diaria_date == day or STATE.get('last_cobranca_diaria_date') == day:
        return
    try:
        text = build_daily_collection_summary(BASE_DIR, day)
        ok, resp = telegram_send(text, alert_type='cobranca_diaria', base_dir=BASE_DIR)
        if ok:
            _last_cobranca_diaria_date = day
            STATE['last_cobranca_diaria_date'] = day
            _save_status()
            log(f'📞 Relatório diário de cobrança Telegram enviado: {resp}')
        else:
            log(f'ℹ️ Relatório diário de cobrança não enviado: {resp}')
    except Exception as e:
        log(f'⚠️ Falha relatório diário de cobrança Telegram: {e}')


def _force_daily_collection_worker():
    try:
        day = br_now().strftime('%Y-%m-%d')
        text = build_daily_collection_summary(BASE_DIR, day)
        ok, resp = telegram_send(text, alert_type='cobranca_diaria', base_dir=BASE_DIR)
        log('📞 Relatório diário de cobrança Telegram manual enviado' if ok else f'⚠️ Falha relatório diário cobrança manual: {resp}')
    except Exception as e:
        log(f'⚠️ Erro montando relatório diário cobrança manual: {e}')


def force_daily_collection_now():
    threading.Thread(target=_force_daily_collection_worker, daemon=True).start()
    return True, 'Relatório diário de cobrança Telegram enfileirado. Será enviado somente aos Chat IDs marcados em Cobrança diária.'


def maybe_send_general_message_alerts(now):
    if NOTIFICATION_CHANNEL == 'telegram' and not TELEGRAM_ENABLED: return
    if NOTIFICATION_CHANNEL == 'whatsapp' and not (WHATSAPP_ENABLED and WHATSAPP_ALERTAS_ENABLED): return
    sent = set(STATE.get('whatsapp_sent_message_ids') or [])
    try:
        for m in load_active_general_messages(BASE_DIR):
            mid = str(m.get('id') or '')
            if not mid or mid in sent:
                continue
            # Evita disparar avisos antigos existentes antes da implantação do watcher.
            ts = None
            try:
                from telegram_monitor_mdl import _parse_dt_any
                ts = _parse_dt_any(m.get('server_time'))
            except Exception:
                ts = None
            started = None
            try:
                started = datetime.fromisoformat(str(STATE.get('started_at'))).astimezone(BR_TZ)
            except Exception:
                started = now - timedelta(minutes=5)
            if ts and ts < (started - timedelta(minutes=2)):
                sent.add(mid)
                continue
            ok = notify(build_general_message_alert(m), 'avisos')
            if ok:
                sent.add(mid)
        STATE['whatsapp_sent_message_ids'] = list(sent)[-500:]
        _save_status()
    except Exception as e:
        log(f'⚠️ Falha watcher Telegram avisos gerais: {e}')

def maybe_send_meta_diaria_alerts(now):
    if NOTIFICATION_CHANNEL == 'telegram' and not TELEGRAM_ENABLED: return
    if NOTIFICATION_CHANNEL == 'whatsapp' and not (WHATSAPP_ENABLED and WHATSAPP_ALERTAS_ENABLED): return
    sent = set(STATE.get('whatsapp_sent_meta_keys') or [])
    today_prefix = now.strftime('%Y-%m-%d')
    try:
        for item in load_meta_diaria_batidas(BASE_DIR):
            key = today_prefix + '|' + str(item.get('key') or '')
            if not key or key in sent:
                continue
            ok = notify(build_meta_diaria_alert(item), 'meta_diaria')
            if ok:
                sent.add(key)
        # mantém somente chaves recentes/atuais para não crescer infinito
        STATE['whatsapp_sent_meta_keys'] = [k for k in list(sent)[-800:] if k.startswith(today_prefix) or len(k) < 250]
        _save_status()
    except Exception as e:
        log(f'⚠️ Falha watcher Telegram meta diária: {e}')


def maybe_send_meta_mercantil_100_alerts(now):
    """WhatsApp Master quando filial/vendedor bater 100% da meta mercantil mensal."""
    if NOTIFICATION_CHANNEL == 'telegram' and not TELEGRAM_ENABLED: return
    if NOTIFICATION_CHANNEL == 'whatsapp' and not (WHATSAPP_ENABLED and WHATSAPP_ALERTAS_ENABLED): return
    sent = set(STATE.get('whatsapp_sent_meta100_keys') or [])
    month_prefix = now.strftime('%Y-%m')
    try:
        for item in load_meta_mercantil_100(BASE_DIR):
            key = month_prefix + '|' + str(item.get('key') or '')
            if not key or key in sent:
                continue
            ok = notify(build_meta_mercantil_100_alert(item), 'meta_mensal')
            if ok:
                sent.add(key)
        # mantém chaves do mês atual e um limite para não crescer infinito
        STATE['whatsapp_sent_meta100_keys'] = [k for k in list(sent)[-1000:] if k.startswith(month_prefix) or len(k) < 250]
        _save_status()
    except Exception as e:
        log(f'⚠️ Falha watcher Telegram meta mercantil 100%: {e}')

def maybe_send_audit_master_alerts(now):
    """Avisa somente novos casos que realmente precisam de decisão humana."""
    if NOTIFICATION_CHANNEL == 'telegram' and not TELEGRAM_ENABLED: return
    if NOTIFICATION_CHANNEL == 'whatsapp' and not (WHATSAPP_ENABLED and WHATSAPP_ALERTAS_ENABLED): return
    try:
        items = load_auditorias_master(BASE_DIR)
        ids = [str(x.get('id') or '') for x in items if x.get('id')]
        sent = set(STATE.get('whatsapp_sent_audit_ids') or [])
        if not STATE.get('whatsapp_audit_watcher_initialized'):
            # Evita disparar todo o passivo antigo no primeiro deploy.
            STATE['whatsapp_sent_audit_ids'] = ids[-1000:]
            STATE['whatsapp_audit_watcher_initialized'] = True
            _save_status()
            log(f'🧑‍⚖️ Watcher auditoria iniciado com {len(ids)} caso(s) já existentes; próximos casos serão avisados.')
            return
        for item in items:
            item_id = str(item.get('id') or '')
            if not item_id or item_id in sent:
                continue
            ok = notify(build_audit_master_alert(item, BASE_DIR), 'auditoria')
            if ok:
                sent.add(item_id)
        STATE['whatsapp_sent_audit_ids'] = list(sent)[-1500:]
        _save_status()
    except Exception as e:
        log(f'⚠️ Falha watcher Telegram auditoria: {e}')


def _force_summary_worker():
    try:
        day = br_now().strftime('%Y-%m-%d')
        text = build_whatsapp_daily_summary(BASE_DIR, day)
        if NOTIFICATION_CHANNEL == 'telegram':
            ok, resp = telegram_send(text, alert_type='resumo', base_dir=BASE_DIR)
            log('📲 Resumo Telegram manual enviado' if ok else f'⚠️ Falha resumo Telegram manual: {resp}')
        else:
            ok, resp = whatsapp_send(text, alert_type='resumo', base_dir=BASE_DIR)
            log('💬 Resumo WhatsApp manual enviado' if ok else f'⚠️ Falha resumo WhatsApp manual: {resp}')
    except Exception as e:
        log(f'⚠️ Erro montando/enviando resumo manual: {e}')


def force_summary_now():
    threading.Thread(target=_force_summary_worker, daemon=True).start()
    return True, f'Resumo {NOTIFICATION_CHANNEL} enfileirado. Confira o log em alguns segundos.'


def _load_json_safe(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def preventiva_status_payload():
    preview = _load_json_safe(PREVENTIVA_STATUS, None) or _load_json_safe(PREVENTIVA_PREVIEW, {})
    return {
        'ok': True,
        'updated_at': iso_now(),
        'job': dict(STATE.get('jobs', {}).get('whatsapp_master_preventiva', {})),
        'preview': preview,
        'service': preview.get('service') if isinstance(preview, dict) else {},
        'history_available': os.path.exists(PREVENTIVA_HISTORY),
    }


def preventiva_history_payload():
    return _load_json_safe(PREVENTIVA_HISTORY, {'version':'V10.49','runs':[]})

def force_run(kind):
    global _sales_proc, _cobranca_proc, _preventiva_proc, _cob_terceira_proc, _force_sales_after_main
    if kind == 'cob_terceira':
        if is_running(_cob_terceira_proc): return False, 'Cobrança Terceira já está rodando.'
        if is_running(_sales_proc) or is_running(_cobranca_proc): return False, 'Existe Selenium do dashboard rodando. Aguarde finalizar.'
        STATE['last_cob_terceira_attempt_at'] = iso_now()
        _save_status()
        _cob_terceira_proc = start_job('cobranca_terceira_manual', COB_TERCEIRA_CMD)
        return True, 'Cobrança Terceira iniciada. Confira o log; DRY RUN permanece controlado por variável.'
    if kind == 'preventiva':
        if not PREVENTIVA_ENABLED: return False, 'WhatsApp Master está em standby (WHATSAPP_MASTER_PREVENTIVA_ENABLED=0).'
        if is_running(_preventiva_proc): return False, 'Preventiva WhatsApp Master já está rodando.'
        _preventiva_proc = start_job('whatsapp_master_preventiva_manual', PREVENTIVA_CMD)
        return True, 'Preventiva WhatsApp Master iniciada em modo configurado. Confira o log/preview.'
    if is_running(_sales_proc) or is_running(_cobranca_proc): return False, 'Já existe job rodando. Aguarde finalizar.'
    if kind == 'main':
        _force_sales_after_main = True
        _cobranca_proc = start_job('dashboard_completo_cobranca_manual', COBRANCA_CMD, main_job_env(False))
        return True, 'Cobrança/Main iniciado. Vendas rodará depois que ele terminar.'
    if kind == 'sales':
        _sales_proc = start_job('vendas_unificadas_manual', SALES_CMD)
        return True, 'Vendas iniciado manualmente.'
    return False, 'Tipo inválido.'

HTML = '<!doctype html><html lang="pt-br"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>COB+VENDAS Monitor Railway</title><style>:root{--bg:#070a10;--card:#111827;--line:#263244;--txt:#eef2ff;--mut:#94a3b8;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at top,#111827,#070a10 55%);font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--txt);padding:24px}.wrap{max-width:1180px;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.brand h1{margin:0;font-size:28px}.brand p{margin:6px 0 0;color:var(--mut)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:20px 0}.card{background:rgba(17,24,39,.86);border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 18px 55px rgba(0,0,0,.25)}.k{font-size:12px;color:var(--mut);font-weight:900;text-transform:uppercase;letter-spacing:.08em}.v{font-size:24px;font-weight:900;margin-top:8px}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}button{border:0;border-radius:12px;padding:12px 16px;font-weight:900;cursor:pointer;color:#111827;background:#f59e0b}button.soft{background:#1f2937;color:var(--txt);border:1px solid var(--line)}button.blue{background:#2563eb;color:white}button.active{outline:2px solid #f59e0b}.jobs{display:grid;grid-template-columns:1fr 1fr;gap:14px}.row{display:grid;grid-template-columns:160px 1fr;gap:8px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06)}pre{white-space:pre-wrap;background:#030712;border:1px solid var(--line);border-radius:14px;padding:14px;color:#d1d5db;max-height:430px;overflow:auto}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}.logbox{height:560px;max-height:70vh;font-family:Consolas,monospace;font-size:12px;line-height:1.35}.mut{color:var(--mut)}@media(max-width:850px){.grid,.jobs{grid-template-columns:1fr}.row{grid-template-columns:1fr}.logbox{height:420px}}</style></head><body><div class="wrap"><div class="top"><div class="brand"><h1>🚦 COB+VENDAS Monitor Railway</h1><p>Ordem: Cobrança Terceira D+91 roda 1x/dia às 06:30; cobrança/recebimentos a cada 2h; vendas a cada 20min; listas pesadas às 07h.</p></div><div class="actions"><button onclick="run(\'main\')">Rodar cobrança agora</button><button class="blue" onclick="run(\'sales\')">Rodar vendas agora</button><button class="soft" onclick="sendSummary()">Enviar resumo Telegram</button><button class="soft" onclick="sendCobDaily()">Cobrança diária Telegram</button><button class="soft" onclick="testTelegram()">Teste Telegram</button><button class="soft" onclick="run(\'preventiva\')">WhatsApp Master · standby</button><button class="soft" onclick="run(\'cob_terceira\')">Rodar COB Terceira</button></div></div><div id="app">Carregando...</div><div class="card" id="logsCard" style="margin-top:14px"><h2>Logs</h2><div class="actions"><button class="soft" data-log="scheduler" onclick="loadLog(\'scheduler\')">Scheduler</button><button class="soft" data-log="main" onclick="loadLog(\'main\')">Cobrança/Main</button><button class="soft" data-log="sales" onclick="loadLog(\'sales\')">Vendas</button><button class="soft" data-log="preventiva" onclick="loadLog(\'preventiva\')">WhatsApp Master</button><button class="soft" data-log="cob_terceira" onclick="loadLog(\'cob_terceira\')">COB Terceira</button><button class="soft" onclick="togglePause()" id="pauseBtn">Pausar atualização</button></div><div class="mut" id="logStatus">Clique em um log. A tela não será mais recriada quando você estiver lendo.</div><pre id="logbox" class="logbox">Clique em um log.</pre></div></div><script>const R=v=>v==null?\'-\':String(v).replace(\'T\',\' \').slice(0,19);let selectedLog=\'\';let paused=false;let refreshing=false;async function api(p,o){const r=await fetch(p,o);return await r.json()}function esc(s){return String(s??\'\').replace(/[&<>]/g,m=>({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\'}[m]))}async function refresh(){if(paused||refreshing)return;refreshing=true;try{const s=await api(\'/api/status\');const j=s.jobs||{};const ev=(s.recent_events||[]).slice(-18).reverse().join(\'\\n\');document.getElementById(\'app\').innerHTML=`<div class="grid"><div class="card"><div class="k">Scheduler</div><div class="v ok">${s.scheduler||\'-\'}</div></div><div class="card"><div class="k">Próxima vendas</div><div class="v warn">${s.next_sales_label||\'-\'}</div></div><div class="card"><div class="k">Próxima cobrança</div><div class="v warn">${s.next_cobranca_label||\'-\'}</div></div><div class="card"><div class="k">Próxima COB Terceira</div><div class="v warn">${s.next_cob_terceira_label||\'-\'}</div></div><div class="card"><div class="k">Listas 07h</div><div class="v warn">${s.next_daily_lists_label||\'-\'}</div></div><div class="card"><div class="k">Atualizado</div><div class="v" style="font-size:17px">${R(s.updated_at)}</div></div></div><div class="jobs">${Object.entries(j).map(([name,x])=>`<div class="card"><h2>${name}</h2><div class="row"><b>Status</b><span class="${x.running?\'warn\':\'ok\'}">${x.running?\'Rodando\':\'Parado\'}</span></div><div class="row"><b>Início</b><span>${R(x.last_start)}</span></div><div class="row"><b>Fim</b><span>${R(x.last_end)}</span></div><div class="row"><b>Exit</b><span class="${x.last_exit===0?\'ok\':(x.last_exit?\'bad\':\'\')}">${x.last_exit??\'-\'}</span></div>${x.last_error?`<h3 class="bad">Último erro</h3><pre>${esc(x.last_error)}</pre>`:\'\'}</div>`).join(\'\')}</div><div class="card" style="margin-top:14px"><h2>Eventos recentes</h2><pre>${esc(ev)}</pre></div>`; if(selectedLog) await loadLog(selectedLog,true);}finally{refreshing=false}}async function loadLog(f,keepScroll=false){selectedLog=f;document.querySelectorAll(\'[data-log]\').forEach(b=>b.classList.toggle(\'active\',b.dataset.log===f));const box=document.getElementById(\'logbox\');const status=document.getElementById(\'logStatus\');const nearBottom=box && (box.scrollHeight-box.scrollTop-box.clientHeight<80);const oldTop=box?box.scrollTop:0;const r=await fetch(\'/api/logs?file=\'+encodeURIComponent(f)+\'&_=\'+Date.now());const txt=await r.text();if(box){box.textContent=txt||\'Sem log ainda.\'; if(keepScroll&&!nearBottom) box.scrollTop=oldTop; else box.scrollTop=box.scrollHeight;}if(status)status.textContent=\'Exibindo: \'+f+\' • atualizado \'+new Date().toLocaleTimeString(\'pt-BR\')+\'.\'}function togglePause(){paused=!paused;document.getElementById(\'pauseBtn\').textContent=paused?\'Retomar atualização\':\'Pausar atualização\';}async function run(k){const r=await api(\'/run/\'+k,{method:\'POST\'});alert(r.message||JSON.stringify(r));refresh()}async function sendSummary(){const r=await api(\'/telegram/summary\',{method:\'POST\'});alert(r.message||JSON.stringify(r))}async function testTelegram(){const r=await api(\'/telegram/test\',{method:\'POST\'});alert(r.message||JSON.stringify(r))}setInterval(refresh,7000);refresh();</script></body></html>'

class Handler(BaseHTTPRequestHandler):
    def _send(self, code=200, body='', ctype='text/html; charset=utf-8'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False, indent=2); ctype='application/json; charset=utf-8'
        data = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers(); self.wfile.write(data)
    def do_OPTIONS(self):
        self._send(204, '', 'text/plain; charset=utf-8')
    def do_GET(self):
        if self.path.startswith('/api/preventiva/status'): self._send(200, preventiva_status_payload())
        elif self.path.startswith('/api/preventiva/history'): self._send(200, preventiva_history_payload())
        elif self.path.startswith('/api/status'): self._send(200, STATE)
        elif self.path.startswith('/api/logs'):
            which='scheduler'
            if '?' in self.path:
                for part in self.path.split('?',1)[1].split('&'):
                    if part.startswith('file='): which=part.split('=',1)[1]
            path = SCHED_LOG if which=='scheduler' else (MAIN_LOG if which=='main' else (PREVENTIVA_LOG if which=='preventiva' else (COB_TERCEIRA_LOG if which=='cob_terceira' else SALES_LOG)))
            self._send(200, '\n'.join(tail_file(path, 320)), 'text/plain; charset=utf-8')
        elif self.path.startswith('/health'): self._send(200, {'ok': True, 'updated_at': iso_now()})
        else: self._send(200, HTML)
    def do_POST(self):
        if self.path.startswith('/run/main'):
            ok,msg=force_run('main'); self._send(200, {'ok':ok,'message':msg})
        elif self.path.startswith('/run/sales'):
            ok,msg=force_run('sales'); self._send(200, {'ok':ok,'message':msg})
        elif self.path.startswith('/run/preventiva'):
            ok,msg=force_run('preventiva'); self._send(200, {'ok':ok,'message':msg})
        elif self.path.startswith('/run/cob_terceira'):
            ok,msg=force_run('cob_terceira'); self._send(200, {'ok':ok,'message':msg})
        elif self.path.startswith('/telegram/test'):
            ok,resp=telegram_send('✅ Teste Telegram COB+VENDAS OK\n'+br_now().strftime('%d/%m/%Y %H:%M:%S'), alert_type='teste', base_dir=BASE_DIR)
            self._send(200, {'ok':ok,'message':('Teste Telegram: '+str(resp)) if ok else str(resp)})
        elif self.path.startswith('/telegram/summary'):
            ok,resp=force_summary_now(); self._send(200, {'ok':ok,'message':resp})
        elif self.path.startswith('/telegram/cobranca-diaria'):
            ok,resp=force_daily_collection_now(); self._send(200, {'ok':ok,'message':resp})
        elif self.path.startswith('/whatsapp/test') or self.path.startswith('/whatsapp/summary'):
            self._send(503, {'ok':False,'message':'WhatsApp Master temporariamente em standby. Canal ativo: Telegram.'})
        else: self._send(404, {'ok':False,'message':'not found'})
    def log_message(self, fmt, *args): return

def start_http_panel():
    port=int(os.getenv('PORT','3000'))
    server=ThreadingHTTPServer(('0.0.0.0', port), Handler)
    log(f'🌐 Painel monitor iniciado na porta {port}')
    server.serve_forever()

STATE['started_at']=iso_now(); STATE['scheduler']='running'; _save_status()
threading.Thread(target=start_http_panel, daemon=True).start()
log('Scheduler Railway ativo | TZ=America/Sao_Paulo')
log(f'VERSAO V10.99: Telegram cobrança diária + guarda de atualização | canal={NOTIFICATION_CHANNEL} | manual_only={COB_TERCEIRA_MANUAL_ONLY}')
log(f'Cobrança: janelas {sorted(COBRANCA_HOURS)} com intervalo mínimo {COBRANCA_MIN_GAP_MIN} min | Listas pesadas: {DAILY_LISTS_HOUR:02d}:00 1x/dia')

while True:
    _sales_proc, sales_finished = finish_if_done('vendas_unificadas', _sales_proc)
    _cobranca_proc, cobranca_finished = finish_if_done('dashboard_completo_cobranca', _cobranca_proc)
    _preventiva_proc, preventiva_finished = finish_if_done('whatsapp_master_preventiva', _preventiva_proc)
    _cob_terceira_proc, cob_terceira_finished = finish_if_done('cobranca_terceira', _cob_terceira_proc)
    if cobranca_finished: _force_sales_after_main = True

    now = br_now(); maybe_send_daily_summary(now); maybe_send_daily_collection_report(now); maybe_send_general_message_alerts(now); maybe_send_meta_diaria_alerts(now); maybe_send_meta_mercantil_100_alerts(now); maybe_send_audit_master_alerts(now)
    STATE['next_daily_lists_label'] = fmt_delta(next_daily_lists_time(now))
    STATE['next_sales_label'] = fmt_delta(next_sales_time(now))
    STATE['next_cobranca_label'] = fmt_delta(next_cobranca_time(now))
    STATE['next_cob_terceira_label'] = fmt_delta(next_cob_terceira_time(now))
    _save_status()

    sales_running = is_running(_sales_proc); cobranca_running = is_running(_cobranca_proc); cob_terceira_running = is_running(_cob_terceira_proc)
    skey = sales_slot_key(now); ckey = cobranca_slot_key(now)
    gap_ok = (_last_cobranca_end is None) or ((now - _last_cobranca_end).total_seconds() >= COBRANCA_MIN_GAP_MIN*60)
    cobranca_ok = ((now.hour in COBRANCA_HOURS and 0 <= now.minute <= COBRANCA_MINUTE_MAX) or is_last_day_23_window(now)) and gap_ok

    if (not COB_TERCEIRA_MANUAL_ONLY) and cob_terceira_due(now) and not sales_running and not cobranca_running and not cob_terceira_running:
        STATE['last_cob_terceira_attempt_at'] = iso_now()
        _save_status()
        _cob_terceira_proc = start_job('cobranca_terceira_prioridade_diaria', COB_TERCEIRA_CMD); cob_terceira_running=True
    elif _force_main_boot and not sales_running and not cobranca_running and not cob_terceira_running:
        _force_main_boot=False; _last_cobranca_slot=ckey
        
        # V31: permite forçar clientes sem movimento + aniversariantes no primeiro boot/deploy.
        # Use FORCE_DAILY_LISTS_ON_BOOT=1 somente no primeiro deploy; depois remova/volte para 0 para manter a regra das 07h.
        _daily = daily_lists_due(now) or FORCE_DAILY_LISTS_ON_BOOT
        if _daily:
            STATE['last_daily_lists_date'] = now.strftime('%Y-%m-%d')
        _cobranca_proc=start_job('dashboard_completo_cobranca_boot_publica_html' + ('_com_listas_pesadas' if _daily else ''), COBRANCA_CMD, main_job_env(_daily)); cobranca_running=True
    elif cobranca_ok and not sales_running and not cobranca_running and not cob_terceira_running and _last_cobranca_slot != ckey:
        _last_cobranca_slot=ckey
        
        _daily = daily_lists_due(now)
        if _daily:
            STATE['last_daily_lists_date'] = now.strftime('%Y-%m-%d')
        _cobranca_proc=start_job('dashboard_completo_cobranca_prioridade' + ('_com_listas_07h' if _daily else ''), COBRANCA_CMD, main_job_env(_daily)); cobranca_running=True
    elif _force_sales_after_main and not sales_running and not cobranca_running and not cob_terceira_running:
        _force_sales_after_main=False; _last_sales_slot=skey
        _sales_proc=start_job('vendas_unificadas_pos_main', SALES_CMD); sales_running=True
    elif not sales_running and not cobranca_running and not cob_terceira_running and _last_sales_slot != skey:
        _last_sales_slot=skey
        _sales_proc=start_job('vendas_unificadas', SALES_CMD); sales_running=True

    log(f'tick | cob_terceira={cob_terceira_running} | sales={sales_running} | cobranca={cobranca_running} | sales_slot={_last_sales_slot} | cobranca_slot={_last_cobranca_slot} | force_sales_after_main={_force_sales_after_main}')
    time.sleep(TICK_SECONDS)

# MDL_V99_RESUMO_LOGS_REMOTE_AVISOS

# MDL_V42_MONITOR_LOGS_FIX: painel de logs não recria/zera área enquanto usuário lê.

# MDL_V43_V103_CRED_FREEZE_RESUMO

# V10.88_SCHEDULER_COB_EXTERNA

# V10.88_COB_MANUAL_ONLY_HOMOLOGACAO

# V10.91_TELEGRAM_PRINCIPAL_WHATSAPP_STANDBY

# V10.92_TELEGRAM_TESTE_EXIBE_DESTINATARIOS

# V10.94_COB_EXTERNA_PRODUCAO

# V10.95_DECISAO_MASTER_COB

# V10.96_COB_DECISAO_EM_LOTE

# V10.99_TELEGRAM_COBRANCA_DIARIA_UPDATE_GUARD
