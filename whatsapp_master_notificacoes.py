# VERSAO: WHATSAPP_MASTER_NOTIFICACOES_V10_80_COB_TERCEIRA
from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from telegram_monitor_mdl import (
    build_daily_summary,
    build_general_message_alert,
    build_meta_diaria_alert,
    build_meta_mercantil_100_alert,
    load_active_general_messages,
    load_meta_diaria_batidas,
    load_meta_mercantil_100,
    now_br,
    tail_file,
)

VERSION = "V10.80"
TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
PUBLIC_BASE = os.getenv("DASHBOARD_PUBLIC_BASE_URL", "https://moveisdolar.com.br/colaborador").rstrip("/")
WHATSAPP_BASE = os.getenv(
    "WHATSAPP_MASTER_BASE_URL",
    os.getenv("MDL_WHATSAPP_MASTER_BASE_URL", "https://mdl-whatsapp-ia-f1-piloto-production.up.railway.app"),
).rstrip("/")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_MASTER_INTERNAL_TOKEN", os.getenv("INTERNAL_API_TOKEN", "")).strip()
SEND_ENDPOINT = os.getenv("WHATSAPP_MASTER_SEND_ENDPOINT", "/api/internal/interacoes/enviar").strip() or "/api/internal/interacoes/enviar"
NOTIFY_ENABLED = os.getenv("WHATSAPP_MASTER_NOTIFICACOES_ENABLED", "1") != "0"
DEFAULT_PHONES = [
    re.sub(r"\D+", "", x)
    for x in os.getenv("WHATSAPP_MASTER_NOTIFICACOES_PHONES", "").split(",")
    if x.strip()
]

_CONFIG_CACHE: dict[str, Any] = {"ts": 0.0, "data": {}}


