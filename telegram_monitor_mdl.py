# VERSAO: TELEGRAM_MONITOR_MDL_V1
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BR_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
PUBLIC_BASE = os.getenv("COLABORADOR_PUBLIC_BASE", "https://moveisdolar.com.br/colaborador").rstrip("/")


def now_br():
    return datetime.now(BR_TZ)


def fmt_money(v):
    try:
        n = float(v or 0)
    except Exception:
        n = 0.0
    s = f"R$ {n:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_pct(v):
    try:
        n = float(v or 0)
    except Exception:
        n = 0.0
    return f"{n:.2f}%".replace(".", ",")


def _read_json_file(path, default):
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
    except Exception:
        pass
    return default


def _read_url_json(url, default, timeout=12):
    try:
        with urllib.request.urlopen(url + ("&" if "?" in url else "?") + "_=" + str(int(time.time())), timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore").strip()
        if not raw:
            return default
        data = json.loads(raw)
        if isinstance(data, dict) and data.get("ok") and "data" in data:
            return data.get("data")
        return data
    except Exception:
        return default


def load_json_local_or_remote(base_dir, local_rel, remote_name, default):
    data = _read_json_file(os.path.join(base_dir, local_rel), None)
    if data is not None:
        return data
    return _read_url_json(f"{PUBLIC_BASE}/{remote_name}", default)


def telegram_send(text, parse_mode=None, disable_web_page_preview=True):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurado"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text[:3900],
        "disable_web_page_preview": "true" if disable_web_page_preview else "false",
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        return True, raw
    except Exception as e:
        return False, str(e)


def tail_file(path, lines=45):
    try:
        if not path or not os.path.exists(path):
            return ""
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            while size > 0 and data.count(b"\n") <= lines:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step) + data
        return data.decode("utf-8", errors="ignore").splitlines()[-lines:]
    except Exception as e:
        return [f"Erro lendo log: {e}"]


def _latest_key(dct):
    if not isinstance(dct, dict) or not dct:
        return ""
    return sorted(dct.keys())[-1]


def _date_from_server_time(v):
    s = str(v or "")
    if len(s) >= 10:
        return s[:10]
    return ""


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip()).lower()


def _active_messages(base_dir):
    msgs = _read_url_json(f"{PUBLIC_BASE}/mensagens_api.php", [])
    if not isinstance(msgs, list):
        msgs = []
    hoje = now_br().date()
    active = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        exp = str(m.get("expires_at") or "").strip()
        expired = False
        if exp:
            try:
                # aceita YYYY-MM-DD ou DD/MM/YYYY
                if "/" in exp:
                    d = datetime.strptime(exp[:10], "%d/%m/%Y").date()
                else:
                    d = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                expired = d < hoje
            except Exception:
                expired = False
        if not expired:
            active.append(m)
    return active


def _load_cobrancas(base_dir):
    # tenta arquivo público direto e depois API
    data = load_json_local_or_remote(base_dir, "cobrancas_log.json", "cobrancas_log.json", None)
    if data is None:
        data = _read_url_json(f"{PUBLIC_BASE}/cobrancas_api.php", [])
    return data if isinstance(data, list) else []


def _load_users(base_dir):
    data = load_json_local_or_remote(base_dir, "credenciais_dashboard.json", "credenciais_dashboard.json", {})
    users = (data or {}).get("users", {}) if isinstance(data, dict) else {}
    out = []
    if isinstance(users, dict):
        for login, u in users.items():
            if not isinstance(u, dict):
                continue
            if u.get("is_viewer") or str(login).lower() in {"painel", "master"}:
                continue
            out.append({
                "login": str(login),
                "nome": str(u.get("nome") or login),
                "filial": str(u.get("filial") or ""),
                "tipo": "Crediarista" if u.get("is_crediarista") else ("Terceiro" if u.get("is_terceiro") else ("Gerente" if u.get("is_gerente") else "Vendedor")),
            })
    return out


