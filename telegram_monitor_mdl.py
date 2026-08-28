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


# VERSAO: TELEGRAM_MONITOR_MDL_V10_101_COBRANCA_DIARIA_LIVE
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
TELEGRAM_NOTIFICACOES_ENABLED = os.getenv('TELEGRAM_NOTIFICACOES_ENABLED', '1') != '0'


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
    """V10.92: Telegram usa PRIMEIRO a config online mais recente.

    Motivo: o dashboard salva novos Chat IDs no config_meta.json público.
    O arquivo local do Railway pode ficar antigo entre execuções/deploys.
    Só usamos cache/local se a leitura online falhar.
    """
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))

    # Fonte principal: config público salvo pelo dashboard, com cachebuster.
    cfg = _read_url_json(
        f"{PUBLIC_BASE}/config_meta.json?_tg={int(time.time())}",
        None,
        timeout=10,
    )

    # Fallback local apenas em indisponibilidade real da fonte online.
    if not isinstance(cfg, dict):
        candidates = [
            os.path.join(base_dir, 'cache_historico', 'config_meta.json'),
            os.path.join(base_dir, 'config_meta.json'),
        ]
        for p in candidates:
            cfg = _read_json_file(p, None)
            if isinstance(cfg, dict):
                break

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
                'auditoria': b('auditoria', True),
                'cob_externa': b('cob_externa', True),
                'cobranca_diaria': b('cobranca_diaria', False),
                'cobranca_3h': b('cobranca_3h', False),
                'teste': True,
            })
    if not out:
        env_chat = os.getenv('TELEGRAM_CHAT_ID', '').strip()
        if env_chat:
            out.append({'nome':'TELEGRAM_CHAT_ID','chat_id':env_chat,'ativo':True,'erros':True,'meta_diaria':True,'meta_mensal':True,'avisos':True,'resumo':True,'auditoria':True,'cob_externa':True,'cobranca_diaria':True,'cobranca_3h':False,'teste':True})
    return out