def _normalize_phone(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    if digits.startswith("55") and len(digits) in (12, 13):
        return digits
    if len(digits) in (10, 11):
        return "55" + digits
    return ""


def _read_json_file(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return default


def _url_json(url: str, default: Any, timeout: int = 20) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": f"MDL-WhatsNotify/{VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as exc:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        ssl_bad = "CERTIFICATE_VERIFY_FAILED" in str(exc).upper() or isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError)
        if host.endswith("moveisdolar.com.br") and ssl_bad:
            try:
                with urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context()) as r:
                    return json.loads(r.read().decode("utf-8", errors="replace"))
            except Exception:
                return default
        return default


def _global_config(base_dir: str | None = None, force: bool = False) -> dict[str, Any]:
    now = datetime.now(TZ).timestamp()
    if not force and _CONFIG_CACHE["data"] and now - float(_CONFIG_CACHE["ts"] or 0) < 30:
        return dict(_CONFIG_CACHE["data"])
    base = Path(base_dir or Path(__file__).resolve().parent)
    candidates = [
        base / "cache_historico" / "config_meta.json",
        base / "config_meta.json",
    ]
    payload = _url_json(f"{PUBLIC_BASE}/config_meta.json?_={int(now)}", {}, timeout=15)
    if not isinstance(payload, dict) or not payload:
        for p in candidates:
            payload = _read_json_file(p, {})
            if isinstance(payload, dict) and payload:
                break
    glob = payload.get("global") if isinstance(payload, dict) and isinstance(payload.get("global"), dict) else payload
    glob = glob if isinstance(glob, dict) else {}
    _CONFIG_CACHE.update({"ts": now, "data": glob})
    return dict(glob)


def _bool(v: Any, default: bool = True) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() not in {"0", "false", "nao", "não", "off", ""}


def _contacts(base_dir: str | None = None) -> list[dict[str, Any]]:
    cfg = _global_config(base_dir)
    raw = cfg.get("whatsapp_master_contacts") or cfg.get("whatsapp_notificacoes_contacts") or []
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for i, c in enumerate(raw):
            if not isinstance(c, dict):
                continue
            phone = _normalize_phone(c.get("telefone") or c.get("phone") or c.get("numero"))
            if not phone:
                continue
            out.append({
                "id": str(c.get("id") or f"wa_{i}"),
                "nome": str(c.get("nome") or c.get("name") or phone),
                "telefone": phone,
                "ativo": _bool(c.get("ativo"), True),
                "erros": _bool(c.get("erros"), True),
                "meta_diaria": _bool(c.get("meta_diaria"), True),
                "meta_mensal": _bool(c.get("meta_mensal"), True),
                "avisos": _bool(c.get("avisos"), True),
                "resumo": _bool(c.get("resumo"), True),
                "auditoria": _bool(c.get("auditoria"), True),
                "teste": True,
            })
    if not out:
        for i, p in enumerate(DEFAULT_PHONES):
            phone = _normalize_phone(p)
            if phone:
                out.append({"id": f"env_{i}", "nome": f"Diretoria {i+1}", "telefone": phone, "ativo": True, "erros": True, "meta_diaria": True, "meta_mensal": True, "avisos": True, "resumo": True, "auditoria": True, "teste": True})
    return out


def _contacts_for(alert_type: str, base_dir: str | None = None) -> list[dict[str, Any]]:
    key_map = {
        "daily_summary": "resumo",
        "resumo": "resumo",
        "meta_diaria": "meta_diaria",
        "meta_mensal": "meta_mensal",
        "avisos": "avisos",
        "auditoria": "auditoria",
        "erros": "erros",
        "teste": "teste",
    }
    key = key_map.get(str(alert_type or "").lower(), "avisos")
    return [c for c in _contacts(base_dir) if c.get("ativo") and _bool(c.get(key), True)]


def _send_one(text: str, phone: str, recipient_name: str = "Diretoria MDL", alert_type: str = "geral") -> tuple[bool, str]:
    if not NOTIFY_ENABLED:
        return False, "WHATSAPP_MASTER_NOTIFICACOES_ENABLED=0"
    if not WHATSAPP_TOKEN:
        return False, "WHATSAPP_MASTER_INTERNAL_TOKEN/INTERNAL_API_TOKEN não configurado"
    phone = _normalize_phone(phone)
    if not phone:
        return False, "telefone_invalido"
    payload = {
        "tipo": ("notificacao_" + re.sub(r"[^a-z0-9_]+", "_", str(alert_type).lower()))[:40],
        "filial": "F1",
        "usuario_login": "dashboard_notificacoes",
        "nome_perfil": "Lojas MDL",
        "cpf_cnpj": "",
        "cliente_nome": recipient_name[:180],
        "telefone": phone,
        "titulos": [],
        "mensagem": str(text or "")[:60000],
    }
    req = urllib.request.Request(
        WHATSAPP_BASE + SEND_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={"Authorization": "Bearer " + WHATSAPP_TOKEN, "Content-Type": "application/json; charset=utf-8", "User-Agent": f"MDL-WhatsNotify/{VERSION}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45, context=ssl._create_unverified_context()) as r:
            body = r.read().decode("utf-8", errors="replace")
            return 200 <= r.status < 300, body[:1400]
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8", errors="replace")[:1400]
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def whatsapp_send(text: str, alert_type: str = "geral", base_dir: str | None = None, phone: str | None = None) -> tuple[bool, str]:
    contacts = [{"nome": "Teste", "telefone": _normalize_phone(phone), "ativo": True}] if phone else _contacts_for(alert_type, base_dir)
    if not contacts:
        return False, "Nenhum telefone WhatsApp configurado para este tipo de aviso"
    ok_count = 0
    failures: list[str] = []
    for c in contacts:
        ok, resp = _send_one(text, str(c.get("telefone") or ""), str(c.get("nome") or "Diretoria MDL"), alert_type)
        if ok:
            ok_count += 1
        else:
            failures.append(f"{c.get('nome') or c.get('telefone')}: {resp}")
    if ok_count:
        return True, f"Enviado para {ok_count}/{len(contacts)} contato(s)" + (f"; falhas: {' | '.join(failures)[:900]}" if failures else "")
    return False, " | ".join(failures)[:1400]


def _audits(base_dir: str | None = None) -> list[dict[str, Any]]:
    payload = _url_json(f"{PUBLIC_BASE}/cobranca_auditoria_api.php?_={int(datetime.now(TZ).timestamp())}", {}, timeout=25)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    base = Path(base_dir or Path(__file__).resolve().parent)
    data = _read_json_file(base / "cobranca_auditoria.json", [])
    return data if isinstance(data, list) else []


def load_auditorias_master(base_dir: str | None = None) -> list[dict[str, Any]]:
    out = []
    for x in _audits(base_dir):
        st = str(x.get("status") or "").lower()
        fraud = _bool(x.get("fraude_suspeita"), False)
        if st in {"revisao_master", "recusado_ia", "recusado"} or (fraud and st not in {"aprovado_manual", "recusado_manual"}):
            out.append(x)
    return out


def build_audit_master_alert(item: dict[str, Any], base_dir: str | None = None) -> str:
    cfg = _global_config(base_dir)
    templates = cfg.get("whatsapp_master_templates") if isinstance(cfg.get("whatsapp_master_templates"), dict) else {}
    tpl = str(templates.get("auditoria_master") or "").strip()
    default = (
        "🧑‍⚖️ *NOVA EVIDÊNCIA PARA DECISÃO DO MASTER*\n\n"
        "Cliente: {cliente}\nCPF/CNPJ: {cpf}\nTítulo: {titulo} · Parcela: {parcela}\n"
        "Colaborador: {usuario} · {filial}\nFaixa: {faixa}\n"
        "Parecer da IA: {motivo}\n\n"
        "Abra o Dashboard → Cobranças → Auditoria IA / MASTER para aprovar ou recusar."
    )
    text = tpl or default
    values = {
        "cliente": str(item.get("cliente") or "Cliente não informado"),
        "cpf": str(item.get("cpf_cnpj") or "-"),
        "titulo": str(item.get("titulo") or "-"),
        "parcela": str(item.get("parcela") or "-"),
        "usuario": str(item.get("usuario_nome") or item.get("usuario_login") or "-"),
        "filial": str(item.get("filial") or "-"),
        "faixa": str(item.get("faixa") or "-"),
        "motivo": str(item.get("motivo") or "A IA solicitou revisão humana."),
        "id": str(item.get("id") or ""),
    }
    for k, v in values.items():
        text = text.replace("{" + k + "}", v)
    return text


def _day(s: Any) -> str:
    raw = str(s or "")
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else ""


def build_whatsapp_daily_summary(base_dir: str, date_str: str | None = None) -> str:
    date_str = date_str or datetime.now(TZ).strftime("%Y-%m-%d")
    base = build_daily_summary(base_dir, date_str)
    # Remove repetição consecutiva de versões antigas do resumo.
    clean_lines: list[str] = []
    for line in str(base or "").splitlines():
        if clean_lines and clean_lines[-1] == line:
            continue
        clean_lines.append(line)
    audits = _audits(base_dir)
    created = [x for x in audits if _day(x.get("server_time")) == date_str]
    approved_ia = [x for x in audits if str(x.get("status") or "").lower() == "aprovado_ia" and _day(x.get("ia_analisado_em") or x.get("updated_at")) == date_str]
    approved_master = [x for x in audits if str(x.get("status") or "").lower() == "aprovado_manual" and _day(x.get("master_decidido_em") or x.get("updated_at")) == date_str]
    rejected_master = [x for x in audits if str(x.get("status") or "").lower() == "recusado_manual" and _day(x.get("master_decidido_em") or x.get("updated_at")) == date_str]
    pending = load_auditorias_master(base_dir)
    by_faixa = {"grave": 0, "alerta": 0, "atencao": 0, "outro": 0}
    for x in created:
        fx = str(x.get("faixa") or "").lower()
        by_faixa[fx if fx in by_faixa else "outro"] += 1
    # V10.80: resumo COB é público somente em forma agregada; nenhuma PII da fila é publicada em JSON.
    cob_summary = _url_json(f"{PUBLIC_BASE}/cobranca_terceira_resumo.json?_={int(datetime.now(TZ).timestamp())}", {}, timeout=20)
    if not isinstance(cob_summary, dict) or str(cob_summary.get("date") or "") != date_str:
        cob_summary = {}
    cob_new_count = int(cob_summary.get("new_cpfs_today") or 0)
    cob_sent_count = int(cob_summary.get("sent_cpfs_today") or 0)
    cob_titles_sent = int(cob_summary.get("sent_titles_today") or 0)
    cob_value_new = float(cob_summary.get("new_value_today") or 0)
    cob_hold_count = int(cob_summary.get("hold_count") or 0)
    cob_error_count = int(cob_summary.get("error_count") or 0)

    clean_lines.extend([
        "",
        "💬 RESPOSTAS DE CLIENTES / AUDITORIA",
        f"• Cobranças com resposta e evidência enviada hoje: {len(created)}",
        f"• Por faixa: Grave {by_faixa['grave']} | Alerta {by_faixa['alerta']} | Atenção {by_faixa['atencao']}",
        f"• Aprovadas automaticamente pela IA hoje: {len(approved_ia)}",
        f"• Aprovadas pelo MASTER hoje: {len(approved_master)}",
        f"• Recusadas pelo MASTER hoje: {len(rejected_master)}",
        f"• Aguardando decisão do MASTER agora: {len(pending)}",
        "",
        "🤝 COBRANÇA TERCEIRA / COB",
        f"• Novos CPFs encaminhados hoje: {cob_new_count}",
        f"• CPFs baixados/enviados pela COB hoje: {cob_sent_count}",
        f"• Títulos enviados hoje: {cob_titles_sent}",
        f"• Valor novo encaminhado hoje: R$ {cob_value_new:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        f"• Em acordo/promessa temporária: {cob_hold_count}",
        f"• Pendências de atualização SGI/marcadores: {cob_error_count}",
    ])
    return "\n".join(clean_lines)


__all__ = [
    "VERSION", "whatsapp_send", "build_whatsapp_daily_summary", "load_auditorias_master", "build_audit_master_alert",
    "tail_file", "now_br", "load_active_general_messages", "build_general_message_alert", "load_meta_diaria_batidas",
    "build_meta_diaria_alert", "load_meta_mercantil_100", "build_meta_mercantil_100_alert",
]
