def _extract_list_payload(data):
    """Aceita listas vindas em vários formatos de API/JSON.

    O FTP/API pode devolver lista direta, {ok:true,data:[...]},
    {ok:true,logs:[...]}, {ok:true,mensagens:[...]}, {result:[...]},
    ou objetos aninhados com lista dentro.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        preferred = (
            "data", "logs", "items", "clientes", "registros", "rows",
            "mensagens", "messages", "avisos", "campanhas", "result", "results", "payload"
        )
        for key in preferred:
            val = data.get(key)
            if isinstance(val, list):
                return val
            if isinstance(val, dict):
                nested = _extract_list_payload(val)
                if nested:
                    return nested
        listas = []
        for val in data.values():
            if isinstance(val, list):
                listas.append(val)
            elif isinstance(val, dict):
                nested = _extract_list_payload(val)
                if nested:
                    listas.append(nested)
        if listas:
            listas.sort(key=len, reverse=True)
            return listas[0]
    return []


# VERSAO: TELEGRAM_MONITOR_MDL_V28_RESUMO_NDJSON_FIX
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



def _read_json_file_any(path, default):
    """Lê JSON local aceitando lista/dict e nunca estoura o resumo."""
    try:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                raw = f.read().strip()
            if not raw:
                return default
            return json.loads(raw)
    except Exception:
        return default
    return default


def _read_url_ndjson(url, default=None, timeout=12):
    """Lê arquivo NDJSON remoto, 1 JSON por linha, usado pelos backups append.

    Corrige o erro do resumo manual: name '_read_url_ndjson' is not defined.
    """
    out = [] if default is None else default
    try:
        raw = _read_url_text(url, "", timeout=timeout)
        if not raw:
            return [] if default is None else default
        rows = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    rows.append(item)
                elif isinstance(item, list):
                    rows.extend([x for x in item if isinstance(x, dict)])
            except Exception:
                continue
        return rows
    except Exception:
        return [] if default is None else default

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
        if isinstance(data, dict):
            extracted = _extract_list_payload(data)
            if extracted:
                return extracted
            if data.get("ok") and "data" in data:
                return data.get("data")
        return data
    except Exception:
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


def _load_telegram_global_config(base_dir=None):
    """Carrega config_meta.json/global, incluindo contatos e templates Telegram."""
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, 'cache_historico', 'config_meta.json'),
        os.path.join(base_dir, 'config_meta.json'),
    ]
    cfg = None
    for p in candidates:
        cfg = _read_json_file(p, None)
        if isinstance(cfg, dict):
            break
    if not isinstance(cfg, dict):
        cfg = _read_url_json(f"{PUBLIC_BASE}/config_meta.json", {}, timeout=10)
    if not isinstance(cfg, dict):
        return {}
    return (cfg.get('global') if isinstance(cfg.get('global'), dict) else cfg) or {}


def _load_telegram_contacts_from_config(base_dir=None):
    """Carrega contatos configurados em config_meta.json/global.telegram_contacts.
    Fallback: TELEGRAM_CHAT_ID do ambiente.
    """
    glob = _load_telegram_global_config(base_dir)
    contacts = glob.get('telegram_contacts') or []
    out = []
    if isinstance(contacts, list):
        for c in contacts:
            if not isinstance(c, dict):
                continue
            chat_id = str(c.get('chat_id') or '').strip()
            if not chat_id:
                continue
            def b(k, default=False):
                v = c.get(k, default)
                return v is True or str(v).lower() in {'1','true','sim','yes','on'}
            out.append({
                'nome': str(c.get('nome') or chat_id).strip(),
                'chat_id': chat_id,
                'ativo': b('ativo', True),
                'erros': b('erros', True),
                'meta_diaria': b('meta_diaria', True),
                'meta_mensal': b('meta_mensal', True),
                'avisos': b('avisos', True),
                'resumo': b('resumo', True),
            })
    if not out:
        env_chat = os.getenv('TELEGRAM_CHAT_ID', '').strip()
        if env_chat:
            out.append({'nome':'TELEGRAM_CHAT_ID','chat_id':env_chat,'ativo':True,'erros':True,'meta_diaria':True,'meta_mensal':True,'avisos':True,'resumo':True})
    return out


def _telegram_contacts_for_alert(alert_type='geral', base_dir=None):
    alert_type = str(alert_type or 'geral').lower().strip()
    key_map = {
        'erro': 'erros', 'erros': 'erros', 'sistema': 'erros',
        'meta_diaria': 'meta_diaria', 'diaria': 'meta_diaria',
        'meta_mensal': 'meta_mensal', 'meta100': 'meta_mensal', 'mercantil100': 'meta_mensal',
        'aviso': 'avisos', 'avisos': 'avisos', 'campanha': 'avisos', 'geral': 'avisos',
        'resumo': 'resumo', 'daily_summary': 'resumo',
        'teste': None, 'test': None,
    }
    flag = key_map.get(alert_type, None)
    contacts = [c for c in _load_telegram_contacts_from_config(base_dir) if c.get('ativo')]
    if flag is None:
        return contacts
    return [c for c in contacts if c.get(flag)]


def _sanitize_meta_alert_text(text):
    """Blindagem final dos alertas de META no Telegram.

    Para META DIÁRIA / META MENSAL, o grupo pode receber somente:
    - parabéns / título
    - responsável/filial
    - tipo / escopo / data / competência
    - percentual atingido

    Nunca enviar valores em reais nem comparativo Realizado / Meta.
    """
    raw = str(text or '')
    clean_lines = []
    # Não bloquear a palavra "meta" de forma genérica, pois isso remove
    # títulos como "META DIÁRIA BATIDA" e rodapés como "Controle de Meta".
    # A blindagem deve remover somente valores financeiros/comparativos.
    bloqueios = (
        'r$',
        'realizado / meta',
        'realizado/meta',
        'realizado:',
        'valor:',
        'valor ',
    )
    for line in raw.splitlines():
        low = line.lower().strip()
        if any(b in low for b in bloqueios) and '%' not in line:
            continue
        if 'r$' in low:
            continue
        # remove linhas que são claramente dois valores financeiros sem R$, ex.: 2.401,00 / 1.000,00
        if re.search(r'\d{1,3}(?:\.\d{3})*,\d{2}\s*/\s*\d{1,3}(?:\.\d{3})*,\d{2}', line):
            continue
        clean_lines.append(line)
    out = '\n'.join(clean_lines)
    # remove qualquer resquício de valor monetário com ou sem R$ dentro do texto
    out = re.sub(r'R\$\s*[-+]?\d{1,3}(?:\.\d{3})*,\d{2}', '', out, flags=re.IGNORECASE)
    out = re.sub(r'R\$\s*[-+]?\d+(?:[\.,]\d{2})?', '', out, flags=re.IGNORECASE)
    # remove padrões comparativos que eventualmente sobraram
    out = re.sub(r'Realizado\s*/\s*Meta\s*:\s*[^\n]+', '', out, flags=re.IGNORECASE)
    out = re.sub(r'[ \t]+\n', '\n', out)
    out = re.sub(r'\n{3,}', '\n\n', out).strip()
    return out


def _telegram_send_one(text, chat_id, parse_mode=None, disable_web_page_preview=True):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token or not str(chat_id or '').strip():
        return False, "TELEGRAM_BOT_TOKEN ou chat_id não configurado"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": str(chat_id).strip(),
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


def telegram_send(text, parse_mode=None, disable_web_page_preview=True, chat_id=None, alert_type='geral', base_dir=None):
    """Envia Telegram para um chat específico ou para os contatos configurados por tipo de alerta."""
    atype = str(alert_type or '').lower().strip()
    if atype in {'meta_diaria', 'meta_mensal', 'meta100', 'mercantil100'}:
        text = _sanitize_meta_alert_text(text)
    if chat_id:
        return _telegram_send_one(text, chat_id, parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
    contacts = _telegram_contacts_for_alert(alert_type, base_dir=base_dir)
    if not contacts:
        return False, f"Nenhum contato Telegram ativo para alerta {alert_type}"
    oks = []
    resps = []
    for c in contacts:
        ok, resp = _telegram_send_one(text, c.get('chat_id'), parse_mode=parse_mode, disable_web_page_preview=disable_web_page_preview)
        oks.append(ok)
        resps.append(f"{c.get('nome') or c.get('chat_id')}: {'OK' if ok else resp}")
    return any(oks), " | ".join(resps)

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


def _dedup_dicts_by_id(items):
    out = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get('id') or item.get('message_id') or item.get('server_time') or '')
        if not key:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)[:300]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _active_messages(base_dir):
    """Carrega avisos/campanhas ativos do FTP/API de forma robusta."""
    candidatos = []
    candidatos += _extract_list_payload(_read_json_file(os.path.join(base_dir, "mensagens_log.json"), []))
    candidatos += _extract_list_payload(_read_url_json(f"{PUBLIC_BASE}/mensagens_api.php", [], timeout=12))
    candidatos += _extract_list_payload(_read_url_json(f"{PUBLIC_BASE}/mensagens_log.json", [], timeout=12))
    msgs = _dedup_dicts_by_id(candidatos)

    hoje = now_br().date()
    active = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        if m.get('deleted') is True or str(m.get('status') or '').lower() in {'deleted','removido','removida','cancelado','cancelada'}:
            continue
        exp = str(m.get("expires_at") or m.get("valid_until") or m.get("ate") or m.get("data_final") or m.get("validade") or m.get("fim") or m.get("expires") or "").strip()
        expired = False
        if exp:
            try:
                if "/" in exp[:10]:
                    d = datetime.strptime(exp[:10], "%d/%m/%Y").date()
                else:
                    d = datetime.strptime(exp[:10], "%Y-%m-%d").date()
                expired = d < hoje
            except Exception:
                expired = False
        if not expired:
            active.append(m)
    return active


def _log_dedup_key(x):
    if not isinstance(x, dict):
        return ""
    for k in ("id", "log_id", "uuid"):
        if x.get(k):
            return f"id:{x.get(k)}"
    parts = [
        x.get("titulo") or x.get("tipo") or "",
        x.get("cliente") or x.get("nome") or "",
        x.get("parcela") or "",
        x.get("telefone") or "",
        x.get("server_time") or x.get("criado_em") or x.get("created_at") or x.get("data") or "",
        x.get("usuario") or x.get("destino_nome") or x.get("login") or "",
    ]
    return "|".join(str(p) for p in parts)


def _merge_log_sources(*sources):
    out = []
    seen = set()
    for src in sources:
        for x in _extract_list_payload(src):
            if not isinstance(x, dict):
                continue
            key = _log_dedup_key(x)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            out.append(x)
    return out


def _load_cobrancas(base_dir):
    """Carrega logs do FTP/API público e local, mesclando sem duplicar.

    V10.3: inclui backups/append e cache busting, além de aceitar wrappers diversos.
    Isso corrige resumo final zerado quando o Railway não enxergava a lista principal.
    """
    local = _read_json_file(os.path.join(base_dir, "cobrancas_log.json"), [])
    remote_file = _read_url_json(f"{PUBLIC_BASE}/cobrancas_log.json", [], timeout=20)
    remote_api = _read_url_json(f"{PUBLIC_BASE}/cobrancas_api.php", [], timeout=20)
    remote_api2 = _read_url_json(f"{PUBLIC_BASE}/cobrancas_api.php?full=1", [], timeout=20)
    hoje = now_br().strftime("%Y-%m-%d")
    ontem = (now_br() - timedelta(days=1)).strftime("%Y-%m-%d")
    backup_hoje = _read_url_json(f"{PUBLIC_BASE}/backups_cobrancas/cobrancas_log_{hoje}_latest.json", [], timeout=12)
    backup_ontem = _read_url_json(f"{PUBLIC_BASE}/backups_cobrancas/cobrancas_log_{ontem}_latest.json", [], timeout=12)
    ndjson_hoje = _read_url_ndjson(f"{PUBLIC_BASE}/backups_cobrancas/cobrancas_log_append_{hoje}.ndjson", timeout=12)
    ndjson_ontem = _read_url_ndjson(f"{PUBLIC_BASE}/backups_cobrancas/cobrancas_log_append_{ontem}.ndjson", timeout=12)
    # Alguns deploys guardam cópia em /app/monitor_logs ou cache_historico.
    local2 = _read_json_file_any(os.path.join(base_dir, "monitor_logs", "cobrancas_log.json"), [])
    local3 = _read_json_file_any(os.path.join(base_dir, "cache_historico", "cobrancas_log.json"), [])
    return _merge_log_sources(remote_api, remote_api2, remote_file, backup_hoje, backup_ontem, ndjson_hoje, ndjson_ontem, local, local2, local3)


def _load_users(base_dir):
    data = load_json_local_or_remote(base_dir, "credenciais_dashboard.json", "credenciais_dashboard.json", {})
    users = (data or {}).get("users", {}) if isinstance(data, dict) else {}
    out = []
    if isinstance(users, dict):
        for login, u in users.items():
            if not isinstance(u, dict):
                continue
            login_s = str(login or u.get("login") or "").strip()
            if u.get("is_viewer") or login_s.lower() in {"painel", "master", "diretorcomercial"}:
                continue
            status = str(u.get("status_operacional") or u.get("status") or "ativo").lower().strip()
            if status and status not in {"ativo", "active", "true", "1"}:
                continue
            if u.get("access_disabled") is True:
                continue
            out.append({
                "login": login_s,
                "nome": str(u.get("nome") or login_s),
                "filial": str(u.get("filial") or ""),
                "tipo": "Crediarista" if u.get("is_crediarista") else ("Terceiro" if u.get("is_terceiro") else ("Gerente" if u.get("is_gerente") else "Vendedor")),
                "is_crediarista": bool(u.get("is_crediarista")),
                "is_terceiro": bool(u.get("is_terceiro")),
                "is_gerente": bool(u.get("is_gerente")),
                "participa_cobrancas": bool(u.get("participa_cobrancas", True)),
                "participa_sem_movimento": bool(u.get("participa_sem_movimento", True)),
                "participa_aniversariantes": bool(u.get("participa_aniversariantes", True)),
                "participa_murais": bool(u.get("participa_murais", True)),
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



def _date_only_br_from_any(v):
    s = str(v or "").strip()
    if not s:
        return ""
    if "T" in s or re.search(r"[+-]\d{2}:?\d{2}$", s) or s.endswith("Z"):
        try:
            ss = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ss)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BR_TZ)
            return dt.astimezone(BR_TZ).strftime("%Y-%m-%d")
        except Exception:
            pass
    if "/" in s[:10]:
        try:
            return datetime.strptime(s[:10], "%d/%m/%Y").strftime("%Y-%m-%d")
        except Exception:
            return ""
    if len(s) >= 10 and re.match(r"\d{4}-\d{2}-\d{2}", s[:10]):
        return s[:10]
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")).astimezone(BR_TZ).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _alias_norm(v):
    return _norm(v).replace(" - ", " ")


def _add_alias(aliases, v):
    v = str(v or "").strip()
    if not v:
        return
    aliases.add(_alias_norm(v))
    aliases.add(_alias_norm(v.replace("_", " ")))
    aliases.add(_alias_norm(v.replace("-", " ")))


def _user_aliases(u):
    aliases = set()
    login = str((u or {}).get("login") or "").strip()
    nome = str((u or {}).get("nome") or "").strip()
    filial = str((u or {}).get("filial") or "").strip().upper()
    tipo = str((u or {}).get("tipo") or "").strip()
    for v in [login, nome, filial, tipo]:
        _add_alias(aliases, v)
    if nome and filial:
        _add_alias(aliases, f"{nome}_{filial}")
        _add_alias(aliases, f"{nome} ({filial})")
        _add_alias(aliases, f"{filial} - {nome}")
        _add_alias(aliases, f"{filial} {nome}")
    if login and filial:
        _add_alias(aliases, f"{login}_{filial}")
        _add_alias(aliases, f"{filial} - {login}")
    if (u or {}).get("is_crediarista") and filial:
        # O log às vezes vem como crediaristaf06_01, Crediarista F6 01, ou só F6 - Crediarista.
        _add_alias(aliases, f"Crediarista {filial} 01")
        _add_alias(aliases, f"crediarista{filial.lower()}_01")
    if (u or {}).get("is_terceiro"):
        _add_alias(aliases, "Cobrança10")
        _add_alias(aliases, "cobranca10")
        _add_alias(aliases, "FTER")
    return {a for a in aliases if a}


def _log_aliases(x):
    aliases = set()
    if not isinstance(x, dict):
        return aliases
    for k in ["usuario", "user", "login", "destino_nome", "responsavel", "vendedor", "filial", "owner_key"]:
        _add_alias(aliases, x.get(k))
    destino = str(x.get("destino_nome") or "").strip()
    usuario = str(x.get("usuario") or x.get("login") or "").strip()
    login = str(x.get("login") or "").strip()
    filial = str(x.get("filial") or "").strip().upper()
    for val in [destino, usuario, login]:
        if val and filial:
            _add_alias(aliases, f"{val}_{filial}")
            _add_alias(aliases, f"{val} ({filial})")
            _add_alias(aliases, f"{filial} - {val}")
            _add_alias(aliases, f"{filial} {val}")
    # Se o usuário veio como "F3 - NOME", também adiciona só o nome.
    for val in [usuario, destino, login]:
        m = re.match(r"^\s*F\d{1,2}\s*[-–]\s*(.+)$", str(val or ""), flags=re.I)
        if m:
            _add_alias(aliases, m.group(1))
            if filial:
                _add_alias(aliases, f"{m.group(1)}_{filial}")
    return {a for a in aliases if a}


def _log_date(x):
    if not isinstance(x, dict):
        return ""
    # V10.3: muitos registros antigos usam server_date/data_envio/data_hora.
    # Se não aceitar esses campos, o resumo diário fica zerado.
    for k in ("server_date", "data_envio", "data_hora", "datahora", "data_log", "enviado_em", "sent_at", "server_time", "criado_em", "created_at", "created", "updated_at", "timestamp", "hora", "data", "date"):
        d = _date_only_br_from_any(x.get(k))
        if d:
            return d
    # fallback: tenta localizar data em qualquer campo textual do registro
    blob = " ".join(str(v) for v in x.values() if isinstance(v, (str, int, float)))
    m = re.search(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", blob)
    if m:
        return _date_only_br_from_any(m.group(1))
    return ""


def _titulo_upper(x):
    return str((x or {}).get("titulo") or (x or {}).get("tipo") or (x or {}).get("tipo_log") or "").strip().upper()


def _log_blob_upper(x):
    if not isinstance(x, dict):
        return ""
    vals = []
    for k in ("titulo", "tipo", "tipo_log", "parcela", "cliente_key", "cobranca_key", "owner_key", "origem", "categoria"):
        vals.append(str(x.get(k) or ""))
    return " | ".join(vals).upper()


def _is_reactivation_log(x):
    blob = _log_blob_upper(x)
    return ("REATIVACAO" in blob) or ("REATIVAÇÃO" in blob) or ("CLIENTE_SEM_MOVIMENTO" in blob) or ("SEM_MOVIMENTO" in blob)


def _is_birthday_log(x):
    blob = _log_blob_upper(x)
    return ("ANIVERSARIO" in blob) or ("ANIVERSÁRIO" in blob) or ("ANIV" in blob)


def _is_real_collection_log(x):
    if not isinstance(x, dict):
        return False
    if _is_reactivation_log(x) or _is_birthday_log(x):
        return False
    t = str(x.get("titulo") or x.get("tipo") or "").strip().upper()
    if t in {"REATIVACAO", "REATIVAÇÃO", "ANIVERSARIO", "ANIVERSÁRIO", "ANIVERSARIO_DIRETOR"}:
        return False
    # V10.3: cobrança real pode vir só com usuario+telefone+cliente_key/titulo/parcela.
    has_owner = bool(x.get("usuario") or x.get("destino_nome") or x.get("login") or x.get("responsavel"))
    has_client = bool(x.get("cliente") or x.get("nome") or x.get("cliente_key") or x.get("cobranca_key"))
    has_contact = bool(x.get("telefone") or x.get("phone") or x.get("whatsapp") or x.get("acao") == "whatsapp")
    has_title = bool(x.get("titulo") or x.get("parcela") or x.get("pendente") is not None or x.get("vencimento"))
    return bool(has_owner and has_client and (has_contact or has_title))


def _log_owner_label(x):
    if not isinstance(x, dict):
        return "Sem usuário"
    filial = str(x.get("filial") or "").strip().upper()
    nome = str(x.get("destino_nome") or x.get("usuario") or x.get("user") or x.get("login") or x.get("responsavel") or "").strip()
    if not nome:
        nome = "Sem usuário"
    # Normaliza "F3 - Nome" sem perder a filial.
    m = re.match(r"^\s*(F\d{1,2})\s*[-–]\s*(.+)$", nome, flags=re.I)
    if m:
        filial = filial or m.group(1).upper()
        nome = m.group(2).strip()
    if filial and filial not in nome.upper() and nome.lower() not in {"sem usuário", "sem usuario"}:
        return f"{nome} ({filial})"
    return nome


def _active_keys_for_logs(logs):
    keys = set()
    counts = {}
    for x in logs:
        label = _log_owner_label(x)
        counts[label] = counts.get(label, 0) + 1
        keys.update(_log_aliases(x))
    return keys, sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def _users_missing_action(users, active_keys, flag_name):
    arr = []
    for u in users:
        if not u.get(flag_name, True):
            continue
        if not u.get("participa_murais", True):
            continue
        if _user_aliases(u).intersection(active_keys):
            continue
        arr.append(u)
    return arr


def _format_user_list(users, limit=22):
    if not users:
        return "• Todos fizeram ✅"
    nomes = []
    for u in users[:limit]:
        nome = _first_name_v97(u.get('nome') or u.get('login') or '')
        if nome:
            nomes.append(nome)
    txt = "• " + "; ".join(nomes)
    if len(users) > limit:
        txt += f"\n• +{len(users)-limit} outros"
    return txt


# ===== V8.3: funções de watchers/alertas instantâneos restauradas =====
def load_active_general_messages(base_dir):
    """Mensagens/avisos/campanhas com destino Todos, para o Telegram notificar o grupo."""
    msgs = _active_messages(base_dir)
    out = []
    for m in msgs:
        if not isinstance(m, dict):
            continue
        target_type = str(m.get('target_type') or 'all').lower().strip()
        target_id = str(m.get('target_id') or '').upper().strip()
        if target_type == 'all' or target_id in {'ALL', 'TODOS'}:
            out.append(m)
    return out

def build_general_message_alert(m):
    kind = str(m.get('message_kind') or m.get('kind') or 'notice').lower()
    icon = '🚀' if kind == 'campaign' else '🔔'
    tipo = 'Campanha geral' if kind == 'campaign' else 'Aviso geral'
    titulo = str(m.get('title') or 'Sem título').strip()
    corpo = str(m.get('body') or '').strip()
    exp = str(m.get('expires_at') or '').strip()
    linhas = [f'{icon} {tipo} enviado no Dashboard MDL', '', f'Título: {titulo}']
    if exp:
        linhas.append(f'Válido até: {exp}')
    if corpo:
        linhas += ['', corpo[:1500]]
    media = str(m.get('media_url') or '').strip()
    if media:
        linhas += ['', f'Anexo: {media}']
    linhas += ['', f'Horário: {now_br().strftime("%d/%m/%Y %H:%M:%S")}']
    return '\n'.join(linhas)


def _is_gerente_meta_vendedor(nome):
    """True para metas individuais de gerentes (GER/GERF) que não devem gerar Telegram.

    A meta do gerente pode existir no SGI com valor simbólico. Para Telegram,
    gerente deve ser avisado somente quando a FILIAL bater meta, não pela meta
    individual de vendedor.
    """
    txt = str(nome or '').upper()
    return bool(re.search(r'\(\s*GER\s*F?\d*\s*\)', txt) or re.search(r'\bGERF?\d*\b', txt))


def _is_vendedor_operacional_meta(nome):
    """Aceita somente vendedores com tag operacional explícita (F1, F2...)."""
    txt = str(nome or '').upper()
    if _is_gerente_meta_vendedor(txt):
        return False
    return bool(re.search(r'\(\s*F\d+\s*\)', txt))


def _is_linha_meta_vendedor(chave, escopo):
    cs = str(chave or '').lower()
    es = str(escopo or '').lower()
    return ('vendedor' in cs) or ('vendedor' in es)

def _is_meta_venda_mercantil_diaria(chave, bloco):
    """Retorna True somente para metas diárias do tipo Venda/Mercantil.

    Importante: o dashboard pode coletar também metas de Serviço para cards,
    mas Telegram de META DIÁRIA BATIDA deve disparar apenas para Venda.
    """
    spec = (bloco or {}).get('spec') or {}
    tipo = str(spec.get('tipo') or '').strip().lower()
    label = str(spec.get('label') or '').strip().lower()
    chave_s = str(chave or '').strip().lower()

    # Bloqueia qualquer meta de serviço/caminhão por segurança.
    bloqueados = ('servico', 'serviço', 'caminhao', 'caminhão')
    if any(x in chave_s or x in label or x in tipo for x in bloqueados):
        return False

    # Aceita somente tipo Venda ou chaves/labels claramente de venda.
    if tipo == 'venda':
        return True
    if 'venda' in chave_s or 'venda' in label:
        return True
    return False


def _date_to_iso_v97(v):
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""

def _first_name_v97(nome):
    s = str(nome or "").strip()
    if not s:
        return ""
    s = re.sub(r"^\s*F\d+\s*[-–]\s*", "", s, flags=re.I)
    s = re.sub(r"\s*\([^)]+\)\s*$", "", s).strip()
    if s.upper().startswith("GERENTE"):
        return s.title()
    return (s.split()[0] if s.split() else s).title()


def _v101_money_float(v):
    try:
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v or "").strip()
        if not s or s.lower() in {"nan", "none", "null"}:
            return 0.0
        s = s.replace("R$", "").replace("%", "").replace(" ", "")
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return 0.0


def _v101_meta_diaria_validada(row):
    """Valida meta diária pelo cálculo Realizado Período / Meta Período.
    Não aceita Projetado/Realizado Total como base do alerta.
    """
    meta_txt = str(row.get('Meta (R$) Período') or row.get('Meta(R$) Período') or row.get('Meta (R$) Periodo') or row.get('Meta(R$) Periodo') or '').strip()
    real_txt = str(row.get('Realizado (R$) Período') or row.get('Realizado(R$) Período') or row.get('Realizado (R$) Periodo') or row.get('Realizado(R$) Periodo') or '').strip()
    total_txt = str(row.get('Realizado (R$) Total') or row.get('Realizado(R$) Total') or '').strip()
    meta_n = _v101_money_float(meta_txt)
    real_n = _v101_money_float(real_txt)
    total_n = _v101_money_float(total_txt)
    if meta_n <= 0 or real_n <= 0:
        return False, 0.0
    if total_n > 0 and real_n > (total_n + 0.01):
        return False, 0.0
    ating = round((real_n / meta_n) * 100.0, 2)
    # V10.2/V26: blindagem contra coluna desalinhada/projetado lido como realizado período.
    ating_txt = str(row.get('Atingido Período') or row.get('Atingido Periodo') or row.get('Atingido Período_float') or row.get('Atingido Periodo_float') or '').strip()
    ating_sgi = _v101_money_float(ating_txt)
    if ating_sgi > 0 and abs(ating_sgi - ating) > max(2.0, ating * 0.05):
        return False, 0.0
    if ating > 500:
        return False, 0.0
    return ating >= 100.0, ating

def load_meta_diaria_batidas(base_dir):
    """Lê metas_vendas_dia_atual.json e retorna somente Venda/Mercantil com Atingido Período >= 100%.

    Regra Telegram:
    - Meta diária: somente tipo Venda/Mercantil.
    - Serviço não dispara Telegram.
    - A trava de repetição diária fica no scheduler, via telegram_sent_meta_keys.
    """
    data = load_json_local_or_remote(base_dir, 'metas_vendas_dia_atual.json', 'metas_vendas_dia_atual.json', {})
    if not isinstance(data, dict):
        return []
    # V9.7: não dispara meta diária velha após meia-noite/deploy.
    data_iso = _date_to_iso_v97(data.get('data_consulta') or data.get('data') or data.get('gerado_em'))
    today_iso = now_br().strftime('%Y-%m-%d')
    if data_iso and data_iso != today_iso:
        return []
    metas = data.get('metas') or {}
    out = []
    for chave, bloco in metas.items():
        if not isinstance(bloco, dict):
            continue
        if not _is_meta_venda_mercantil_diaria(chave, bloco):
            continue
        spec = bloco.get('spec') or {}
        for row in bloco.get('linhas') or []:
            if not isinstance(row, dict) or row.get('_is_total'):
                continue
            # Reforço: se a linha trouxer _meta_tipo Serviço, não dispara.
            row_tipo = str(row.get('_meta_tipo') or spec.get('tipo') or '').strip().lower()
            if row_tipo and row_tipo != 'venda':
                continue
            ok_meta_dia, ating = _v101_meta_diaria_validada(row)
            if not ok_meta_dia:
                continue
            escopo = str(row.get('_meta_escopo') or spec.get('escopo') or '')
            nome = str(row.get('Vendedor_2') or row.get('Vendedor') or row.get('Filial') or '').strip()
            filial = str(row.get('Filial') or row.get('Vendedor') or '').strip()
            # Se for meta no escopo vendedor, ignora gerentes GER/GERF e aceita
            # somente vendedores operacionais com tag (F1), (F2), etc.
            if _is_linha_meta_vendedor(chave, escopo) and not _is_vendedor_operacional_meta(nome):
                continue
            out.append({
                # V18: chave estável por dia + escopo + responsável.
                # Não inclui percentual, para enviar só 1x quando passou de 100%,
                # mesmo que depois suba de 106% para 112%.
                'key': f"{today_iso}|VENDA_MERCANTIL|{chave}|{nome}|{filial}",
                'nome': nome,
                'filial': filial,
                'escopo': escopo,
                'tipo': 'Venda/Mercantil',
                'atingido': ating,
                'atingido_txt': str(row.get('Atingido Período') or f'{ating:.2f}%'),
                'data_consulta': data.get('data_consulta') or now_br().strftime('%d/%m/%Y'),
            })
    # remove duplicados preservando ordem
    seen=set(); final=[]
    for x in out:
        k=x['key']
        if k in seen: continue
        seen.add(k); final.append(x)
    return final


def _telegram_template(kind, base_dir=None):
    glob = _load_telegram_global_config(base_dir)
    templates = glob.get('telegram_templates') if isinstance(glob.get('telegram_templates'), dict) else {}
    txt = str(templates.get(kind) or '').strip()
    return txt


def _render_template(txt, data):
    out = str(txt or '')
    for k, v in (data or {}).items():
        out = out.replace('{' + str(k) + '}', str(v if v is not None else ''))
    return out


def _force_pretty_meta_template(kind, text):
    """Garante que template antigo salvo no servidor não perca título/rodapé.
    Mantém a regra: só percentual, sem valores em R$.
    """
    out = str(text or '').strip()
    if not out:
        return out
    k = str(kind or '').lower()
    if k == 'meta_diaria':
        title = '🎯🚀 PARABÉNS! META DIÁRIA BATIDA'
        footer1 = '🔥 Excelente resultado no Controle de Meta do Sólidus!'
        footer2 = '💪 MISSÃO DADA! MISSÃO CUMPRIDA!'
    else:
        title = '🏆🚀 PARABÉNS! META MENSAL BATIDA'
        footer1 = '🔥 Excelente resultado no Controle de Meta do Sólidus!'
        footer2 = '💪 Resultado de time forte!'
    # Remove rodapés antigos conhecidos para padronizar.
    lines = []
    for ln in out.splitlines():
        low = ln.lower()
        if 'bora manter esse ritmo' in low:
            continue
        if 'resultado de time forte' in low and k == 'meta_diaria':
            continue
        lines.append(ln)
    out = '\n'.join(lines).strip()
    if 'PARABÉNS' not in out.upper() and 'PARABENS' not in out.upper():
        out = title + '\n\n' + out
    if 'Excelente resultado no Controle de Meta do Sólidus' not in out:
        out = out.rstrip() + '\n\n' + footer1
    if footer2 not in out:
        out = out.rstrip() + '\n' + footer2
    return out

def build_meta_diaria_alert(item, base_dir=None):
    """Mensagem bonita de meta diária, com emojis, editável no dashboard e SEM qualquer valor em R$."""
    nome = item.get('nome') or item.get('filial') or 'Equipe MDL'
    escopo = item.get('escopo') or ''
    data = item.get('data_consulta') or now_br().strftime('%d/%m/%Y')
    atingido = _sanitize_meta_alert_text(str(item.get('atingido_txt') or fmt_pct(item.get('atingido'))).strip())
    tpl = _telegram_template('meta_diaria', base_dir)
    if tpl:
        rendered = _render_template(tpl, {
            'nome': nome, 'filial': item.get('filial') or '', 'escopo': escopo,
            'atingido': atingido, 'tipo': 'Venda mercantil', 'data': data,
            'competencia': now_br().strftime('%Y-%m')
        })
        return _sanitize_meta_alert_text(_force_pretty_meta_template('meta_diaria', rendered))
    linhas = ['🎯🚀 PARABÉNS! META DIÁRIA BATIDA','',f'👏 Destaque: {nome}']
    if atingido:
        linhas.append(f'📈 Meta atingida: {atingido}')
    linhas += ['🛒 Tipo: Venda mercantil',f'📅 Data: {data}','','🔥 Excelente resultado no Controle de Meta do Sólidus!','💪 MISSÃO DADA! MISSÃO CUMPRIDA!']
    return _sanitize_meta_alert_text('\n'.join(linhas))



def _first_existing(row, names):
    if not isinstance(row, dict):
        return ''
    for name in names:
        if name in row and row.get(name) not in (None, ''):
            return row.get(name)
    # fallback por normalização parcial
    wanted = [re.sub(r'[^a-z0-9]+', '', str(n).lower()) for n in names]
    for k, v in row.items():
        nk = re.sub(r'[^a-z0-9]+', '', str(k).lower())
        if any(w and w in nk for w in wanted) and v not in (None, ''):
            return v
    return ''


def load_meta_mercantil_100(base_dir):
    """Lê metas_vendas_mes_atual.json e retorna filiais/vendedores com Atingido Total >= 100% em Venda Mercantil."""
    data = load_json_local_or_remote(base_dir, 'metas_vendas_mes_atual.json', 'metas_vendas_mes_atual.json', {})
    if not isinstance(data, dict):
        return []
    # V9.7: não dispara meta diária velha após meia-noite/deploy.
    data_iso = _date_to_iso_v97(data.get('data_consulta') or data.get('data') or data.get('gerado_em'))
    today_iso = now_br().strftime('%Y-%m-%d')
    if data_iso and data_iso != today_iso:
        return []
    metas = data.get('metas') or {}
    specs = [
        ('venda_filial_meta', 'Filial'),
        ('venda_filial_vendedor_meta', 'Vendedor'),
    ]
    out = []
    mes = str(data.get('mes') or data.get('competencia') or now_br().strftime('%Y-%m'))[:7]
    for chave, tipo in specs:
        bloco = metas.get(chave) or {}
        if not isinstance(bloco, dict):
            continue
        for row in bloco.get('linhas') or []:
            if not isinstance(row, dict) or row.get('_is_total') or _is_total_row(row):
                continue
            ating = _float(row.get('Atingido Total_float', row.get('Atingido Total')), 0.0)
            if ating < 100:
                continue
            nome = str(_first_existing(row, ['Vendedor_2','Vendedor','Nome_2','Nome','Filial']) or '').strip()
            filial = str(_first_existing(row, ['Filial']) or '').strip()
            if not nome:
                continue
            # Para metas individuais de vendedor, não dispara Telegram para gerentes
            # com tag GER/GERF nem para linhas sem tag operacional (F1/F2...).
            # Gerentes continuam recebendo o aviso pela meta da FILIAL quando a loja bater.
            if tipo == 'Vendedor' and not _is_vendedor_operacional_meta(nome):
                continue
            out.append({
                'key': f'{mes}|{chave}|{nome}|{filial}',
                'tipo': tipo,
                'nome': nome,
                'filial': filial,
                'atingido': ating,
                'atingido_txt': str(row.get('Atingido Total') or f'{ating:.2f}%'),
                'mes': mes,
            })
    seen=set(); final=[]
    for x in out:
        k=x['key']
        if k in seen: continue
        seen.add(k); final.append(x)
    return final


def build_meta_mercantil_100_alert(item, base_dir=None):
    """Mensagem bonita de meta mensal, com emojis, editável no dashboard e SEM qualquer valor em R$."""
    tipo = item.get('tipo') or 'Meta'
    nome = item.get('nome') or 'Equipe MDL'
    filial = item.get('filial') or ''
    destino = f'{nome}' + (f' | {filial}' if filial and filial not in nome else '')
    atingido = _sanitize_meta_alert_text(str(item.get('atingido_txt') or fmt_pct(item.get('atingido'))).strip())
    competencia = item.get('mes') or now_br().strftime('%Y-%m')
    tpl = _telegram_template('meta_mensal', base_dir)
    if tpl:
        rendered = _render_template(tpl, {
            'nome': destino, 'filial': filial, 'escopo': tipo, 'atingido': atingido,
            'tipo': tipo, 'data': now_br().strftime('%d/%m/%Y'), 'competencia': competencia
        })
        return _sanitize_meta_alert_text(_force_pretty_meta_template('meta_mensal', rendered))
    linhas = ['🏆🚀 PARABÉNS! META MENSAL BATIDA','',f'👏 Destaque: {destino}']
    if atingido:
        linhas.append(f'📈 Meta atingida: {atingido}')
    linhas += [f'🛒 Tipo: Venda mercantil / {tipo}',f'🗓️ Competência: {competencia}','','🔥 Excelente resultado no Controle de Meta do Sólidus!','💪 Resultado de time forte!']
    return _sanitize_meta_alert_text('\n'.join(linhas))




def load_projecao_mercantil_filiais(base_dir):
    """V18: dados do Controle de Meta Venda/Filial para o resumo final.
    Retorna Atingido Total, Realizado Período e Projetado por filial.
    """
    data = load_json_local_or_remote(base_dir, 'metas_vendas_mes_atual.json', 'metas_vendas_mes_atual.json', {})
    metas = data.get('metas') if isinstance(data, dict) else {}
    bloco = (metas or {}).get('venda_filial_meta') or {}
    out = []
    for row in (bloco.get('linhas') or []):
        if not isinstance(row, dict) or row.get('_is_total'):
            continue
        nome = str(row.get('Filial') or '').strip()
        if not nome or nome.lower() == 'total':
            continue
        out.append({
            'filial': nome,
            'atingido_total': str(row.get('Atingido Total') or '').strip(),
            'realizado_periodo': str(row.get('Realizado (R$) Período') or '').strip(),
            'projetado': str(row.get('Projetado (R$)') or '').strip(),
        })
    return out

def build_daily_summary(base_dir, date_str=None):
    """Resumo final das 19h.

    V23/V9.9:
    - separa cobrança real de ANIVERSARIO e REATIVACAO;
    - calcula corretamente quem cobrou, quem acionou reativação e quem enviou aniversário;
    - inclui metas diárias e mensais batidas;
    - mantém resumo comercial completo.
    """
    date_str = date_str or now_br().strftime("%Y-%m-%d")
    date_br = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y") if re.match(r"\d{4}-\d{2}-\d{2}", date_str) else date_str

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
    logs_day_all = [x for x in logs if _log_date(x) == date_str]
    logs_cob = [x for x in logs_day_all if _is_real_collection_log(x)]
    logs_reat = [x for x in logs_day_all if _is_reactivation_log(x)]
    logs_aniv = [x for x in logs_day_all if _is_birthday_log(x)]

    cob_keys, cob_top = _active_keys_for_logs(logs_cob)
    reat_keys, reat_top = _active_keys_for_logs(logs_reat)
    aniv_keys, aniv_top = _active_keys_for_logs(logs_aniv)

    users = _load_users(base_dir)
    sem_cob = _users_missing_action(users, cob_keys, "participa_cobrancas")
    sem_reat = _users_missing_action(users, reat_keys, "participa_sem_movimento")
    sem_aniv = _users_missing_action(users, aniv_keys, "participa_aniversariantes")

    msgs = _active_messages(base_dir)
    def _msg_kind_v103(m):
        return str(m.get("message_kind") or m.get("kind") or m.get("tipo") or m.get("categoria") or "").lower().strip()
    campaigns = [m for m in msgs if _msg_kind_v103(m) in {"campaign", "campanha", "campanhas"} or "campanha" in _msg_kind_v103(m)]
    notices = [m for m in msgs if m not in campaigns]

    merc = _float(sales_emp.get("venda_realizado_total"))
    serv = _float(sales_emp.get("servico_realizado_total"))
    cam = _float(sales_emp.get("caminhao_realizado_total"))
    faturamento = merc + serv
    venda_diaria = _float(sales_emp.get("venda_diaria_total") or sales_emp.get("venda_diaria") or sales_emp.get("venda_diaria_oficial"), 0.0)
    rent = _float(sales_emp.get("margem_bruta_pct"), 0.0)
    markup = _float(sales_emp.get("markup_realizado"), 0.0)

    try:
        metas_dia = load_meta_diaria_batidas(base_dir)
    except Exception:
        metas_dia = []
    try:
        metas_mes = load_meta_mercantil_100(base_dir)
    except Exception:
        metas_mes = []

    linhas = []
    linhas.append(f"📊 RESUMO FINAL DO DIA — {date_br}")
    linhas.append("Lojas MDL • COB+VENDAS")
    linhas.append("")

    linhas.append("💰 COBRANÇA / CARTEIRA")
    if emp:
        linhas.append(f"• Pendente geral: {fmt_money(emp.get('pendente'))}")
        linhas.append(f"• Recebido carteira: {fmt_money(emp.get('recebido'))}")
        if any(k in emp for k in ["grave", "alerta", "atencao"]):
            linhas.append(f"• Carteira: Grave {fmt_money(emp.get('grave'))} | Alerta {fmt_money(emp.get('alerta'))} | Atenção {fmt_money(emp.get('atencao'))}")
        if emp.get("perc_meta") is not None:
            linhas.append(f"• Meta cobrança: {fmt_pct(emp.get('perc_meta'))}")
    else:
        linhas.append("• Sem histórico consolidado de cobrança no dia.")
    linhas.append(f"• Recebimentos de hoje: Grave {receb_dia['grave']['qtd']} / {fmt_money(receb_dia['grave']['valor'])} | Alerta {receb_dia['alerta']['qtd']} / {fmt_money(receb_dia['alerta']['valor'])} | Atenção {receb_dia['atencao']['qtd']} / {fmt_money(receb_dia['atencao']['valor'])}")

    linhas.append("")
    linhas.append("🧡 VENDAS / SERVIÇOS / RENTABILIDADE")
    linhas.append(f"• Venda mercantil: {fmt_money(merc)} | Atingido mês: {fmt_pct(sales_emp.get('venda_atingido_total'))}")
    linhas.append(f"• Serviços: {fmt_money(serv)} | Atingido mês: {fmt_pct(sales_emp.get('servico_atingido_total'))}")
    linhas.append(f"• Caminhão: {fmt_money(cam)} | Atingido mês: {fmt_pct(sales_emp.get('caminhao_atingido_total'))}")
    linhas.append(f"• Venda geral/faturamento: {fmt_money(faturamento)}")
    linhas.append(f"• Venda diária: {fmt_money(venda_diaria)}")
    linhas.append(f"• Rentabilidade geral: {fmt_pct(rent)}")
    linhas.append(f"• Markup geral: {str(f'{markup:.2f}').replace('.', ',')}")

    try:
        proj_filiais = load_projecao_mercantil_filiais(base_dir)
    except Exception:
        proj_filiais = []
    linhas.append("")
    linhas.append("🏬 PROJEÇÃO MERCANTIL POR FILIAL")
    if proj_filiais:
        for p in proj_filiais[:12]:
            linhas.append(f"• {p.get('filial')}: atingido total {p.get('atingido_total') or '-'} | realizado período R$ {p.get('realizado_periodo') or '0,00'} | projetado R$ {p.get('projetado') or '0,00'}")
    else:
        linhas.append("• Sem dados de projeção mercantil por filial.")

    linhas.append("")
    linhas.append(f"📞 COBRANÇAS FEITAS HOJE: {len(logs_cob)} registro(s)")
    if cob_top:
        for nome, qtd in cob_top[:14]:
            linhas.append(f"• {nome}: {qtd}")
    else:
        linhas.append("• Nenhuma cobrança real registrada hoje.")
    linhas.append(f"🚫 Sem cobrança registrada: {len(sem_cob)} usuário(s)")
    linhas.append(_format_user_list(sem_cob, 24))

    linhas.append("")
    linhas.append(f"🧡 CLIENTES SEM MOVIMENTO / REATIVAÇÃO: {len(logs_reat)} acionamento(s)")
    if reat_top:
        for nome, qtd in reat_top[:10]:
            linhas.append(f"• {nome}: {qtd}")
    else:
        linhas.append("• Nenhuma reativação registrada hoje.")
    linhas.append(f"🚫 Sem acionar clientes inativos: {len(sem_reat)} usuário(s)")
    linhas.append(_format_user_list(sem_reat, 24))

    linhas.append("")
    linhas.append(f"🎂 ANIVERSARIANTES: {len(logs_aniv)} mensagem(ns) enviada(s)")
    if aniv_top:
        for nome, qtd in aniv_top[:10]:
            linhas.append(f"• {nome}: {qtd}")
    else:
        linhas.append("• Nenhuma mensagem de aniversário registrada hoje.")
    linhas.append(f"🚫 Sem enviar aniversariantes: {len(sem_aniv)} usuário(s)")
    linhas.append(_format_user_list(sem_aniv, 24))

    linhas.append("")
    linhas.append(f"🎯 METAS DIÁRIAS BATIDAS: {len(metas_dia)}")
    if metas_dia:
        for m in metas_dia[:12]:
            nome = m.get('nome') or m.get('filial') or 'Meta diária'
            escopo = m.get('escopo') or ''
            linhas.append(f"• {nome} — {m.get('atingido_txt') or fmt_pct(m.get('atingido'))}" + (f" ({escopo})" if escopo else ""))
    else:
        linhas.append("• Nenhuma meta diária batida registrada.")

    linhas.append("")
    linhas.append(f"🏆 METAS MENSAIS 100%+: {len(metas_mes)}")
    if metas_mes:
        for m in metas_mes[:12]:
            nome = m.get('nome') or 'Meta mensal'
            tipo = m.get('tipo') or ''
            linhas.append(f"• {nome} — {m.get('atingido_txt') or fmt_pct(m.get('atingido'))}" + (f" ({tipo})" if tipo else ""))
    else:
        linhas.append("• Nenhuma nova meta mensal acima de 100% na leitura atual.")

    linhas.append("")
    linhas.append(f"📣 AVISOS ATIVOS: {len(notices)} | CAMPANHAS ATIVAS: {len(campaigns)}")
    for m in (campaigns + notices)[:6]:
        titulo = str(m.get("title") or "Sem título").strip()
        alvo = str(m.get("target_label") or m.get("target_type") or "Todos").strip()
        exp = str(m.get("expires_at") or "").strip()
        prefix = "🚀" if m in campaigns else "🔔"
        linhas.append(f"{prefix} {titulo} — {alvo}" + (f" até {exp}" if exp else ""))

    linhas.append("")
    linhas.append(f"🕒 Gerado em {now_br().strftime('%d/%m/%Y %H:%M:%S')}")
    return "\n".join(linhas)


# MDL_V99_RESUMO_LOGS_REMOTE_AVISOS: le cobrancas_log/cobrancas_api/mensagens_api remotos e locais, com deduplicacao.

# MDL_V101_META_DIARIA_VALIDADA: alertas somente por Realizado Período / Meta Período.
# MDL_V102_META_DIARIA_STRICT: bloqueia discrepância de Atingido Período e qualquer leitura acima de 500%.

# MDL_V103_RESUMO_LOGS_ROBUSTO
