# VERSAO: WHATSAPP_MASTER_PREVENTIVA_V2_V10_49
# MDL COB+VENDAS -> WhatsApp Master
# Régua: D-5, D-1, D0, D+1, D+3, D+7, D+10, D+14.
# Segurança: qualquer título D+15 ou mais no mesmo CPF/CNPJ bloqueia o automático.

from __future__ import annotations

import ftplib
import json
import os
import re
import shutil
import ssl
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import pandas as pd
except Exception:
    pd = None

APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "monitor_logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / "whatsapp_master_preventiva.log"
PREVIEW_PATH = BASE_DIR / "whatsapp_master_preventiva_preview.json"
STATUS_PATH = BASE_DIR / "whatsapp_master_preventiva_status.json"
HISTORY_PATH = BASE_DIR / "whatsapp_master_preventiva_historico.json"
STATE_PATH = BASE_DIR / "whatsapp_master_preventiva_enviados.json"

PREVENTIVA_FIXED_PATH = BASE_DIR / "contas_receber_preventiva.xls"
HUMAN_FIXED_PATH = BASE_DIR / "contas_receber_principal.xls"

MARCOS = {-5: "D-5", -1: "D-1", 0: "D0", 1: "D+1", 3: "D+3", 7: "D+7", 10: "D+10", 14: "D+14"}

ENABLED = os.getenv("WHATSAPP_MASTER_PREVENTIVA_ENABLED", "0") == "1"
DRY_RUN = os.getenv("WHATSAPP_MASTER_PREVENTIVA_DRY_RUN", "1") != "0"
ONLY_PHONES = {
    re.sub(r"\D+", "", value)
    for value in os.getenv("WHATSAPP_MASTER_PREVENTIVA_ALLOWED_PHONES", "").split(",")
    if value.strip()
}
WHATSAPP_BASE = os.getenv(
    "WHATSAPP_MASTER_BASE_URL",
    os.getenv("MDL_WHATSAPP_MASTER_BASE_URL", "https://mdl-whatsapp-ia-f1-piloto-production.up.railway.app"),
).rstrip("/")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_MASTER_INTERNAL_TOKEN", os.getenv("INTERNAL_API_TOKEN", "")).strip()
SEND_ENDPOINT = os.getenv("WHATSAPP_MASTER_SEND_ENDPOINT", "/api/internal/interacoes/enviar")
MAX_AUDIT_ITEMS = max(100, int(os.getenv("WHATSAPP_MASTER_AUDIT_MAX", "1500")))


def now_br() -> datetime:
    return datetime.now(APP_TZ)


def hoje_br() -> date:
    return now_br().date()


def log(message: str) -> None:
    line = f"[{now_br().isoformat()}] {message}"
    print(line, flush=True)
    # O scheduler já redireciona stdout para este mesmo arquivo. Evita linhas duplicadas.
    if os.getenv("WHATSAPP_MASTER_STDOUT_CAPTURED", "0") == "1":
        return
    try:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except Exception:
        pass