def _telegram_contacts_for_alert(alert_type='geral', base_dir=None):
    alert_type = str(alert_type or 'geral').lower().strip()
    key_map = {
        'erro': 'erros', 'erros': 'erros', 'sistema': 'erros',
        'meta_diaria': 'meta_diaria', 'diaria': 'meta_diaria',
        'meta_mensal': 'meta_mensal', 'meta100': 'meta_mensal', 'mercantil100': 'meta_mensal',
        'aviso': 'avisos', 'avisos': 'avisos', 'campanha': 'avisos', 'geral': 'avisos',
        'resumo': 'resumo', 'daily_summary': 'resumo',
        'auditoria': 'auditoria', 'audit': 'auditoria',
        'cob_externa': 'cob_externa', 'cob': 'cob_externa',
        'cobranca_diaria': 'cobranca_diaria', 'daily_collection': 'cobranca_diaria',
        'cobranca_3h': 'cobranca_3h', 'collection_3h': 'cobranca_3h', 'cobrancas_3h': 'cobranca_3h',
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
    if not TELEGRAM_NOTIFICACOES_ENABLED:
        return False, 'TELEGRAM_NOTIFICACOES_ENABLED=0'
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
    total_ok = sum(1 for x in oks if x)
    return any(oks), f"{total_ok}/{len(contacts)} contato(s) enviado(s) | " + " | ".join(resps)

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
    """Carrega logs de cobrança/reativação/aniversário de forma bem robusta.

    V29:
    - tenta HTTPS e HTTP do /colaborador;
    - aumenta timeout dos arquivos grandes;
    - prioriza também NDJSON do dia, que é menor e evita resumo zerado;
    - aceita cópias locais em monitor_logs/cache_historico.
    """
    hoje = now_br().strftime("%Y-%m-%d")
    ontem = (now_br() - timedelta(days=1)).strftime("%Y-%m-%d")
    bases = [PUBLIC_BASE]
    if PUBLIC_BASE.startswith('https://'):
        bases.append('http://' + PUBLIC_BASE[len('https://'):])
    elif PUBLIC_BASE.startswith('http://'):
        bases.append('https://' + PUBLIC_BASE[len('http://'):])
    # remove duplicados preservando ordem
    seen_b=set(); bases=[b for b in bases if not (b in seen_b or seen_b.add(b))]

    sources = []
    for base in bases:
        sources.append(_read_url_ndjson(f"{base}/backups_cobrancas/cobrancas_log_append_{hoje}.ndjson", timeout=35))
        sources.append(_read_url_json(f"{base}/backups_cobrancas/cobrancas_log_{hoje}_latest.json", [], timeout=35))
        sources.append(_read_url_json(f"{base}/cobrancas_api.php", [], timeout=45))
        sources.append(_read_url_json(f"{base}/cobrancas_api.php?full=1", [], timeout=45))
        sources.append(_read_url_json(f"{base}/cobrancas_log.json", [], timeout=45))
        sources.append(_read_url_ndjson(f"{base}/backups_cobrancas/cobrancas_log_append_{ontem}.ndjson", timeout=20))
        sources.append(_read_url_json(f"{base}/backups_cobrancas/cobrancas_log_{ontem}_latest.json", [], timeout=20))

    sources.append(_read_json_file(os.path.join(base_dir, "cobrancas_log.json"), []))
    sources.append(_read_json_file_any(os.path.join(base_dir, "monitor_logs", "cobrancas_log.json"), []))
    sources.append(_read_json_file_any(os.path.join(base_dir, "cache_historico", "cobrancas_log.json"), []))
    out = _merge_log_sources(*sources)
    return out


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



def _log_belongs_to_date(x, date_str):
    """Confere a data do log por campos formais e por fallback textual."""
    if not isinstance(x, dict):
        return False
    if _log_date(x) == date_str:
        return True
    for k in ("server_date", "server_time", "created_at", "criado_em", "data_hora", "data", "timestamp", "date"):
        raw = str(x.get(k) or "")
        if raw.startswith(date_str):
            return True
        if date_str in raw:
            return True
    br = ""
    try:
        br = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        br = ""
    if br:
        blob = " ".join(str(v) for v in x.values() if isinstance(v, (str, int, float)))
        if br in blob:
            return True
    return False


def _is_action_whatsapp_log(x):
    if not isinstance(x, dict):
        return False
    return bool(
        str(x.get('acao') or '').lower() == 'whatsapp'
        or x.get('telefone') or x.get('phone') or x.get('whatsapp')
        or x.get('cliente') or x.get('nome')
    )

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
    # V29: alguns logs de clientes sem movimento usam REATIF no cliente_key/parcela/cobranca_key.
    return ("REATIVACAO" in blob) or ("REATIVAÇÃO" in blob) or ("REATIF" in blob) or ("CLIENTE_SEM_MOVIMENTO" in blob) or ("SEM_MOVIMENTO" in blob)


def _is_birthday_log(x):
    blob = _log_blob_upper(x)
    return ("ANIVERSARIO" in blob) or ("ANIVERSÁRIO" in blob) or ("ANIV" in blob) or ("BIRTHDAY" in blob)


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


# ===== V10.99 RELATÓRIO DIÁRIO DE COBRANÇA PARA TELEGRAM =====
def _v1099_row_key(row):
    if not isinstance(row, dict):
        return ""
    doc = re.sub(r"\D+", "", str(row.get("cpf_cnpj_normalizado") or row.get("cpf_cnpj") or ""))
    tit_raw = str(row.get("titulo") or "").strip()
    tit = re.sub(r"\D+", "", tit_raw) or tit_raw.upper()
    nums = re.findall(r"\d+", str(row.get("parcela") or ""))
    par = "/".join(str(int(x)) for x in nums[:2]) if nums else str(row.get("parcela") or "").strip().upper()
    return f"{doc}|{tit}|{par}"

def _v1099_norm(v):
    import unicodedata
    s = unicodedata.normalize("NFD", str(v or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()

def _v1099_date(v):
    s = str(v or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return s[:10]

def _load_daily_collection_snapshot_v1099(base_dir):
    data = load_json_local_or_remote(base_dir, "cobranca_diaria_resumo.json", "cobranca_diaria_resumo.json", {})
    return data if isinstance(data, dict) else {}

def _load_audits_v1099(base_dir):
    candidates = []
    for url in (
        f"{PUBLIC_BASE}/cobranca_auditoria.json",
        f"{PUBLIC_BASE}/cobranca_auditoria_api.php?full=1",
        f"{PUBLIC_BASE}/cobranca_auditoria_api.php",
    ):
        candidates += _extract_list_payload(_read_url_json(url, [], timeout=35))
    candidates += _extract_list_payload(_read_json_file(os.path.join(base_dir, "cobranca_auditoria.json"), []))
    return _dedup_dicts_by_id(candidates)

def _load_paid_v1099(base_dir):
    data = load_json_local_or_remote(base_dir, "quitados_180d_contas_receber.json", "quitados_180d_contas_receber.json", {})
    if isinstance(data, dict):
        rows = data.get("quitados") or data.get("data") or data.get("rows") or []
    else:
        rows = data
    return rows if isinstance(rows, list) else []

def _v1099_approved(status):
    return str(status or "").lower().strip() in {"aprovado","aprovado_ia","aprovado_manual"}

def _v1099_entity_match(row, ent):
    if not isinstance(row, dict) or not isinstance(ent, dict):
        return False
    login = str(ent.get("login") or "").lower().strip()
    nome = _v1099_norm(ent.get("nome"))
    filial = str(ent.get("filial") or "").upper().strip()
    vals = [
        str(row.get("usuario_login") or "").lower().strip(),
        str(row.get("usuario") or "").lower().strip(),
        str(row.get("login") or "").lower().strip(),
    ]
    if login and login in vals:
        return True
    names = [_v1099_norm(row.get("usuario_nome")), _v1099_norm(row.get("destino_nome")), _v1099_norm(row.get("responsavel"))]
    if nome and nome in names:
        rf = str(row.get("filial") or "").upper().strip()
        return not filial or not rf or rf == filial
    return False

def _v1099_same(a, b):
    return bool(_v1099_row_key(a)) and _v1099_row_key(a) == _v1099_row_key(b)

def build_daily_collection_summary(base_dir, date_str=None):
    """Resumo curto, separado, roteável por Chat ID usando alert_type=cobranca_diaria."""
    date_str = date_str or now_br().strftime("%Y-%m-%d")
    snap = _load_daily_collection_snapshot_v1099(base_dir)
    entities = snap.get("entities") if isinstance(snap.get("entities"), list) else []
    entities = [e for e in entities if isinstance(e, dict) and e.get("ativo", True)]
    audits = _load_audits_v1099(base_dir)
    paid = _load_paid_v1099(base_dir)

    rows = []
    for ent in entities:
        cob_keys = set(str(x) for x in (ent.get("cobrados_keys") or []) if x)
        approved_keys = set()
        paid_keys = set()
        received = 0.0

        for a in audits:
            if not _v1099_approved(a.get("status")):
                continue
            if not _v1099_entity_match(a, ent):
                continue
            k = _v1099_row_key(a)
            if not k or k not in cob_keys:
                continue
            approved_keys.add(k)

            matches = [
                q for q in paid
                if _v1099_same(a, q)
                and _v1099_date(q.get("pagamento") or q.get("data_pagamento")) >= date_str
            ]
            if matches and k not in paid_keys:
                q = sorted(matches, key=lambda x: _v1099_date(x.get("pagamento") or x.get("data_pagamento")))[0]
                paid_keys.add(k)
                received += _float(q.get("pago"), 0.0)

        feitos = int(ent.get("cobrancas_feitas") or 0)
        previstos = int(ent.get("previstos") or 0)
        nao = int(ent.get("nao_trabalhados") or 0)
        valor_nao = _float(ent.get("valor_nao_trabalhado"), 0.0)
        eff = (len(paid_keys) / feitos * 100.0) if feitos else 0.0
        exec_pct = (feitos / previstos * 100.0) if previstos else 100.0

        rows.append({
            **ent,
            "auditorias_aprovadas": len(approved_keys),
            "pagamentos_conciliados": len(paid_keys),
            "recebido_conciliado": round(received, 2),
            "taxa_efetividade": round(eff, 1),
            "taxa_execucao": round(exec_pct, 1),
            "nao_trabalhados": nao,
            "valor_nao_trabalhado": round(valor_nao, 2),
        })

    users_queue = [r for r in rows if int(r.get("previstos") or 0) > 0]
    no_work = [r for r in users_queue if int(r.get("cobrancas_feitas") or 0) == 0]
    partial = [r for r in users_queue if 0 < int(r.get("cobrancas_feitas") or 0) < int(r.get("previstos") or 0)]
    total_cob = sum(int(r.get("cobrancas_feitas") or 0) for r in rows)
    total_aud = sum(int(r.get("auditorias_aprovadas") or 0) for r in rows)
    total_pay = sum(int(r.get("pagamentos_conciliados") or 0) for r in rows)
    total_rec = sum(_float(r.get("recebido_conciliado"), 0.0) for r in rows)

    ssum = snap.get("summary") if isinstance(snap.get("summary"), dict) else {}
    lost_unique = _float(ssum.get("valor_nao_trabalhado_unico"), 0.0)
    lost_titles = int(ssum.get("titulos_nao_trabalhados_unicos") or 0)

    date_br = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y") if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str) else date_str
    lines = [
        f"📞 COBRANÇA DIÁRIA — {date_br}",
        "Lojas MDL • resumo operacional",
        "",
        f"👥 Usuários com fila: {len(users_queue)}",
        f"📲 Cobranças feitas: {total_cob}",
        f"✅ Auditorias aprovadas: {total_aud}",
        f"💵 Pagamentos conciliados: {total_pay}",
        f"🏦 Recebido conciliado: {fmt_money(total_rec)}",
        f"⚠️ Oportunidade não trabalhada: {lost_titles} título(s) • {fmt_money(lost_unique)}",
        "",
    ]

    if no_work:
        lines.append(f"🚫 NÃO COBRARAM ({len(no_work)}):")
        for r in no_work[:12]:
            lines.append(f"• {r.get('nome') or r.get('login')} · {r.get('filial') or '-'} · fila {r.get('previstos',0)} · {fmt_money(r.get('valor_previsto'))}")
        if len(no_work) > 12:
            lines.append(f"• +{len(no_work)-12} usuário(s)")
    else:
        lines.append("✅ Todos os usuários com fila fizeram ao menos uma cobrança.")

    if partial:
        lines.append("")
        lines.append(f"🟠 PARCIAIS ({len(partial)}):")
        for r in sorted(partial, key=lambda x: float(x.get("taxa_execucao") or 0))[:8]:
            lines.append(f"• {r.get('nome') or r.get('login')}: execução {str(r.get('taxa_execucao',0)).replace('.',',')}%")

    top_eff = [r for r in rows if int(r.get("cobrancas_feitas") or 0) > 0]
    top_eff.sort(key=lambda x: (float(x.get("taxa_efetividade") or 0), int(x.get("pagamentos_conciliados") or 0)), reverse=True)
    if top_eff:
        lines.append("")
        lines.append("📈 EFETIVIDADE — destaques:")
        for r in top_eff[:8]:
            lines.append(
                f"• {r.get('nome') or r.get('login')}: "
                f"{str(r.get('taxa_efetividade',0)).replace('.',',')}% "
                f"({r.get('pagamentos_conciliados',0)}/{r.get('cobrancas_feitas',0)})"
            )

    lines += [
        "",
        "ℹ️ “Oportunidade não trabalhada” é o valor deduplicado dos títulos que permaneceram disponíveis sem cobrança no dia; não é recebimento garantido.",
        f"🕒 Gerado em {now_br().strftime('%d/%m/%Y %H:%M:%S')}",
    ]
    return "\n".join(lines)


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
    logs_day_all = [x for x in logs if _log_belongs_to_date(x, date_str)]
    logs_reat = [x for x in logs_day_all if _is_reactivation_log(x)]
    logs_aniv = [x for x in logs_day_all if _is_birthday_log(x)]
    logs_cob = [x for x in logs_day_all if _is_real_collection_log(x)]
    # V29: fallback contra resumo zerado quando o formato do log do PHP muda.
    if not logs_cob and logs_day_all:
        logs_cob = [x for x in logs_day_all if (not _is_reactivation_log(x)) and (not _is_birthday_log(x)) and _is_action_whatsapp_log(x)]

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

# V10.91_TELEGRAM_CANAL_PRINCIPAL_AUDITORIA_COB_EXTERNA

# V10.92_TELEGRAM_MULTI_GRUPOS_REMOTE_FIRST

# V10.99_TELEGRAM_COBRANCA_DIARIA


# ===== V10.100: COBRANÇA DIÁRIA TELEGRAM ROBUSTA =====
def build_daily_collection_summary(base_dir, date_str=None):
    """
    V10.100:
    - sempre consegue montar ao menos o resumo operacional do snapshot local;
    - enriquecimento de auditoria/pagamento usa timeout curto e nunca impede o envio;
    - evita o clique manual retornar "enfileirado" e depois falhar silenciosamente.
    """
    date_str = date_str or now_br().strftime("%Y-%m-%d")
    snap = _read_json_file(os.path.join(base_dir, "cobranca_diaria_resumo.json"), None)
    if not isinstance(snap, dict):
        snap = _read_url_json(f"{PUBLIC_BASE}/cobranca_diaria_resumo.json?_={int(time.time())}", {}, timeout=6)
    if not isinstance(snap, dict):
        snap = {}

    entities = snap.get("entities") if isinstance(snap.get("entities"), list) else []
    entities = [e for e in entities if isinstance(e, dict) and e.get("ativo", True)]
    summary = snap.get("summary") if isinstance(snap.get("summary"), dict) else {}

    # Enriquecimento best-effort. Se falhar, a mensagem operacional continua.
    audits = []
    paid = []
    try:
        ajson = _read_url_json(f"{PUBLIC_BASE}/cobranca_auditoria_api.php?_={int(time.time())}", {}, timeout=6)
        audits = _extract_list_payload(ajson)
    except Exception:
        audits = []
    try:
        pjson = _read_json_file(os.path.join(base_dir, "quitados_180d_contas_receber.json"), None)
        if pjson is None:
            pjson = _read_url_json(f"{PUBLIC_BASE}/quitados_180d_contas_receber.json?_={int(time.time())}", {}, timeout=6)
        if isinstance(pjson, dict):
            paid = pjson.get("quitados") or pjson.get("data") or pjson.get("rows") or []
        elif isinstance(pjson, list):
            paid = pjson
    except Exception:
        paid = []
    if not isinstance(paid, list):
        paid = []

    rows = []
    for ent in entities:
        cob_keys = set(str(x) for x in (ent.get("cobrados_keys") or []) if x)
        approved_keys = set()
        paid_keys = set()
        rec = 0.0

        for a in audits:
            if not isinstance(a, dict) or not _v1099_approved(a.get("status")):
                continue
            if not _v1099_entity_match(a, ent):
                continue
            k = _v1099_row_key(a)
            if not k or k not in cob_keys:
                continue
            approved_keys.add(k)
            if k in paid_keys:
                continue
            matches = [q for q in paid if isinstance(q, dict) and _v1099_same(a,q) and _v1099_date(q.get("pagamento") or q.get("data_pagamento")) >= date_str]
            if matches:
                q = sorted(matches, key=lambda x: _v1099_date(x.get("pagamento") or x.get("data_pagamento")))[0]
                paid_keys.add(k)
                rec += _float(q.get("pago"), 0.0)

        feitos = int(ent.get("cobrancas_feitas") or 0)
        previstos = int(ent.get("previstos") or 0)
        rows.append({
            **ent,
            "auditorias_aprovadas": len(approved_keys),
            "pagamentos_conciliados": len(paid_keys),
            "recebido_conciliado": round(rec,2),
            "taxa_execucao": round((feitos/previstos*100.0) if previstos else 100.0,1),
            "taxa_auditoria": round((len(approved_keys)/feitos*100.0) if feitos else 0.0,1),
            "taxa_efetividade": round((len(paid_keys)/feitos*100.0) if feitos else 0.0,1),
        })

    with_queue=[r for r in rows if int(r.get("previstos") or 0)>0]
    no_work=[r for r in with_queue if int(r.get("cobrancas_feitas") or 0)==0]
    partial=[r for r in with_queue if 0<int(r.get("cobrancas_feitas") or 0)<int(r.get("previstos") or 0)]
    total_cob=sum(int(r.get("cobrancas_feitas") or 0) for r in rows)
    total_aud=sum(int(r.get("auditorias_aprovadas") or 0) for r in rows)
    total_pay=sum(int(r.get("pagamentos_conciliados") or 0) for r in rows)
    total_rec=sum(_float(r.get("recebido_conciliado"),0) for r in rows)
    lost=_float(summary.get("valor_nao_trabalhado_unico"),0)
    lost_q=int(summary.get("titulos_nao_trabalhados_unicos") or 0)

    try:
        date_br=datetime.strptime(date_str,"%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        date_br=date_str

    lines=[
        f"📞 COBRANÇA DIÁRIA — {date_br}",
        "Lojas MDL • resumo operacional",
        "",
        f"👥 Usuários com fila: {len(with_queue)}",
        f"📲 Cobranças feitas: {total_cob}",
        f"✅ Auditorias aprovadas: {total_aud}",
        f"💵 Pagamentos conciliados: {total_pay}",
        f"🏦 Recebido conciliado: {fmt_money(total_rec)}",
        f"⚠️ Oportunidade não trabalhada: {lost_q} título(s) • {fmt_money(lost)}",
        ""
    ]
    if no_work:
        lines.append(f"🚫 NÃO COBRARAM ({len(no_work)}):")
        for r in no_work[:12]:
            lines.append(f"• {r.get('nome') or r.get('login')} · {r.get('filial') or '-'} · fila {r.get('previstos',0)} · {fmt_money(r.get('valor_previsto'))}")
        if len(no_work)>12:
            lines.append(f"• +{len(no_work)-12} usuário(s)")
    else:
        lines.append("✅ Todos os usuários com fila fizeram ao menos uma cobrança.")

    if partial:
        lines.append("")
        lines.append(f"🟠 PARCIAIS ({len(partial)}):")
        for r in sorted(partial,key=lambda x:float(x.get("taxa_execucao") or 0))[:8]:
            lines.append(f"• {r.get('nome') or r.get('login')}: execução {str(r.get('taxa_execucao',0)).replace('.',',')}%")

    eff=[r for r in rows if int(r.get("cobrancas_feitas") or 0)>0]
    eff.sort(key=lambda x:(float(x.get("taxa_efetividade") or 0),int(x.get("pagamentos_conciliados") or 0)),reverse=True)
    if eff:
        lines += ["","📈 EFETIVIDADE PAGA — destaques:"]
        for r in eff[:8]:
            lines.append(f"• {r.get('nome') or r.get('login')}: {str(r.get('taxa_efetividade',0)).replace('.',',')}% ({r.get('pagamentos_conciliados',0)}/{r.get('cobrancas_feitas',0)})")

    lines += ["","ℹ️ Execução = cobranças feitas ÷ previstos. Efetividade paga = pagamentos conciliados ÷ cobranças feitas.","ℹ️ Oportunidade não trabalhada não é recebimento garantido.",f"🕒 Gerado em {now_br().strftime('%d/%m/%Y %H:%M:%S')}"]
    return "\n".join(lines)


def send_daily_collection_now_v10100(base_dir, date_str=None):
    text = build_daily_collection_summary(base_dir, date_str or now_br().strftime("%Y-%m-%d"))
    return telegram_send(text, alert_type="cobranca_diaria", base_dir=base_dir)

# V10.100_TELEGRAM_COBRANCA_DIARIA_ROBUSTA


# ===== V10.101: COBRANÇA DIÁRIA LIVE =====
def _v10101_fetch_detail(base_dir, entry):
    if not isinstance(entry, dict):
        return {"grave":[],"alerta":[],"atencao":[]}
    file_name = str(entry.get("file") or "").lstrip("/")
    data = None
    if file_name:
        data = _read_json_file(os.path.join(base_dir, file_name.replace("/", os.sep)), None)
        if data is None:
            data = _read_url_json(f"{PUBLIC_BASE}/{file_name}?_={int(time.time())}", None, timeout=8)
    if isinstance(data, dict):
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if isinstance(payload, dict):
            return {fx:(payload.get(fx) if isinstance(payload.get(fx), list) else []) for fx in ("grave","alerta","atencao")}
    return {"grave":[],"alerta":[],"atencao":[]}

def _v10101_manifest(base_dir):
    data = _read_json_file(os.path.join(base_dir, "clientes_detalhes", "manifest.json"), None)
    if data is None:
        data = _read_url_json(f"{PUBLIC_BASE}/clientes_detalhes/manifest.json?_={int(time.time())}", {}, timeout=8)
    return data if isinstance(data, dict) else {}

def _v10101_entry_for_user(user, manifest):
    if user.get("is_crediarista"):
        return (manifest.get("crediaristas") or {}).get(str(user.get("login") or "").lower())
    if user.get("is_terceiro"):
        return manifest.get("terceiro")
    vendors = manifest.get("vendedores") if isinstance(manifest.get("vendedores"), dict) else {}
    uname = _v1099_norm(user.get("nome"))
    filial = str(user.get("filial") or "").upper()
    for name, entry in vendors.items():
        if _v1099_norm(name) != uname:
            continue
        ef = str((entry or {}).get("filial") or "").upper()
        if not filial or not ef or ef == filial:
            return entry
    return None

def _v10101_dt(v):
    s = str(v or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z","+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=BR_TZ)
        return d.astimezone(BR_TZ)
    except Exception:
        pass
    ds = _v1099_date(s)
    try:
        return datetime.strptime(ds,"%Y-%m-%d").replace(tzinfo=BR_TZ)
    except Exception:
        return None

def _v10101_live_rows(base_dir, date_str):
    users = [u for u in _load_users(base_dir) if u.get("participa_cobrancas", True) and not u.get("is_gerente")]
    manifest = _v10101_manifest(base_dir)
    logs = _load_cobrancas(base_dir)
    logs = [x for x in logs if isinstance(x, dict) and str(x.get("acao") or "whatsapp").lower() == "whatsapp"]
    target = datetime.strptime(date_str,"%Y-%m-%d").replace(tzinfo=BR_TZ)
    out = []

    for user in users:
        ent = {
            "tipo":"crediarista" if user.get("is_crediarista") else ("terceiro" if user.get("is_terceiro") else "vendedor"),
            "login":str(user.get("login") or "").lower(),
            "nome":str(user.get("nome") or ""),
            "filial":str(user.get("filial") or "").upper(),
            "ativo":True,
        }
        detail = _v10101_fetch_detail(base_dir, _v10101_entry_for_user(user, manifest))
        detail_rows = []
        value_by_key = {}
        for fx in ("grave","alerta","atencao"):
            for r in detail.get(fx) or []:
                if not isinstance(r, dict):
                    continue
                rr = dict(r); rr["_faixa_v10101"] = fx
                k = _v1099_row_key(rr)
                if k and k not in value_by_key:
                    value_by_key[k] = _float(rr.get("pendente"),0.0)
                detail_rows.append(rr)

        ent_logs = [l for l in logs if _v1099_entity_match(l, ent)]
        by_key = {}
        today = []
        today_keys = set()
        for l in ent_logs:
            k = _v1099_row_key(l)
            if not k:
                continue
            by_key.setdefault(k,[]).append(l)
            if _v1099_date(l.get("server_time") or l.get("criado_em") or l.get("data") or l.get("server_date")) == date_str and k not in today_keys:
                today_keys.add(k); today.append(l)
        for k in by_key:
            by_key[k].sort(key=lambda x: str(x.get("server_time") or x.get("criado_em") or x.get("data") or ""))

        actionable = {}
        for r in detail_rows:
            k = _v1099_row_key(r)
            if not k:
                continue
            last = (by_key.get(k) or [None])[-1]
            if last is None:
                actionable[k] = r
                continue
            ldt = _v10101_dt(last.get("server_time") or last.get("criado_em") or last.get("data") or last.get("server_date"))
            if ldt is None or (target.date() - ldt.date()).days >= 3:
                actionable[k] = r

        plan = dict(actionable)
        for l in today:
            k = _v1099_row_key(l)
            if k not in plan:
                ref = next((r for r in detail_rows if _v1099_row_key(r)==k), l)
                plan[k] = ref
                if k not in value_by_key:
                    value_by_key[k] = _float(ref.get("pendente"),0.0)

        not_worked = {k:r for k,r in actionable.items() if k not in today_keys}
        out.append({
            **ent,
            "previstos":len(plan),
            "valor_previsto":round(sum(value_by_key.get(k,0.0) for k in plan),2),
            "cobrancas_feitas":len(today_keys),
            "valor_cobrado":round(sum(_float(value_by_key.get(k,0.0),0.0) for k in today_keys),2),
            "nao_trabalhados":len(not_worked),
            "valor_nao_trabalhado":round(sum(value_by_key.get(k,0.0) for k in not_worked),2),
            "cobrados_keys":sorted(today_keys),
            "previstos_keys":sorted(plan.keys()),
            "nao_trabalhados_keys":sorted(not_worked.keys()),
            "valores_por_key":{k:round(_float(value_by_key.get(k,0.0),0.0),2) for k in plan},
        })
    return out

def build_daily_collection_summary(base_dir, date_str=None):
    """V10.101: calcula fila e cobranças ao vivo no momento do envio."""
    date_str = date_str or now_br().strftime("%Y-%m-%d")
    try:
        entities = _v10101_live_rows(base_dir, date_str)
    except Exception as e:
        entities = []
        print(f"⚠️ V10.101 live daily rows falhou: {e}")

    # Fallback somente se live falhar totalmente.
    if not entities:
        snap = _read_json_file(os.path.join(base_dir, "cobranca_diaria_resumo.json"), None)
        if not isinstance(snap, dict):
            snap = _read_url_json(f"{PUBLIC_BASE}/cobranca_diaria_resumo.json?_={int(time.time())}", {}, timeout=6)
        entities = (snap or {}).get("entities") if isinstance((snap or {}).get("entities"), list) else []

    audits = []
    paid = []
    try:
        ajson = _read_url_json(f"{PUBLIC_BASE}/cobranca_auditoria_api.php?_={int(time.time())}", {}, timeout=8)
        audits = _extract_list_payload(ajson)
    except Exception:
        audits = []
    try:
        pjson = _read_url_json(f"{PUBLIC_BASE}/quitados_180d_contas_receber.json?_={int(time.time())}", {}, timeout=8)
        if isinstance(pjson, dict):
            paid = pjson.get("quitados") or pjson.get("data") or pjson.get("rows") or []
        elif isinstance(pjson, list):
            paid = pjson
    except Exception:
        paid = []
    if not isinstance(paid, list):
        paid = []

    rows = []
    global_plan = {}
    global_cob = set()

    for ent in entities:
        cob_keys = set(str(x) for x in (ent.get("cobrados_keys") or []) if x)
        global_cob.update(cob_keys)
        for k,v in (ent.get("valores_por_key") or {}).items():
            global_plan.setdefault(str(k), _float(v,0.0))

        approved_keys=set();paid_keys=set();received=0.0
        for a in audits:
            if not isinstance(a,dict) or not _v1099_approved(a.get("status")) or not _v1099_entity_match(a,ent):
                continue
            k=_v1099_row_key(a)
            if not k or k not in cob_keys:
                continue
            approved_keys.add(k)
            if k in paid_keys:
                continue
            matches=[q for q in paid if isinstance(q,dict) and _v1099_same(a,q) and _v1099_date(q.get("pagamento") or q.get("data_pagamento"))>=date_str]
            if matches:
                q=sorted(matches,key=lambda x:_v1099_date(x.get("pagamento") or x.get("data_pagamento")))[0]
                paid_keys.add(k);received+=_float(q.get("pago"),0.0)

        feitos=int(ent.get("cobrancas_feitas") or 0)
        previstos=int(ent.get("previstos") or 0)
        rows.append({
            **ent,
            "auditorias_aprovadas":len(approved_keys),
            "pagamentos_conciliados":len(paid_keys),
            "recebido_conciliado":round(received,2),
            "taxa_execucao":round((feitos/previstos*100.0) if previstos else 100.0,1),
            "taxa_auditoria":round((len(approved_keys)/feitos*100.0) if feitos else 0.0,1),
            "taxa_efetividade":round((len(paid_keys)/feitos*100.0) if feitos else 0.0,1),
        })

    not_worked_global={k:v for k,v in global_plan.items() if k not in global_cob}
    with_queue=[r for r in rows if int(r.get("previstos") or 0)>0]
    no_work=[r for r in with_queue if int(r.get("cobrancas_feitas") or 0)==0]
    partial=[r for r in with_queue if 0<int(r.get("cobrancas_feitas") or 0)<int(r.get("previstos") or 0)]
    total_cob=sum(int(r.get("cobrancas_feitas") or 0) for r in rows)
    total_aud=sum(int(r.get("auditorias_aprovadas") or 0) for r in rows)
    total_pay=sum(int(r.get("pagamentos_conciliados") or 0) for r in rows)
    total_rec=sum(_float(r.get("recebido_conciliado"),0) for r in rows)
    lost=sum(not_worked_global.values())

    try: date_br=datetime.strptime(date_str,"%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception: date_br=date_str

    lines=[
        f"📞 COBRANÇA DIÁRIA — {date_br}",
        "Lojas MDL • dados LIVE no momento do envio",
        "",
        f"👥 Usuários com fila: {len(with_queue)}",
        f"📲 Cobranças feitas: {total_cob}",
        f"✅ Auditorias aprovadas: {total_aud}",
        f"💵 Pagamentos conciliados: {total_pay}",
        f"🏦 Recebido conciliado: {fmt_money(total_rec)}",
        f"⚠️ Oportunidade não trabalhada: {len(not_worked_global)} título(s) • {fmt_money(lost)}",
        ""
    ]
    if no_work:
        lines.append(f"🚫 NÃO COBRARAM ({len(no_work)}):")
        for r in no_work[:12]:
            lines.append(f"• {r.get('nome') or r.get('login')} · {r.get('filial') or '-'} · fila {r.get('previstos',0)} · {fmt_money(r.get('valor_previsto'))}")
        if len(no_work)>12:lines.append(f"• +{len(no_work)-12} usuário(s)")
    else:
        lines.append("✅ Todos os usuários com fila fizeram ao menos uma cobrança.")

    if partial:
        lines += ["",f"🟠 PARCIAIS ({len(partial)}):"]
        for r in sorted(partial,key=lambda x:float(x.get("taxa_execucao") or 0))[:8]:
            lines.append(f"• {r.get('nome') or r.get('login')}: execução {str(r.get('taxa_execucao',0)).replace('.',',')}%")

    eff=[r for r in rows if int(r.get("cobrancas_feitas") or 0)>0]
    eff.sort(key=lambda x:(float(x.get("taxa_efetividade") or 0),int(x.get("pagamentos_conciliados") or 0)),reverse=True)
    if eff:
        lines += ["","📈 EFETIVIDADE PAGA — destaques:"]
        for r in eff[:8]:
            lines.append(f"• {r.get('nome') or r.get('login')}: {str(r.get('taxa_efetividade',0)).replace('.',',')}% ({r.get('pagamentos_conciliados',0)}/{r.get('cobrancas_feitas',0)})")

    lines += ["","ℹ️ Execução = cobranças feitas ÷ previstos. Efetividade paga = pagamentos conciliados ÷ cobranças feitas.","ℹ️ Oportunidade não trabalhada não é recebimento garantido.",f"🕒 Gerado LIVE em {now_br().strftime('%d/%m/%Y %H:%M:%S')}"]
    return "\n".join(lines)

def send_daily_collection_now_v10100(base_dir, date_str=None):
    # Mantém o nome importado pelo scheduler, mas agora usa V10.101 LIVE.
    text = build_daily_collection_summary(base_dir, date_str or now_br().strftime("%Y-%m-%d"))
    return telegram_send(text, alert_type="cobranca_diaria", base_dir=base_dir)


# ===== V10.107: COBRANÇAS FEITAS ATÉ O MOMENTO — 3H =====
def build_collection_progress_3h(base_dir, date_str=None):
    """Resumo LIVE por usuário, incluindo quem está zerado."""
    date_str = date_str or now_br().strftime("%Y-%m-%d")
    users = [u for u in _load_users(base_dir) if u.get("participa_cobrancas", True) and not u.get("is_gerente")]
    logs = [
        x for x in _load_cobrancas(base_dir)
        if isinstance(x, dict)
        and str(x.get("acao") or "whatsapp").lower() == "whatsapp"
        and _v1099_date(x.get("server_time") or x.get("criado_em") or x.get("data") or x.get("server_date")) == date_str
    ]

    rows = []
    for u in users:
        ent = {
            "login": str(u.get("login") or "").lower().strip(),
            "nome": str(u.get("nome") or u.get("login") or "").strip(),
            "filial": str(u.get("filial") or "").upper().strip(),
            "is_crediarista": bool(u.get("is_crediarista")),
            "is_terceiro": bool(u.get("is_terceiro")),
        }
        keys = set()
        for log in logs:
            if _v1099_entity_match(log, ent):
                k = _v1099_row_key(log)
                if k:
                    keys.add(k)
        rows.append({**ent, "cobrancas": len(keys)})

    rows.sort(key=lambda r: (str(r.get("filial") or "ZZZ"), str(r.get("nome") or r.get("login") or "").upper()))

    try:
        date_br = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        date_br = date_str

    total = sum(int(r.get("cobrancas") or 0) for r in rows)
    zeros = sum(1 for r in rows if int(r.get("cobrancas") or 0) == 0)

    lines = [f"⏱️ COBRANÇAS ATÉ O MOMENTO — {date_br}", f"🕒 {now_br().strftime('%H:%M')}", ""]
    last_filial = None
    for r in rows:
        filial = str(r.get("filial") or "SEM FILIAL")
        if filial != last_filial:
            if last_filial is not None:
                lines.append("")
            lines.append(f"🏬 {filial}")
            last_filial = filial
        nome = str(r.get("nome") or r.get("login") or "Usuário")
        qtd = int(r.get("cobrancas") or 0)
        palavra = "COBRANÇA" if qtd == 1 else "COBRANÇAS"
        lines.append(f"• {nome} = {qtd} {palavra}")

    lines += [
        "",
        f"📲 TOTAL ATÉ AGORA = {total} COBRANÇAS",
        f"⚠️ USUÁRIOS COM ZERO = {zeros}",
        "",
        "ℹ️ Contagem LIVE por CPF/título/parcela único registrado hoje.",
        f"🕒 Gerado em {now_br().strftime('%d/%m/%Y %H:%M:%S')}",
    ]
    return "\n".join(lines)

def send_collection_progress_3h_now(base_dir, date_str=None):
    text = build_collection_progress_3h(base_dir, date_str or now_br().strftime("%Y-%m-%d"))
    return telegram_send(text, alert_type="cobranca_3h", base_dir=base_dir)

# V10.107_TELEGRAM_COBRANCAS_3H

# V10.101_TELEGRAM_COBRANCA_DIARIA_LIVE