def build_daily_summary(base_dir, date_str=None):
    date_str = date_str or now_br().strftime("%Y-%m-%d")
    hist = load_json_local_or_remote(base_dir, os.path.join("cache_historico", "historico_dashboard.json"), "historico_dashboard.json", {"dates": {}, "sales_dates": {}})
    dates = hist.get("dates", {}) if isinstance(hist, dict) else {}
    sales_dates = hist.get("sales_dates", {}) if isinstance(hist, dict) else {}
    day_key = date_str if date_str in dates else _latest_key(dates)
    sales_key = date_str if date_str in sales_dates else _latest_key(sales_dates)

    emp = (dates.get(day_key, {}) or {}).get("empresa", {}) if day_key else {}
    sales_emp = (sales_dates.get(sales_key, {}) or {}).get("empresa", {}) if sales_key else {}

    logs = _load_cobrancas(base_dir)
    logs_day = [x for x in logs if _date_from_server_time(x.get("server_time") or x.get("data") or x.get("created_at")) == date_str]
    counts = {}
    for x in logs_day:
        user = str(x.get("usuario") or x.get("user") or x.get("login") or "Sem usuário").strip() or "Sem usuário")
        counts[user] = counts.get(user, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    users = _load_users(base_dir)
    active_user_keys = set()
    for u, _qtd in top:
        active_user_keys.add(_norm(u))
    sem = []
    for u in users:
        keys = {_norm(u.get("login")), _norm(u.get("nome"))}
        if not keys.intersection(active_user_keys):
            sem.append(u)

    msgs = _active_messages(base_dir)
    campaigns = [m for m in msgs if str(m.get("message_kind") or m.get("kind") or "").lower() == "campaign"]
    notices = [m for m in msgs if m not in campaigns]

    linhas = []
    linhas.append(f"📊 RESUMO FINAL DO DIA — {date_str}")
    linhas.append("")
    if emp:
        linhas.append("💰 Cobrança / carteira")
        linhas.append(f"• Pendente: {fmt_money(emp.get('pendente'))}")
        linhas.append(f"• Recebido: {fmt_money(emp.get('recebido'))}")
        if any(k in emp for k in ["grave", "alerta", "atencao"]):
            linhas.append(f"• Grave: {fmt_money(emp.get('grave'))} | Alerta: {fmt_money(emp.get('alerta'))} | Atenção: {fmt_money(emp.get('atencao'))}")
        if emp.get("perc_meta") is not None:
            linhas.append(f"• Meta cobrança: {fmt_pct(emp.get('perc_meta'))}")
    else:
        linhas.append("💰 Cobrança / carteira: sem histórico do dia ainda.")

    linhas.append("")
    if sales_emp:
        linhas.append("🧡 Vendas e serviços")
        linhas.append(f"• Venda realizada: {fmt_money(sales_emp.get('venda_realizado_total'))} | Atingido: {fmt_pct(sales_emp.get('venda_atingido_total'))}")
        linhas.append(f"• Serviço realizado: {fmt_money(sales_emp.get('servico_realizado_total'))} | Atingido: {fmt_pct(sales_emp.get('servico_atingido_total'))}")
        if sales_emp.get("margem_bruta_pct") is not None:
            linhas.append(f"• Rentabilidade: {fmt_pct(sales_emp.get('margem_bruta_pct'))}")
    else:
        linhas.append("🧡 Vendas e serviços: sem histórico do dia ainda.")

    linhas.append("")
    linhas.append(f"📞 Cobranças feitas hoje: {len(logs_day)} registro(s)")
    if top:
        for nome, qtd in top[:12]:
            linhas.append(f"• {nome}: {qtd}")
    else:
        linhas.append("• Nenhuma cobrança registrada hoje.")

    linhas.append("")
    linhas.append(f"🚫 Sem cobrança registrada: {len(sem)} usuário(s)")
    if sem:
        nomes_sem = [f"{u['nome']} ({u['filial']})" for u in sem[:20]]
        linhas.append("• " + "; ".join(nomes_sem))
        if len(sem) > 20:
            linhas.append(f"• +{len(sem)-20} outros")

    linhas.append("")
    linhas.append(f"📣 Avisos ativos: {len(notices)} | Campanhas ativas: {len(campaigns)}")
    for m in (campaigns + notices)[:6]:
        titulo = str(m.get("title") or "Sem título").strip()
        alvo = str(m.get("target_label") or m.get("target_type") or "Todos").strip()
        exp = str(m.get("expires_at") or "").strip()
        prefix = "🚀" if m in campaigns else "🔔"
        linhas.append(f"{prefix} {titulo} — {alvo}" + (f" até {exp}" if exp else ""))

    linhas.append("")
    linhas.append(f"🕒 Gerado em {now_br().strftime('%d/%m/%Y %H:%M:%S')}")
    return "\n".join(linhas)