def norm_key(value: Any) -> str:
    text = unicodedata.normalize("NFD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def pick_col(columns: list[Any], names: list[str]) -> Any | None:
    normalized = {norm_key(column): column for column in columns}
    for name in names:
        if name in normalized:
            return normalized[name]
    for normalized_name, original in normalized.items():
        if any(name in normalized_name for name in names):
            return original
    return None


def norm_doc(value: Any) -> str:
    digits = re.sub(r"\D+", "", str(value or ""))
    return digits if len(digits) in (11, 14) else ""


def extract_phones(value: Any) -> list[str]:
    raw = str(value or "")
    candidates = re.findall(r"\d[\d\s().+\-/]{8,}\d", raw)
    if not candidates and raw:
        candidates = re.split(r"[;,|/]", raw)
    output: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        digits = re.sub(r"\D+", "", candidate)
        if digits.startswith("55") and len(digits) in (12, 13):
            normalized = digits
        elif len(digits) in (10, 11):
            normalized = "55" + digits
        else:
            continue
        if normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def parse_money(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if not text or text.lower() == "nan":
        return 0.0
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        return 0.0


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except Exception:
            pass
    if pd is not None:
        try:
            parsed = pd.to_datetime(text, dayfirst=True, errors="coerce")
            if not pd.isna(parsed):
                return parsed.date()
        except Exception:
            pass
    return None


def _read_table_candidates(path: Path) -> list[Any]:
    if pd is None:
        raise RuntimeError("pandas não disponível no ambiente")
    tables: list[Any] = []
    suffix = path.suffix.lower()
    if suffix == ".csv":
        for sep in (None, ";", ",", "\t"):
            try:
                tables.append(pd.read_csv(path, dtype=str, sep=sep, engine="python"))
                break
            except Exception:
                continue
        return tables
    for kwargs in ({"dtype": str}, {"dtype": str, "header": None}):
        try:
            tables.append(pd.read_excel(path, **kwargs))
        except Exception:
            pass
    try:
        tables.extend(pd.read_html(path, decimal=",", thousands="."))
    except Exception:
        pass
    return tables


def _normalize_dataframe(df: Any) -> Any | None:
    required_groups = [
        ["cpf_cnpj", "cpfcnpj", "cpf", "cnpj", "documento"],
        ["cliente", "nome", "nome_cliente", "razao_social"],
        ["vencimento", "data_vencimento", "dt_vencimento", "vencto"],
    ]

    def has_required(columns: list[Any]) -> bool:
        return all(pick_col(columns, group) is not None for group in required_groups)

    if has_required(list(df.columns)):
        return df
    try:
        scan_limit = min(len(df), 30)
        for index in range(scan_limit):
            values = [str(value or "").strip() for value in list(df.iloc[index])]
            if has_required(values):
                normalized = df.iloc[index + 1 :].copy()
                normalized.columns = values
                normalized = normalized.dropna(how="all")
                return normalized
    except Exception:
        pass
    return None


def read_rows(path: Path) -> list[dict[str, Any]]:
    selected = None
    for table in _read_table_candidates(path):
        selected = _normalize_dataframe(table)
        if selected is not None:
            break
    if selected is None:
        raise RuntimeError(f"Não localizei cabeçalho válido em {path.name}")

    columns = list(selected.columns)
    c_doc = pick_col(columns, ["cpf_cnpj", "cpfcnpj", "cpf", "cnpj", "documento"])
    c_cliente = pick_col(columns, ["cliente", "nome", "nome_cliente", "razao_social"])
    c_tel = pick_col(columns, ["telefone", "celular", "fone", "whatsapp", "contato"])
    c_venc = pick_col(columns, ["vencimento", "data_vencimento", "dt_vencimento", "vencto"])
    c_valor = pick_col(columns, ["valor", "valor_titulo", "nominal", "valor_nominal", "pendente"])
    c_titulo = pick_col(columns, ["titulo", "numero_titulo", "documento_titulo", "duplicata", "lancamento", "lancto"])
    c_parcela = pick_col(columns, ["parcela", "prestacao", "nparcela"])
    c_filial = pick_col(columns, ["filial", "loja", "empresa"])

    rows: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        document = norm_doc(row.get(c_doc))
        vencimento = parse_date(row.get(c_venc))
        if not document or not vencimento:
            continue
        phones = extract_phones(row.get(c_tel)) if c_tel else []
        rows.append(
            {
                "cpf_cnpj": document,
                "cliente": str(row.get(c_cliente) or "").strip(),
                "telefone": phones[0] if phones else "",
                "telefones": phones,
                "vencimento": vencimento.isoformat(),
                "dias": (hoje_br() - vencimento).days,
                "valor": parse_money(row.get(c_valor)) if c_valor else 0.0,
                "titulo": str(row.get(c_titulo) or "").strip() if c_titulo else "",
                "parcela": str(row.get(c_parcela) or "").strip() if c_parcela else "",
                "filial": str(row.get(c_filial) or "").strip() if c_filial else "",
            }
        )
    return rows


def find_preventive_input() -> Path | None:
    configured = os.getenv("WHATSAPP_MASTER_PREVENTIVA_INPUT_FILE", "").strip()
    if configured and Path(configured).exists():
        return Path(configured)
    if PREVENTIVA_FIXED_PATH.exists():
        return PREVENTIVA_FIXED_PATH
    candidates: list[Path] = []
    for pattern in ("*preventiva*.xls*", "*preventiva*.csv"):
        candidates.extend(BASE_DIR.glob(pattern))
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def find_human_input() -> Path | None:
    configured = os.getenv("WHATSAPP_MASTER_HUMAN_INPUT_FILE", "").strip()
    if configured and Path(configured).exists():
        return Path(configured)
    if HUMAN_FIXED_PATH.exists():
        return HUMAN_FIXED_PATH
    candidates = [
        item
        for pattern in ("*contas*receber*.xls*", "*relatorio*contas*.xls*")
        for item in BASE_DIR.glob(pattern)
        if "preventiva" not in item.name.lower() and "quitados" not in item.name.lower()
    ]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def primeiro_nome(nome: Any) -> str:
    parts = re.sub(r"\s+", " ", str(nome or "").strip()).split(" ")
    return parts[0].title() if parts and parts[0] else "cliente"


def marco_label(dias: int) -> str | None:
    return MARCOS.get(int(dias))


def money_br(value: Any) -> str:
    text = f"R$ {float(value or 0):,.2f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def montar_msg(row: dict[str, Any]) -> str:
    dias = int(row["dias"])
    nome = primeiro_nome(row.get("cliente"))
    valor = money_br(row.get("valor")) if row.get("valor") else "o valor da parcela"
    vencimento = datetime.strptime(row["vencimento"], "%Y-%m-%d").strftime("%d/%m/%Y")
    if dias < 0:
        return f"Olá, {nome}! Passando para lembrar que você tem uma parcela da LOJAS MDL / Móveis do Lar com vencimento em {vencimento}. Valor: {valor}. Qualquer dúvida, responda esta mensagem."
    if dias == 0:
        return f"Olá, {nome}! Sua parcela da LOJAS MDL / Móveis do Lar vence hoje ({vencimento}). Valor: {valor}. Se já pagou, desconsidere."
    if dias <= 3:
        return f"Olá, {nome}! Identificamos uma parcela da LOJAS MDL / Móveis do Lar vencida desde {vencimento}. Valor: {valor}. Podemos ajudar você a regularizar?"
    if dias <= 10:
        return f"Olá, {nome}! Consta uma parcela em aberto na LOJAS MDL / Móveis do Lar vencida em {vencimento}. Valor: {valor}. Responda esta mensagem para receber atendimento."
    return f"Olá, {nome}! Este é um aviso da LOJAS MDL / Móveis do Lar sobre parcela em aberto vencida em {vencimento}. Valor: {valor}. Para evitar encaminhamento à cobrança humana, responda esta mensagem."


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json_atomic(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".novo")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def send_message(phone: str, text: str, reference: str) -> tuple[bool, str]:
    if not WHATSAPP_TOKEN:
        return False, "WHATSAPP_MASTER_INTERNAL_TOKEN/INTERNAL_API_TOKEN não configurado"
    payload = {
        "telefone": phone,
        "mensagem": text,
        "texto": text,
        "origem": "cobranca_preventiva_mdl",
        "referencia": reference,
        "session_route_id": os.getenv("WHATSAPP_MASTER_SESSION_ROUTE_ID", "mdl-master"),
    }
    request = urllib.request.Request(
        WHATSAPP_BASE + SEND_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
    )
    request.add_header("Authorization", "Bearer " + WHATSAPP_TOKEN)
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=35, context=ssl._create_unverified_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
            return 200 <= response.status < 300, body[:1200]
    except urllib.error.HTTPError as exc:
        return False, exc.read().decode("utf-8", errors="replace")[:1200]
    except Exception as exc:
        return False, str(exc)


def check_service() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "status": "Não confirmado",
        "base_url": WHATSAPP_BASE,
        "session_route_id": os.getenv("WHATSAPP_MASTER_SESSION_ROUTE_ID", "mdl-master"),
    }
    try:
        request = urllib.request.Request(WHATSAPP_BASE + "/health", headers={"User-Agent": "MDL-COB-VENDAS/10.48"})
        with urllib.request.urlopen(request, timeout=15, context=ssl._create_unverified_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body.strip().startswith(("{", "[")) else {"raw": body[:500]}
            result["ok"] = 200 <= response.status < 300 and bool(parsed.get("ok", True))
            result["status"] = str(parsed.get("session_status") or parsed.get("status") or ("Disponível" if result["ok"] else "Indisponível"))
            result["app"] = parsed.get("app")
            result["version"] = parsed.get("version")
            result["session_status"] = parsed.get("session_status") or parsed.get("openwa_status")
    except Exception as exc:
        result["erro"] = str(exc)
    return result


def ftp_publish(path: Path, remote_name: str) -> bool:
    if os.getenv("WHATSAPP_MASTER_FTP_PUBLISH", "1") == "0" or not path.exists():
        return False
    host = os.getenv("FTP_HOST", "").strip()
    user = os.getenv("FTP_USER", "").strip()
    password = os.getenv("FTP_PASS", "").strip()
    remote_dir = os.getenv("FTP_DIR", "/public_html/colaborador").strip()
    if not host or not user or not password:
        log("ℹ️ FTP do worker não configurado; status seguirá disponível pelo monitor Railway e será publicado pelo MAIN.")
        return False
    ftp = None
    temp_name = ".tmp_" + remote_name
    try:
        ftp = ftplib.FTP()
        ftp.connect(host, 21, timeout=35)
        ftp.login(user, password)
        ftp.cwd(remote_dir)
        try:
            ftp.delete(temp_name)
        except Exception:
            pass
        with path.open("rb") as handle:
            ftp.storbinary(f"STOR {temp_name}", handle, blocksize=65536)
        try:
            ftp.rename(temp_name, remote_name)
        except Exception:
            try:
                ftp.delete(remote_name)
            except Exception:
                pass
            ftp.rename(temp_name, remote_name)
        return True
    except Exception as exc:
        log(f"⚠️ FTP status {remote_name}: {exc}")
        return False
    finally:
        try:
            if ftp:
                ftp.quit()
        except Exception:
            pass


def publish_status_files() -> None:
    for path in (STATUS_PATH, PREVIEW_PATH, HISTORY_PATH):
        ftp_publish(path, path.name)


def append_history(run: dict[str, Any]) -> None:
    history = load_json(HISTORY_PATH, {"version": "V10.49", "runs": []})
    runs = history.setdefault("runs", [])
    compact = {
        key: run.get(key)
        for key in (
            "run_id",
            "gerado_em",
            "arquivo",
            "enabled",
            "dry_run",
            "total_linhas_lidas",
            "total_cpfs",
            "cpfs_bloqueados_d15_mais",
            "candidatos",
            "enviados_agora",
            "pulados",
            "erros",
            "por_marco",
            "por_motivo",
        )
    }
    compact["auditoria"] = (run.get("auditoria") or [])[:500]
    runs.append(compact)
    history["runs"] = runs[-90:]
    history["updated_at"] = now_br().isoformat()
    save_json_atomic(HISTORY_PATH, history)


def error_status(message: str) -> dict[str, Any]:
    output = {
        "ok": False,
        "version": "V10.49",
        "erro": message,
        "gerado_em": now_br().isoformat(),
        "enabled": ENABLED,
        "dry_run": DRY_RUN,
        "marcos": list(MARCOS.values()),
        "service": check_service(),
        "preview": [],
        "skipped": [],
        "errors": [],
        "auditoria": [],
    }
    save_json_atomic(PREVIEW_PATH, output)
    save_json_atomic(STATUS_PATH, output)
    publish_status_files()
    return output


def main() -> int:
    run_id = now_br().strftime("%Y%m%d-%H%M%S")
    log("🚀 Iniciando WhatsApp Master Preventiva/Cobrança V10.49")
    log(f"Config: ENABLED={ENABLED} DRY_RUN={DRY_RUN} MARCOS={list(MARCOS.values())}")

    preventive_path = find_preventive_input()
    if not preventive_path:
        message = "Relatório preventivo D-5 até D+14 não encontrado. Rode primeiro Cobrança/Main para gerar contas_receber_preventiva.xls."
        error_status(message)
        log("⚠️ " + message)
        return 0

    try:
        preventive_rows = read_rows(preventive_path)
    except Exception as exc:
        message = f"Falha lendo relatório preventivo {preventive_path.name}: {exc}"
        error_status(message)
        log("❌ " + message)
        return 2

    human_path = find_human_input()
    human_rows: list[dict[str, Any]] = []
    if human_path:
        try:
            human_rows = read_rows(human_path)
        except Exception as exc:
            log(f"⚠️ Não consegui ler base humana para bloqueio D+15: {exc}")

    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in preventive_rows:
        by_doc[row["cpf_cnpj"]].append(row)

    blocked_docs = {
        row["cpf_cnpj"]
        for row in human_rows
        if row.get("cpf_cnpj") and int(row.get("dias") or 0) >= 15
    }
    blocked_docs.update(
        document
        for document, rows in by_doc.items()
        if any(int(row.get("dias") or 0) >= 15 for row in rows)
    )

    state = load_json(STATE_PATH, {"sent": {}})
    sent_state = state.setdefault("sent", {})
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    sent_now: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []

    for row in preventive_rows:
        days = int(row["dias"])
        mark = marco_label(days)
        if not mark:
            continue
        key = "|".join([row["cpf_cnpj"], row.get("titulo", ""), row.get("parcela", ""), row["vencimento"], mark])
        base = {**row, "marco": mark, "dedupe_key": key}
        if row["cpf_cnpj"] in blocked_docs:
            item = {**base, "status": "ignorado", "motivo": "bloqueado_d15_ou_mais_no_cpf"}
            skipped.append(item)
            audit.append(item)
            continue
        if key in sent_state:
            item = {**base, "status": "ignorado", "motivo": "ja_enviado"}
            skipped.append(item)
            audit.append(item)
            continue
        if not row.get("telefone"):
            item = {**base, "status": "ignorado", "motivo": "sem_telefone"}
            skipped.append(item)
            audit.append(item)
            continue
        if ONLY_PHONES and row["telefone"] not in ONLY_PHONES:
            item = {**base, "status": "ignorado", "motivo": "fora_piloto_allowed_phones"}
            skipped.append(item)
            audit.append(item)
            continue

        candidate = {**base, "mensagem": montar_msg(row), "status": "simulado" if DRY_RUN or not ENABLED else "candidato"}
        candidates.append(candidate)
        if ENABLED and not DRY_RUN:
            ok, response = send_message(row["telefone"], candidate["mensagem"], key)
            if ok:
                sent_item = {**candidate, "status": "enviado", "resposta": response[:500]}
                sent_state[key] = {
                    "quando": now_br().isoformat(),
                    "telefone": row["telefone"],
                    "marco": mark,
                    "resposta": response[:500],
                }
                sent_now.append(sent_item)
                audit.append(sent_item)
                time.sleep(float(os.getenv("WHATSAPP_MASTER_PREVENTIVA_SEND_GAP_SECONDS", "2")))
            else:
                error_item = {**candidate, "status": "erro", "erro": response}
                errors.append(error_item)
                audit.append(error_item)
        else:
            audit.append(candidate)

    save_json_atomic(STATE_PATH, state)

    mark_summary: dict[str, dict[str, int]] = {}
    for mark in MARCOS.values():
        mark_summary[mark] = {
            "candidatos": sum(1 for item in candidates if item.get("marco") == mark),
            "enviados": sum(1 for item in sent_now if item.get("marco") == mark),
            "ignorados": sum(1 for item in skipped if item.get("marco") == mark),
            "erros": sum(1 for item in errors if item.get("marco") == mark),
        }
    reason_summary = dict(Counter(item.get("motivo") or "sem_motivo" for item in skipped))
    service = check_service()

    output = {
        "ok": not errors,
        "version": "V10.49",
        "run_id": run_id,
        "gerado_em": now_br().isoformat(),
        "arquivo": preventive_path.name,
        "arquivo_humano_bloqueio": human_path.name if human_path else "",
        "enabled": ENABLED,
        "dry_run": DRY_RUN,
        "marcos": list(MARCOS.values()),
        "service": service,
        "total_linhas_lidas": len(preventive_rows),
        "total_linhas_base_humana": len(human_rows),
        "total_cpfs": len(by_doc),
        "cpfs_bloqueados_d15_mais": len(blocked_docs),
        "candidatos": len(candidates),
        "simulados": len(candidates) if DRY_RUN or not ENABLED else 0,
        "enviados_agora": len(sent_now),
        "pulados": len(skipped),
        "erros": len(errors),
        "por_marco": mark_summary,
        "por_motivo": reason_summary,
        "preview": candidates[:MAX_AUDIT_ITEMS],
        "enviados_detalhes": sent_now[:MAX_AUDIT_ITEMS],
        "skipped": skipped[:MAX_AUDIT_ITEMS],
        "skipped_amostra": skipped[:300],
        "errors": errors[:500],
        "auditoria": audit[:MAX_AUDIT_ITEMS],
    }

    save_json_atomic(PREVIEW_PATH, output)
    save_json_atomic(STATUS_PATH, output)
    append_history(output)
    publish_status_files()
    log(
        "✅ Finalizado | "
        f"candidatos={len(candidates)} simulados={output['simulados']} enviados={len(sent_now)} "
        f"pulados={len(skipped)} erros={len(errors)} bloqueados_D15={len(blocked_docs)}"
    )
    return 0 if not errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
