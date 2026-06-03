# VERSAO: TELEGRAM_MONITOR_MDL_V3_RESUMO_VENDAS_RECEBIMENTOS_FAIXA
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


def _float(v, default=0.0):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v or "").strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return default
        s = s.replace("R$", "").replace("%", "").strip()
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return default


def _read_json_file(path, default):
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _read_text_file(path, default=""):
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
    except Exception:
        pass
    return default


def _read_url_text(url, default="", timeout=12):
    try:
        sep = "&" if "?" in url else "?"
        req_url = url + sep + "_=" + str(int(time.time()))
        with urllib.request.urlopen(req_url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return default


def _read_url_json(url, default, timeout=12):
    raw = _read_url_text(url, "", timeout=timeout).strip()
    if not raw:
        return default
    try:
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
            return []
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
        if "/" in s[:10]:
            try:
                return datetime.strptime(s[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
            except Exception:
                return ""
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


def _find_value_by_key(row, patterns):
    if not isinstance(row, dict):
        return 0.0
    for k, v in row.items():
        nk = re.sub(r"[^a-z0-9]+", "", str(k).lower())
        if all(p in nk for p in patterns):
            return _float(v, 0.0)
    return 0.0


def _is_total_row(row):
    if not isinstance(row, dict):
        return False
    if row.get("_is_total") is True:
        return True
    for key in ("Filial", "Vendedor", "Subgrupo", "Nome", "col_0"):
        if str(row.get(key, "")).strip().lower() == "total":
            return True
    first_val = next((str(v).strip().lower() for k, v in row.items() if not str(k).startswith("_")), "")
    return first_val == "total"


def _total_row_from_meta(meta_obj):
    linhas = (meta_obj or {}).get("linhas") or []
    if not isinstance(linhas, list) or not linhas:
        return {}
    for r in linhas:
        if _is_total_row(r):
            return r
    return linhas[-1] if isinstance(linhas[-1], dict) else {}


def _derive_sales_from_metas(base_dir):
    metas = load_json_local_or_remote(base_dir, "metas_vendas_mes_atual.json", "metas_vendas_mes_atual.json", {})
    metas_map = (metas or {}).get("metas", {}) if isinstance(metas, dict) else {}

    def meta_total(chave):
        row = _total_row_from_meta(metas_map.get(chave, {}))
        return {
            "meta_total": _find_value_by_key(row, ["meta", "total", "float"]),
            "real_total": _find_value_by_key(row, ["realizado", "total", "float"]),
            "ating_total": _find_value_by_key(row, ["atingido", "total", "float"]),
            "meta_periodo": _find_value_by_key(row, ["meta", "periodo", "float"]),
            "real_periodo": _find_value_by_key(row, ["realizado", "periodo", "float"]),
            "projetado": _find_value_by_key(row, ["projetado", "float"]),
        }

    venda = meta_total("venda_filial_meta")
    serv = meta_total("servico_filial_ouro_fob")
    cam = meta_total("venda_filial_subgrupo_20k")
    out = {
        "venda_realizado_total": venda["real_total"],
        "venda_atingido_total": venda["ating_total"],
        "venda_meta_total": venda["meta_total"],
        "venda_meta_periodo": venda["meta_periodo"],
        "venda_projetado": venda["projetado"],
        "servico_realizado_total": serv["real_total"],
        "servico_atingido_total": serv["ating_total"],
        "servico_meta_total": serv["meta_total"],
        "servico_meta_periodo": serv["meta_periodo"],
        "servico_projetado": serv["projetado"],
        "caminhao_realizado_total": cam["real_total"],
        "caminhao_atingido_total": cam["ating_total"],
        "caminhao_meta_total": cam["meta_total"],
        "caminhao_meta_periodo": cam["meta_periodo"],
        "caminhao_projetado": cam["projetado"],
    }

    # Venda diária oficial pode estar anexada com nomes diferentes; procura recursivamente.
    def walk_find(obj, names):
        if isinstance(obj, dict):
            for k, v in obj.items():
                nk = str(k).lower()
                if any(n in nk for n in names):
                    val = _float(v, None)
                    if val is not None:
                        return val
                found = walk_find(v, names)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for it in obj:
                found = walk_find(it, names)
                if found is not None:
                    return found
        return None

    daily = walk_find(metas, ["venda_diaria_total", "venda_diaria", "total_diario", "total_venda_diaria"])
    if daily is not None:
        out["venda_diaria_total"] = daily
    return out


def _derive_margin_from_json(base_dir):
    marg = load_json_local_or_remote(base_dir, "margens_brutas_mes_atual.json", "margens_brutas_mes_atual.json", {})
    emp = (marg or {}).get("empresa", {}) if isinstance(marg, dict) else {}
    if not isinstance(emp, dict):
        emp = {}
    return {
        "margem_bruta_pct": _float(emp.get("margem_bruta_pct"), 0.0),
        "markup_realizado": _float(emp.get("markup_realizado"), 0.0),
        "custo_total": _float(emp.get("custo_total"), 0.0),
        "valor_total": _float(emp.get("valor_total"), 0.0),
        "margem_bruta_valor": _float(emp.get("margem_bruta_valor"), 0.0),
    }


def _merge_sales_data(base_dir, sales_emp):
    sales_emp = dict(sales_emp or {})
    metas_emp = _derive_sales_from_metas(base_dir)

    # Sempre prioriza metas atuais quando vierem com valor, porque são a fonte do dashboard atual.
    for k, v in metas_emp.items():
        if _float(v, 0.0) != 0.0 or _float(sales_emp.get(k), 0.0) == 0.0:
            sales_emp[k] = v

    margin = _derive_margin_from_json(base_dir)
    if margin.get("margem_bruta_pct") or not sales_emp.get("margem_bruta_pct"):
        sales_emp["margem_bruta_pct"] = margin.get("margem_bruta_pct", 0.0)
    if margin.get("markup_realizado"):
        sales_emp["markup_realizado"] = margin.get("markup_realizado", 0.0)
    elif margin.get("custo_total"):
        base = _float(sales_emp.get("venda_realizado_total")) + _float(sales_emp.get("servico_realizado_total"))
        sales_emp["markup_realizado"] = base / margin["custo_total"] if margin["custo_total"] else 0.0
    sales_emp["custo_total"] = margin.get("custo_total", sales_emp.get("custo_total", 0.0))
    return sales_emp


def _extract_js_json_from_html(html, var_name):
    if not html:
        return None
    marker = f"const {var_name}="
    idx = html.find(marker)
    if idx < 0:
        marker = f"var {var_name}="
        idx = html.find(marker)
    if idx < 0:
        return None
    start = idx + len(marker)
    snippet = html[start:]
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(snippet.lstrip())
        return obj
    except Exception:
        return None


def _load_recebimentos_from_dashboard_html(base_dir):
    local_html = _read_text_file(os.path.join(base_dir, "dashboard_vendedores.html"), "")
    remote_html = "" if local_html else _read_url_text(f"{PUBLIC_BASE}/dashboard_vendedores.html", "", timeout=18)
    html = local_html or remote_html
    data = _extract_js_json_from_html(html, "RECEBIMENTOS")
    return data if isinstance(data, dict) else {}


def _recebimentos_dia_por_faixa(base_dir, date_str):
    recebimentos = _load_recebimentos_from_dashboard_html(base_dir)
    out = {
        "grave": {"qtd": 0, "valor": 0.0},
        "alerta": {"qtd": 0, "valor": 0.0},
        "atencao": {"qtd": 0, "valor": 0.0},
    }
    seen = set()
    for _ent_key, grupo in recebimentos.items():
        if not isinstance(grupo, dict):
            continue
        for fx in out.keys():
            arr = grupo.get(fx) or []
            if not isinstance(arr, list):
                continue
            for r in arr:
                if not isinstance(r, dict):
                    continue
                pag = _date_from_server_time(r.get("pagamento") or r.get("data_pagamento") or r.get("pagto"))
                if pag != date_str:
                    continue
                uniq = "|".join([
                    fx,
                    str(r.get("cliente") or r.get("nome") or "")[:80],
                    str(r.get("titulo") or ""),
                    str(r.get("parcela") or ""),
                    str(r.get("pagamento") or ""),
                    str(r.get("pago") or ""),
                ])
                if uniq in seen:
                    continue
                seen.add(uniq)
                out[fx]["qtd"] += 1
                out[fx]["valor"] += _float(r.get("pago"), 0.0)
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
    sales_emp = _merge_sales_data(base_dir, sales_emp)
    receb_dia = _recebimentos_dia_por_faixa(base_dir, date_str)

    logs = _load_cobrancas(base_dir)
    logs_day = [x for x in logs if _date_from_server_time(x.get("server_time") or x.get("data") or x.get("created_at")) == date_str]
    counts = {}
    for x in logs_day:
        user = str(x.get("usuario") or x.get("user") or x.get("login") or "Sem usuário").strip() or "Sem usuário"
        counts[user] = counts.get(user, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

    users = _load_users(base_dir)
    active_user_keys = {_norm(u) for u, _qtd in top}
    sem = []
    for u in users:
        keys = {_norm(u.get("login")), _norm(u.get("nome"))}
        if not keys.intersection(active_user_keys):
            sem.append(u)

    msgs = _active_messages(base_dir)
    campaigns = [m for m in msgs if str(m.get("message_kind") or m.get("kind") or "").lower() == "campaign"]
    notices = [m for m in msgs if m not in campaigns]

    merc = _float(sales_emp.get("venda_realizado_total"))
    serv = _float(sales_emp.get("servico_realizado_total"))
    cam = _float(sales_emp.get("caminhao_realizado_total"))
    faturamento = merc + serv
    venda_diaria = _float(sales_emp.get("venda_diaria_total") or sales_emp.get("venda_diaria") or sales_emp.get("venda_diaria_oficial"), 0.0)
    rent = _float(sales_emp.get("margem_bruta_pct"), 0.0)
    markup = _float(sales_emp.get("markup_realizado"), 0.0)

    linhas = []
    linhas.append(f"📊 RESUMO FINAL DO DIA — {date_str}")
    linhas.append("")
    if emp:
        linhas.append("💰 Cobrança / carteira")
        linhas.append(f"• Pendente: {fmt_money(emp.get('pendente'))}")
        linhas.append(f"• Recebido carteira: {fmt_money(emp.get('recebido'))}")
        if any(k in emp for k in ["grave", "alerta", "atencao"]):
            linhas.append(f"• Carteira por faixa: Grave {fmt_money(emp.get('grave'))} | Alerta {fmt_money(emp.get('alerta'))} | Atenção {fmt_money(emp.get('atencao'))}")
        linhas.append("• Recebimentos do dia por faixa:")
        linhas.append(f"  - Grave: {receb_dia['grave']['qtd']} título(s) · {fmt_money(receb_dia['grave']['valor'])}")
        linhas.append(f"  - Alerta: {receb_dia['alerta']['qtd']} título(s) · {fmt_money(receb_dia['alerta']['valor'])}")
        linhas.append(f"  - Atenção: {receb_dia['atencao']['qtd']} título(s) · {fmt_money(receb_dia['atencao']['valor'])}")
        if emp.get("perc_meta") is not None:
            linhas.append(f"• Meta cobrança: {fmt_pct(emp.get('perc_meta'))}")
    else:
        linhas.append("💰 Cobrança / carteira: sem histórico do dia ainda.")

    linhas.append("")
    linhas.append("🧡 Vendas e serviços")
    linhas.append(f"• Mercantil realizado: {fmt_money(merc)} | Atingido: {fmt_pct(sales_emp.get('venda_atingido_total'))}")
    linhas.append(f"• Serviço realizado: {fmt_money(serv)} | Atingido: {fmt_pct(sales_emp.get('servico_atingido_total'))}")
    linhas.append(f"• Caminhão realizado: {fmt_money(cam)} | Atingido: {fmt_pct(sales_emp.get('caminhao_atingido_total'))}")
    linhas.append(f"• Faturamento total: {fmt_money(faturamento)}")
    linhas.append(f"• Venda diária: {fmt_money(venda_diaria)}")
    linhas.append(f"• Rentabilidade total: {fmt_pct(rent)}")
    linhas.append(f"• Markup total: {str(f'{markup:.2f}').replace('.', ',')}")

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
