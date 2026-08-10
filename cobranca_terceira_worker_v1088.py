# -*- coding: utf-8 -*-
# VERSAO: COBRANCA_EXTERNA_V10_88_TESTE30_NOTIFICACAO
"""
Lojas MDL - Cobrança Terceira (COB)

Regra operacional:
- quando qualquer título de um CPF/CNPJ alcançar D+91, o documento inteiro passa
  para a fila externa, salvo pagamento/acordo recente ou marcador bloqueado;
- a exportação segue exatamente o modelo CSV recebido da COB;
- o nome no SGI é alterado para "(COB)" somente quando DRY_RUN=0;
- a fila completa fica protegida em PHP no /colaborador; somente hashes e resumo agregado ficam públicos.

Segurança de implantação: COB_TERCEIRA_DRY_RUN=1 por padrão.
"""
from __future__ import annotations

import ast
import csv
import ftplib
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    import pandas as pd
except Exception:
    pd = None

try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait, Select
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
except Exception as exc:
    raise RuntimeError(f"Selenium não disponível: {exc}")

VERSION = "V10.88"
TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))
BASE_DIR = Path(__file__).resolve().parent
PUBLIC_BASE = os.getenv("COB_TERCEIRA_PUBLIC_BASE", "https://moveisdolar.com.br/colaborador").rstrip("/")
STATE_PATH = BASE_DIR / "cobranca_terceira_fila.json"
PREVIEW_PATH = BASE_DIR / "cobranca_terceira_preview.json"
PRIVATE_STATE_PATH = BASE_DIR / "cobranca_terceira_fila_privada.php"
PRIVATE_PREVIEW_PATH = BASE_DIR / "cobranca_terceira_preview_privado.php"
BLOCKLIST_PATH = BASE_DIR / "cobranca_terceira_bloqueios.json"
SUMMARY_PATH = BASE_DIR / "cobranca_terceira_resumo.json"
CSV_PATH = BASE_DIR / "cobranca_terceira_modelo_atual.csv"
TRIGGER_XLS_PATH = BASE_DIR / "cobranca_terceira_91_97.xls"
MAIN_SOURCE = BASE_DIR / "dashboard_railway_main_headless.py"
MAIN_FIXED = BASE_DIR / "contas_receber_principal.xls"
PREVENTIVA_FIXED = BASE_DIR / "contas_receber_preventiva.xls"
QUITADOS_JSON = BASE_DIR / "quitados_180d_contas_receber.json"
AUDIT_API = os.getenv("COBRANCA_AUDITORIA_API_URL", PUBLIC_BASE + "/cobranca_auditoria_api.php")
ENABLED = os.getenv("COB_TERCEIRA_ENABLED", "1") == "1"
DRY_RUN = os.getenv("COB_TERCEIRA_DRY_RUN", "1") != "0"
DRY_RUN_FAST = str(os.getenv("COB_TERCEIRA_DRY_RUN_FAST", "1")).strip().lower() not in {"0","false","nao","não","off"}
PROGRESS_EVERY = max(1, int(os.getenv("COB_TERCEIRA_PROGRESS_EVERY", "10") or "10"))
TEST_MODE = str(os.getenv("COB_TERCEIRA_TEST_MODE", "0")).strip().lower() not in {"0","false","nao","não","off",""}
TEST_LIMIT = max(1, min(500, int(os.getenv("COB_TERCEIRA_TEST_LIMIT", "30") or "30")))
DIAS = max(91, int(os.getenv("COB_TERCEIRA_DIAS", "91")))
JANELA = max(1, min(30, int(os.getenv("COB_TERCEIRA_JANELA_CAPTURA_DIAS", "7"))))
HOLD_DIAS = max(1, min(45, int(os.getenv("COB_TERCEIRA_HOLD_ACORDO_DIAS", "7"))))
BOOTSTRAP = os.getenv("COB_TERCEIRA_BOOTSTRAP", "0") == "1"
OBS_FINAL = (os.getenv("COB_TERCEIRA_OBS", "(COB)").strip() or "(COB)")
ACTIVE_STATUSES = {"pronto", "enviado"}
MODEL_HEADER = [
    "COD_DEVEDOR", "NOME", "CNPJ_CPF", "FONE 1", "FONE 2", "FONE 3", "EMAIL",
    "ENDERECO", "NUMERO", "COMPLEMENTO", "BAIRRO", "CIDADE", "ESTADO", "CEP",
    "DADOS_ADICIONAIS", "COD_TITULO", "PARCELA", "CONTRATO", "DT_VENCIMENTO", " VL_TITULO ",
]


def now_br() -> datetime:
    return datetime.now(TZ)


def log(msg: str) -> None:
    print(f"[{now_br().isoformat()}] {msg}", flush=True)


def norm_doc(v: Any) -> str:
    d = re.sub(r"\D+", "", str(v or ""))
    return d if len(d) in (11, 14) else ""


def norm_text(v: Any) -> str:
    s = unicodedata.normalize("NFKD", str(v or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", s)).strip()


def parse_money(v: Any) -> float:
    if v is None:
        return 0.0
    s = str(v).strip().replace("R$", "").replace(" ", "")
    if not s or s.lower() in {"nan", "none"}:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except Exception:
        return 0.0


def parse_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except Exception:
            pass
    if pd is not None:
        try:
            x = pd.to_datetime(s, dayfirst=True, errors="coerce")
            if not pd.isna(x):
                return x.date()
        except Exception:
            pass
    return None


def fmt_date_br(v: Any) -> str:
    d = parse_date(v)
    return d.strftime("%d/%m/%Y") if d else str(v or "").strip()


def fmt_money_csv(v: Any) -> str:
    return f"{float(v or 0):.2f}".replace(".", ",")


def save_json_atomic(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _urlopen(req: urllib.request.Request, timeout: int = 30):
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())
    except Exception as exc:
        host = (urllib.parse.urlparse(getattr(req, "full_url", str(req))).hostname or "").lower()
        ssl_bad = "CERTIFICATE_VERIFY_FAILED" in str(exc).upper() or isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError)
        if host.endswith("moveisdolar.com.br") and ssl_bad:
            return urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context())
        raise


def url_json(url: str, default: Any, timeout: int = 30) -> Any:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"MDL-CobTerceira/{VERSION}"})
        with _urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception:
        return default


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def source_constants(path: Path) -> dict[str, Any]:
    """Lê somente constantes literais do main sem importá-lo/executá-lo."""
    out: dict[str, Any] = {}
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                value = node.value
                if not isinstance(value, ast.Constant):
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        out[target.id] = value.value
    except Exception:
        pass
    return out


def credentials() -> tuple[str, str, str]:
    c = source_constants(MAIN_SOURCE)
    url = os.getenv("SGI_URL", os.getenv("URL_SGI", str(c.get("URL") or "https://smart.sgisistemas.com.br"))).rstrip("/")
    user = os.getenv("SGI_USUARIO", os.getenv("SGI_LOGIN", str(c.get("LOGIN") or ""))).strip()
    pwd = os.getenv("SGI_SENHA", str(c.get("SENHA") or "")).strip()
    if not user or not pwd:
        raise RuntimeError("SGI_USUARIO/SGI_SENHA ausentes e não foi possível reaproveitar as constantes do dashboard.")
    return url, user, pwd


def ftp_config() -> dict[str, Any]:
    c = source_constants(MAIN_SOURCE)
    host = os.getenv("FTP_HOST", str(c.get("FTP_HOST") or "moveisdolar.com.br")).strip()
    user = os.getenv("FTP_USER", str(c.get("FTP_USER") or "")).strip()
    pwd = os.getenv("FTP_PASS", str(c.get("FTP_PASS") or "")).strip()
    root = os.getenv("FTP_COLABORADOR_DIR", str(c.get("FTP_DIR") or "/public_html/colaborador")).strip()
    return {"host": host, "user": user, "pwd": pwd, "dir": root, "port": int(os.getenv("FTP_PORT", "21"))}


def ftp_upload(path: Path, remote_name: str) -> bool:
    cfg = ftp_config()
    if not (cfg["host"] and cfg["user"] and cfg["pwd"]):
        log(f"⚠️ FTP sem configuração; {remote_name} ficará somente local.")
        return False
    ftp = None
    tmp_name = ".tmp_" + remote_name
    try:
        ftp = ftplib.FTP()
        ftp.connect(cfg["host"], cfg["port"], timeout=35)
        ftp.login(cfg["user"], cfg["pwd"])
        ftp.encoding = "utf-8"
        ftp.set_pasv(True)
        ftp.cwd(cfg["dir"])
        try:
            ftp.delete(tmp_name)
        except Exception:
            pass
        with path.open("rb") as fh:
            ftp.storbinary("STOR " + tmp_name, fh, blocksize=65536)
        try:
            ftp.rename(tmp_name, remote_name)
        except Exception:
            try:
                ftp.delete(remote_name)
            except Exception:
                pass
            ftp.rename(tmp_name, remote_name)
        return True
    except Exception as exc:
        log(f"⚠️ FTP falhou em {remote_name}: {exc}")
        return False
    finally:
        try:
            if ftp:
                ftp.quit()
        except Exception:
            pass


PRIVATE_PREFIX = "<?php http_response_code(404); exit; ?>\n"


def doc_hash(doc: str) -> str:
    d = norm_doc(doc)
    return hashlib.sha256(d.encode("utf-8")).hexdigest() if d else ""


def protected_payload(data: Any) -> bytes:
    return (PRIVATE_PREFIX + json.dumps(data, ensure_ascii=False, indent=2)).encode("utf-8")


def parse_protected_payload(raw: bytes | str, default: Any) -> Any:
    try:
        txt = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw or "")
        if txt.startswith("<?php"):
            txt = txt.split("\n", 1)[1] if "\n" in txt else ""
        data = json.loads(txt)
        return data
    except Exception:
        return default


def ftp_read_private(remote_name: str, default: Any) -> Any:
    cfg = ftp_config(); ftp = None
    if not (cfg["host"] and cfg["user"] and cfg["pwd"]):
        return default
    try:
        ftp = ftplib.FTP(); ftp.connect(cfg["host"], cfg["port"], timeout=35); ftp.login(cfg["user"], cfg["pwd"])
        ftp.encoding = "utf-8"; ftp.set_pasv(True); ftp.cwd(cfg["dir"])
        buf = io.BytesIO(); ftp.retrbinary("RETR " + remote_name, buf.write)
        return parse_protected_payload(buf.getvalue(), default)
    except Exception:
        return default
    finally:
        try:
            if ftp: ftp.quit()
        except Exception:
            pass


def ftp_upload_bytes(data: bytes, remote_name: str) -> bool:
    cfg = ftp_config(); ftp = None; tmp_name = ".tmp_" + remote_name
    if not (cfg["host"] and cfg["user"] and cfg["pwd"]):
        log(f"⚠️ FTP sem configuração; {remote_name} ficará somente local."); return False
    try:
        ftp = ftplib.FTP(); ftp.connect(cfg["host"], cfg["port"], timeout=35); ftp.login(cfg["user"], cfg["pwd"])
        ftp.encoding = "utf-8"; ftp.set_pasv(True); ftp.cwd(cfg["dir"])
        try: ftp.delete(tmp_name)
        except Exception: pass
        ftp.storbinary("STOR " + tmp_name, io.BytesIO(data), blocksize=65536)
        try: ftp.rename(tmp_name, remote_name)
        except Exception:
            try: ftp.delete(remote_name)
            except Exception: pass
            ftp.rename(tmp_name, remote_name)
        return True
    except Exception as exc:
        log(f"⚠️ FTP falhou em {remote_name}: {exc}"); return False
    finally:
        try:
            if ftp: ftp.quit()
        except Exception: pass


def load_remote_state() -> dict[str, Any]:
    remote = ftp_read_private("cobranca_terceira_fila_privada.php", {})
    if isinstance(remote, dict) and isinstance(remote.get("items"), list):
        return remote
    local = read_json(STATE_PATH, {})
    if isinstance(local, dict) and isinstance(local.get("items"), list):
        return local
    return {"version": VERSION, "updated_at": "", "items": [], "batches": []}


def item_id(doc: str) -> str:
    return "COB-" + doc


def merge_download_status(new_state: dict[str, Any]) -> dict[str, Any]:
    """Antes de subir, reaplica downloads que podem ter ocorrido durante a execução."""
    remote = ftp_read_private("cobranca_terceira_fila_privada.php", {})
    if not isinstance(remote, dict):
        return new_state
    rmap = {str(x.get("id") or ""): x for x in (remote.get("items") or []) if isinstance(x, dict)}
    for item in new_state.get("items") or []:
        old = rmap.get(str(item.get("id") or ""))
        if not old:
            continue
        if str(old.get("status") or "").lower() == "enviado":
            for key in ("status", "sent_at", "downloaded_by", "batch_id", "last_download_at", "downloads"):
                if key in old:
                    item[key] = old[key]
    if isinstance(remote.get("batches"), list):
        existing = {str(x.get("batch_id") or "") for x in (new_state.get("batches") or [])}
        for b in remote["batches"]:
            if str(b.get("batch_id") or "") not in existing:
                new_state.setdefault("batches", []).append(b)
    return new_state


def normalize_marker_name(name: str) -> str:
    return norm_text(name)


def blocked_marker(name: str) -> str:
    n = normalize_marker_name(name)
    for marker in ("ADV2", "ADV", "OBT", "CURTY"):
        if re.search(rf"(^| )\*?{marker}\*?( |$)", n):
            return marker
    return ""


def has_cob_marker(name: str) -> bool:
    n = normalize_marker_name(name)
    return bool(re.search(r"(^| )COB( |$)", n))


def clean_customer_name_for_cob(name: str) -> str:
    s = re.sub(r"\s+", " ", str(name or "").strip())
    s = re.sub(r"\s*\(\s*INATIVO\s*\)\s*$", "", s, flags=re.I)
    s = re.sub(r"\s*\((?:COB|SPC|MEL|COBRANCA|FALECIDO|PROTESTADO)\)\s*$", "", s, flags=re.I)
    s = re.split(r"\*", s, maxsplit=1)[0].strip()
    s = re.sub(r"\b(?:SPC|MEL|FALECIDO|PROTESTADO)\b\s*$", "", s, flags=re.I).strip(" -*")
    s = re.sub(r"\s+", " ", s).strip()
    return f"{s} {OBS_FINAL}".strip()


def chrome_driver(download_dir: Path):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--lang=pt-BR")
    opts.add_argument("--disable-notifications")
    opts.add_experimental_option("prefs", {"download.default_directory": str(download_dir), "download.prompt_for_download": False, "safebrowsing.enabled": True})
    binary = os.getenv("CHROME_BINARY") or os.getenv("CHROMIUM_BINARY")
    if not binary:
        for p in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
            if os.path.exists(p):
                binary = p
                break
    if binary:
        opts.binary_location = binary
    driver_path = os.getenv("CHROMEDRIVER_PATH") or shutil.which("chromedriver")
    drv = webdriver.Chrome(service=Service(driver_path) if driver_path else Service(), options=opts)
    try:
        drv.execute_cdp_cmd("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(download_dir)})
    except Exception:
        pass
    return drv


def login_sgi(driver, url: str, user: str, pwd: str) -> None:
    wait = WebDriverWait(driver, 25)
    driver.get(url + "/login")
    try:
        u = wait.until(EC.presence_of_element_located((By.NAME, "usuario")))
    except Exception:
        u = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']")))
    u.clear(); u.send_keys(user)
    p = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    p.clear(); p.send_keys(pwd); p.send_keys(Keys.ENTER)
    time.sleep(2.5)
    try:
        b = WebDriverWait(driver, 6).until(EC.element_to_be_clickable((By.ID, "botao_prosseguir_informa_local_trabalho")))
        driver.execute_script("arguments[0].click();", b)
        time.sleep(2)
    except Exception:
        pass


def click_xpath(driver, xpath: str, timeout: int = 20):
    el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, xpath)))
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    return el


def set_input(driver, input_id: str, value: str):
    el = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.ID, input_id)))
    driver.execute_script("arguments[0].removeAttribute('readonly');arguments[0].removeAttribute('disabled');arguments[0].value='';", el)
    if value:
        el.send_keys(value)
    driver.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}));arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));", el)


def mark_multiselect_values(driver, label_text: str, values: list[str]) -> None:
    click_xpath(driver, f"//label[contains(normalize-space(.),'{label_text}')]/following::button[1]")
    ul = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, f"//label[contains(normalize-space(.),'{label_text}')]/following::ul[1]")))
    wanted = {str(x) for x in values}
    for c in ul.find_elements(By.XPATH, ".//input[@type='checkbox']"):
        if c.is_selected():
            driver.execute_script("arguments[0].click();", c)
    for c in ul.find_elements(By.XPATH, ".//input[@type='checkbox']"):
        if str(c.get_attribute("value") or "") in wanted and not c.is_selected():
            driver.execute_script("arguments[0].click();", c)
    driver.execute_script("document.body.click();")


def ensure_report_columns(driver, labels: list[str]) -> None:
    label = None
    for xp in ("//label[@id='titulo_campo_colunas_relatorio']", "//label[contains(normalize-space(.),'Colunas do Relatório')]", "//label[contains(normalize-space(.),'Colunas do Relatorio')]"):
        try:
            label = WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.XPATH, xp)))
            break
        except Exception:
            pass
    if label is None:
        return
    button = label.find_element(By.XPATH, "following::button[1]")
    driver.execute_script("arguments[0].click();", button); time.sleep(.5)
    ul = label.find_element(By.XPATH, "following::ul[1]")
    wanted = {norm_text(x) for x in labels}
    for c in ul.find_elements(By.XPATH, ".//input[@type='checkbox']"):
        txt = ""
        try:
            txt = c.find_element(By.XPATH, "ancestor::label[1]").text
        except Exception:
            pass
        val = str(c.get_attribute("value") or "")
        n = norm_text(txt + " " + val.replace("_", " "))
        if any(w in n for w in wanted) and not c.is_selected():
            driver.execute_script("arguments[0].click();", c)
    driver.execute_script("document.body.click();")


def valid_report_file(p: Path) -> bool:
    n = p.name.lower()
    return p.is_file() and (n.endswith(".xls") or n.endswith(".xlsx")) and any(k in n for k in ("relatorio_contas", "contas_pagar_receber", "contas_receber"))


def generate_trigger_report(driver, url: str, download_dir: Path) -> Path:
    today = now_br().date()
    start_days = DIAS + JANELA - 1
    d_ini = (today - timedelta(days=start_days)).strftime("%d/%m/%Y")
    d_fim = (today - timedelta(days=DIAS)).strftime("%d/%m/%Y")
    log(f"🧾 SGI: capturando vencimentos {d_ini} até {d_fim} (D+{DIAS}..D+{start_days}).")
    driver.get(url + "/relatorio_contas_receber")
    wait = WebDriverWait(driver, 25)
    wait.until(EC.presence_of_element_located((By.ID, "data_vencimento_inicial")))
    Select(driver.find_element(By.ID, "data_vencimento")).select_by_value("intervalo")
    set_input(driver, "data_vencimento_inicial", d_ini)
    set_input(driver, "data_vencimento_final", d_fim)
    try:
        click_xpath(driver, "//label[contains(text(),'Filiais')]/following::button[1]")
        ul = driver.find_element(By.XPATH, "//label[contains(text(),'Filiais')]/following::ul[1]")
        wanted = {"1", "2", "3", "4", "5", "6", "7", "8", "10"}
        for c in ul.find_elements(By.XPATH, ".//input[@type='checkbox']"):
            val = str(c.get_attribute("value") or "")
            if val in wanted and not c.is_selected():
                driver.execute_script("arguments[0].click();", c)
        driver.execute_script("document.body.click();")
    except Exception as exc:
        log(f"⚠️ Filiais: {exc}")
    try:
        click_xpath(driver, "//span[contains(@class,'glyphicon-plus')]")
    except Exception:
        pass
    ensure_report_columns(driver, ["CPF/CNPJ", "Contato", "Observações", "Avalistas"])
    try:
        mark_multiselect_values(driver, "Forma de Pagamento", ["3", "47", "17"])
    except Exception as exc:
        log(f"⚠️ Formas de pagamento: {exc}")
    try:
        Select(wait.until(EC.presence_of_element_located((By.ID, "_formato")))).select_by_value("xls")
    except Exception:
        pass
    before = {p.name for p in download_dir.iterdir() if valid_report_file(p)}
    click_xpath(driver, "//*[@id='gerar']")
    found = None
    for _ in range(120):
        time.sleep(1.5)
        if any(p.suffix.lower() in {".crdownload", ".tmp"} for p in download_dir.iterdir()):
            continue
        new = [p for p in download_dir.iterdir() if valid_report_file(p) and p.name not in before]
        if new:
            found = max(new, key=lambda p: p.stat().st_mtime)
            break
    if not found:
        raise RuntimeError("XLS D+91 não foi baixado pelo SGI")
    shutil.copy2(found, TRIGGER_XLS_PATH)
    return TRIGGER_XLS_PATH


def norm_col(v: Any) -> str:
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", s.lower())).strip("_")


def read_report_df(path: Path):
    if pd is None:
        raise RuntimeError("pandas indisponível")
    candidates = []
    for engine in ("openpyxl", None):
        for kwargs in ({"header": None, "dtype": str}, {"dtype": str}):
            try:
                use = dict(kwargs)
                if engine:
                    use["engine"] = engine
                candidates.append(pd.read_excel(path, **use))
            except Exception:
                pass
    try:
        candidates.extend(pd.read_html(path))
    except Exception:
        pass
    if not candidates:
        raise RuntimeError(f"Não foi possível ler {path.name}")
    return max(candidates, key=lambda d: len(d) * max(1, len(d.columns)))


def _header_match_v1084(key: str, normalized_header: str, aliases: list[str]) -> bool:
    """Reconhecimento robusto do XLS atual do SGI.

    Evita especialmente confundir "Forma de Pagamento" com a coluna "Pagamento".
    """
    n = str(normalized_header or "").strip("_")
    if not n:
        return False

    if key == "pagamento":
        # Não aceita forma_de_pagamento como data/campo pagamento.
        if "forma" in n:
            return False
        return n in {"pagamento", "data_pagamento", "dt_pagamento"} or n.startswith("data_pagamento")

    if key == "forma":
        return n in {"forma_de_pagamento", "forma_pagamento"} or (
            "forma" in n and "pagamento" in n
        )

    if key == "titulo":
        return n in {"titulo", "n_titulo", "no_titulo", "numero_titulo"} or n.endswith("_titulo")

    if key == "parcela":
        return n in {"parcela", "n_parcela", "no_parcela", "numero_parcela"} or n.endswith("_parcela")

    if key == "lancamento":
        return n in {"lancamento", "n_lancamento", "no_lancamento", "numero_lancamento"} or n.endswith("_lancamento")

    return any(a == n or (len(a) >= 4 and a in n) for a in aliases)


def _complete_current_sgi_layout_v1084(mp: dict[str, int], ncols: int) -> dict[str, int]:
    """Completa campos pelo layout confirmado do relatório de Contas a Receber.

    O Main já usa este layout com sucesso:
    Filial=0, Cliente=1, CPF/CNPJ=2, Contato=3, Forma=8,
    Título=10, Parcela=11, Emissão=12, Vencimento=13,
    Pagamento=14, Nominal=15, Pendente=16, Pago=17,
    Juros=18, Observações=19, Avalistas=20.
    """
    out = dict(mp or {})
    fallback = {
        "filial": 0, "cliente": 1, "cpf": 2, "contato": 3,
        "historico": 6, "lancamento": 7, "forma": 8,
        "titulo": 10, "parcela": 11, "emissao": 12,
        "vencimento": 13, "pagamento": 14, "nominal": 15,
        "pendente": 16, "pago": 17, "juros": 18,
        "observacoes": 19, "avalistas": 20,
    }

    # Só usa fallback se o XLS tiver estrutura compatível.
    if ncols >= 18 and {"cliente", "vencimento", "pendente"}.issubset(out):
        for key, idx in fallback.items():
            if key not in out and idx < ncols:
                out[key] = idx

    # Corrige o bug antigo: pagamento capturado na mesma coluna de Forma de Pagamento.
    if out.get("pagamento") == out.get("forma") and 14 < ncols:
        out["pagamento"] = 14

    return out


def detect_header(df) -> tuple[int, dict[str, int]]:
    aliases = {
        "filial": ["filial"], "cliente": ["cliente", "nome_cliente"], "cpf": ["cpf_cnpj", "cpfcnpj", "documento"],
        "contato": ["contato", "telefone"], "historico": ["historico"], "lancamento": ["lancamento", "n_lancamento", "no_lancamento", "numero_lancamento"],
        "forma": ["forma_de_pagamento", "forma_pagamento"], "titulo": ["titulo", "n_titulo", "no_titulo", "numero_titulo"],
        "parcela": ["parcela", "n_parcela", "no_parcela", "numero_parcela"], "emissao": ["emissao", "data_emissao"],
        "vencimento": ["vencimento", "data_vencimento"], "pagamento": ["pagamento", "data_pagamento"],
        "nominal": ["nominal", "valor_nominal"], "pendente": ["pendente", "valor_pendente"], "pago": ["pago_total", "valor_pago", "pago"],
        "juros": ["juros_total", "valor_juros", "juros"], "observacoes": ["observacoes", "observacao"], "avalistas": ["avalistas", "avalista"],
    }
    best = (-1, {})
    for i in range(min(30, len(df))):
        vals = [norm_col(x) for x in list(df.iloc[i])]
        mp: dict[str, int] = {}
        for key, names in aliases.items():
            for j, n in enumerate(vals):
                if _header_match_v1084(key, n, names):
                    mp[key] = j
                    break
        mp = _complete_current_sgi_layout_v1084(mp, len(vals))
        score = sum(k in mp for k in ("cliente", "vencimento", "pendente", "titulo")) + sum(k in mp for k in ("cpf", "parcela", "forma", "avalistas"))
        if score > best[0]:
            best = (score, mp)
    if best[0] < 4:
        # fallback compatível com layout atual com CPF/CNPJ adicionado em C
        ncols = len(df.columns)
        return 1, {
            "filial": 0, "cliente": 1, "cpf": 2, "contato": 3, "historico": 6, "lancamento": 7,
            "forma": 8, "titulo": 10, "parcela": 11, "emissao": 12, "vencimento": 13, "pagamento": 14,
            "nominal": 15, "pendente": 16, "pago": 17, "juros": 18, "observacoes": 19 if ncols > 19 else None,
            "avalistas": 20 if ncols > 20 else (19 if ncols > 19 else None),
        }
    return max(0, best[0] and next((i for i in range(min(30, len(df))) if all(str(df.iloc[i, best[1][k]]).strip() for k in ["cliente"] if k in best[1])), 0)), best[1]


def row_val(row, idx: int | None) -> str:
    if idx is None:
        return ""
    try:
        s = str(row.iloc[idx]).strip()
        return "" if s.lower() in {"nan", "none"} else s
    except Exception:
        return ""


def parse_report_rows(path: Path) -> list[dict[str, Any]]:
    df = read_report_df(path)
    # detecta a linha real de cabeçalho com maior número de nomes conhecidos
    aliases_need = {"cliente", "vencimento", "pendente", "titulo"}
    best_i, best_map, best_score = 0, {}, -1
    for i in range(min(35, len(df))):
        vals = [norm_col(x) for x in list(df.iloc[i])]
        mp = {}
        for key, names in {
            "filial":["filial"],"cliente":["cliente"],"cpf":["cpf_cnpj","cpfcnpj"],"contato":["contato"],"historico":["historico"],
            "lancamento":["lancamento","n_lancamento","numero_lancamento"],"forma":["forma_de_pagamento","forma_pagamento"],"titulo":["titulo","n_titulo","numero_titulo"],
            "parcela":["parcela","n_parcela","numero_parcela"],"emissao":["emissao"],"vencimento":["vencimento"],"pagamento":["data_pagamento","pagamento"],
            "nominal":["nominal","valor_nominal"],"pendente":["pendente","valor_pendente"],"pago":["pago_total","pago"],"juros":["juros_total","juros"],
            "observacoes":["observacoes","observacao"],"avalistas":["avalistas","avalista"]}.items():
            for j, n in enumerate(vals):
                if _header_match_v1084(key, n, names):
                    mp[key] = j
                    break
        mp = _complete_current_sgi_layout_v1084(mp, len(vals))
        score = len(mp)
        if score > best_score:
            best_i, best_map, best_score = i, mp, score
    if not aliases_need.issubset(best_map):
        raise RuntimeError(f"Cabeçalho do contas a receber não reconhecido em {path.name}: {best_map} | colunas={len(df.columns)} | header_row={best_i}")
    log(f"✅ V10.88 cabeçalho SGI reconhecido: linha={best_i} mapa={best_map}")
    out = []
    seller = ""
    today = now_br().date()
    for i in range(best_i + 1, len(df)):
        row = df.iloc[i]
        fil = row_val(row, best_map.get("filial"))
        cli = row_val(row, best_map.get("cliente"))
        if "VENDEDOR:" in fil.upper():
            seller = re.sub(r"^.*?VENDEDOR:\s*", "", fil, flags=re.I).strip()
            continue
        if not cli or cli.upper() in {"CLIENTE", "FILIAL", "TOTAL"} or fil.upper().startswith("TOTAL"):
            continue
        venc = parse_date(row_val(row, best_map.get("vencimento")))
        pend = parse_money(row_val(row, best_map.get("pendente")))
        if not venc or pend <= 0:
            continue
        doc = norm_doc(row_val(row, best_map.get("cpf")))
        if not doc:
            continue
        days = (today - venc).days
        out.append({
            "filial": fil, "cliente": cli, "cpf_cnpj": doc, "contato": row_val(row, best_map.get("contato")),
            "historico": row_val(row, best_map.get("historico")), "lancamento": row_val(row, best_map.get("lancamento")),
            "forma_pagamento": row_val(row, best_map.get("forma")), "titulo": row_val(row, best_map.get("titulo")),
            "parcela": row_val(row, best_map.get("parcela")), "emissao": row_val(row, best_map.get("emissao")),
            "vencimento": venc.strftime("%d/%m/%Y"), "pagamento": row_val(row, best_map.get("pagamento")),
            "nominal": parse_money(row_val(row, best_map.get("nominal"))), "pendente": pend,
            "pago": parse_money(row_val(row, best_map.get("pago"))), "juros": parse_money(row_val(row, best_map.get("juros"))),
            "observacoes": row_val(row, best_map.get("observacoes")), "avalista": row_val(row, best_map.get("avalistas")),
            "vendedor": seller, "dias": days, "source": path.name,
        })
    return out


def merge_title_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set(); out = []
    for group in groups:
        for r in group:
            key = (r.get("cpf_cnpj"), str(r.get("titulo") or ""), str(r.get("parcela") or ""), str(r.get("vencimento") or ""))
            if not r.get("cpf_cnpj") or key in seen:
                continue
            seen.add(key); out.append(r)
    return out


def recent_hold(doc: str, trigger_date: date) -> tuple[bool, str, str]:
    cutoff = now_br().date() - timedelta(days=HOLD_DIAS)
    audits = url_json(AUDIT_API + f"?_={int(time.time())}", {}, 35)
    data = audits.get("data") if isinstance(audits, dict) else []
    for x in data or []:
        if norm_doc(x.get("cpf_cnpj")) != doc:
            continue
        raw_dt = x.get("ia_analisado_em") or x.get("updated_at") or x.get("server_time") or x.get("criado_em")
        d = parse_date(str(raw_dt or "")[:10])
        if not d or d < cutoff:
            continue
        tipo = str(x.get("tipo_resposta") or "").strip().lower()
        if not tipo and x.get("ia_json"):
            try:
                jj = x.get("ia_json") if isinstance(x.get("ia_json"), dict) else json.loads(str(x.get("ia_json")))
                tipo = str(jj.get("tipo_resposta") or "").lower()
            except Exception:
                pass
        if tipo in {"promessa_pagamento", "pedido_boleto_pix", "data_pagamento"}:
            return True, tipo, str(raw_dt or "")
    # pagamento recente no relatório de quitados local/FTP
    q = read_json(QUITADOS_JSON, {})
    if not q:
        q = url_json(PUBLIC_BASE + f"/quitados_180d_contas_receber.json?_={int(time.time())}", {}, 25)
    for x in (q.get("quitados") or []) if isinstance(q, dict) else []:
        if norm_doc(x.get("cpf_cnpj")) != doc:
            continue
        pg = parse_date(x.get("pagamento"))
        if pg and pg >= max(cutoff, trigger_date):
            return True, "pagamento_recente", pg.isoformat()
    return False, "", ""


def _selected_text(select_tag) -> str:
    if not select_tag:
        return ""
    opt = select_tag.find("option", selected=True)
    return opt.get_text(" ", strip=True) if opt else ""


def _input_value(node, name_part: str = "", id_prefix: str = "") -> str:
    if not node:
        return ""
    for el in node.find_all(["input", "textarea"]):
        nm = el.get("name") or ""; iid = el.get("id") or ""
        if (name_part and name_part in nm) or (id_prefix and iid.startswith(id_prefix)):
            return str(el.get("value") or el.get_text(" ", strip=True) or "").strip()
    return ""


def parse_person_html(html: str) -> dict[str, Any]:
    if BeautifulSoup is None:
        return {}
    soup = BeautifulSoup(html or "", "html.parser")
    contacts = []
    tbody = soup.find(id="copia_contatos")
    if tbody:
        for tr in tbody.find_all("tr", class_="copia-linha"):
            sel = None
            for s in tr.find_all("select"):
                if "meio_contato_id" in (s.get("name") or ""):
                    sel = s; break
            tipo = _selected_text(sel)
            info = _input_value(tr, "[informacao]")
            if info:
                contacts.append({"tipo": tipo, "valor": info})
    addresses = []
    cont = soup.find(id="copia_enderecos")
    if cont:
        for bloco in cont.find_all("div", class_="copia-linha", recursive=False):
            item = {
                "principal": bool(bloco.find("input", attrs={"atributo": "endereco_principal", "checked": True})),
                "cep": _input_value(bloco, "[cep_id]", "autocompletar_cep_id"),
                "logradouro": _input_value(bloco, "[logradouro]", "logradouro_"),
                "numero": _input_value(bloco, "[numero]", "numero_"),
                "bairro": _input_value(bloco, "[bairro_id]", "autocompletar_bairro_id"),
                "cidade": _input_value(bloco, "[cidade]", "cidade_"),
                "uf": _input_value(bloco, "[uf]", "uf_"),
                "complemento": _input_value(bloco, "[complemento]", "complemento_"),
            }
            if any(str(v or "").strip() for k, v in item.items() if k != "principal"):
                addresses.append(item)
    main_addr = next((x for x in addresses if x.get("principal")), addresses[0] if addresses else {})
    phones=[]; email=""
    for c in contacts:
        typ=norm_text(c.get("tipo")); val=str(c.get("valor") or "").strip()
        if "MAIL" in typ or "EMAIL" in typ or "@" in val:
            if not email: email=val
        else:
            digits=re.sub(r"\D+","",val)
            if len(digits)>=8 and digits not in phones: phones.append(digits)
    pessoa_id=""
    m=re.search(r"edit_pessoa_(\d+)", html or "")
    if m: pessoa_id=m.group(1)
    return {"phones":phones[:3],"email":email,"address":main_addr,"pessoa_id":pessoa_id}


def find_person_and_enrich(driver, url: str, doc: str, expected_name: str, mutate: bool) -> tuple[dict[str, Any], str, str]:
    """Retorna dados, status nome, mensagem. Nunca salva se mutate=False."""
    driver.get(url + "/pessoas")
    wait=WebDriverWait(driver,20)
    # pesquisa por CPF/CNPJ; ids variam entre versões
    inp=None
    selectors=[(By.ID,"cpf_cnpj_cpf"),(By.ID,"cpf_cnpj_ilike"),(By.ID,"cpf_cnpj"),(By.NAME,"cpf_cnpj_ilike"),(By.CSS_SELECTOR,"input[mascara*='999.999.999']")]
    for by,sel in selectors:
        try:
            inp=wait.until(EC.presence_of_element_located((by,sel))); break
        except Exception: pass
    if inp is None:
        raise RuntimeError("Campo CPF/CNPJ da tela Pessoas não encontrado")
    inp.clear(); inp.send_keys(doc)
    # botão buscar
    clicked=False
    for xp in ("//button[@type='submit' and contains(., 'Filtrar')]","//button[contains(.,'Buscar')]","//input[@value='Buscar']","//*[@id='btn_buscar']","//*[@id='buscar']"):
        try: click_xpath(driver,xp,5); clicked=True; break
        except Exception: pass
    if not clicked: inp.send_keys(Keys.ENTER)
    time.sleep(1.5)
    link=None
    for xp in ("//table//tbody//tr[1]//a[contains(@href,'/pessoas/') and contains(@href,'edit')]","//table//tbody//tr[1]//a","//a[contains(@href,'/pessoas/') and contains(@href,'edit')]"):
        try:
            link=WebDriverWait(driver,8).until(EC.presence_of_element_located((By.XPATH,xp))); break
        except Exception: pass
    if link is None:
        raise RuntimeError(f"Pessoa {doc} não encontrada no SGI")
    href=link.get_attribute("href") or ""
    driver.get(href); time.sleep(1)
    data=parse_person_html(driver.page_source)
    name_el=None
    try: name_el=WebDriverWait(driver,10).until(EC.presence_of_element_located((By.ID,"nome")))
    except Exception:
        try: name_el=driver.find_element(By.CSS_SELECTOR,"input[name='pessoa[nome]']")
        except Exception: pass
    current=(name_el.get_attribute("value") if name_el is not None else expected_name) or expected_name
    marker=blocked_marker(current)
    if marker:
        return data, "bloqueado_marcador", marker
    if has_cob_marker(current):
        return data, "ja_marcado_cob", current
    final=clean_customer_name_for_cob(current or expected_name)
    if not mutate:
        data["nome_atual"]=current; data["nome_final_simulado"]=final
        return data, "simulado_nome", final
    if name_el is None:
        raise RuntimeError("Campo nome no cadastro SGI não encontrado")
    name_el.clear(); name_el.send_keys(final)
    saved=False
    for xp in ("//*[@id='botao_salvar']","//button[contains(.,'Salvar')]","//input[@value='Salvar']"):
        try: click_xpath(driver,xp,8); saved=True; break
        except Exception: pass
    if not saved:
        raise RuntimeError("Botão Salvar do cadastro SGI não encontrado")
    time.sleep(1.2)
    # revalida sem depender de toast
    try:
        current2=driver.find_element(By.ID,"nome").get_attribute("value") or ""
    except Exception:
        current2=final
    if not has_cob_marker(current2):
        raise RuntimeError("Nome não permaneceu com (COB) após salvar")
    data["nome_atual"]=current; data["nome_final"]=current2
    return data, "nome_atualizado", current2


def build_csv_row(item: dict[str, Any], title: dict[str, Any]) -> dict[str, str]:
    person=item.get("pessoa") or {}; addr=person.get("address") or {}; phones=list(person.get("phones") or [])
    while len(phones)<3: phones.append("")
    extras=[]
    for label,key in (("FILIAL","filial"),("FORMA","forma_pagamento"),("VENDEDOR","vendedor")):
        if title.get(key): extras.append(f"{label}: {title.get(key)}")
    extras.append(f"DIAS VENCIDOS: {title.get('dias',0)}")
    if title.get("avalista"): extras.append("AVALISTA: "+str(title.get("avalista")))
    if title.get("observacoes"): extras.append("OBS: "+str(title.get("observacoes"))[:900])
    return {
        "COD_DEVEDOR": str(person.get("pessoa_id") or item.get("codigo_devedor") or item.get("cpf_cnpj") or ""),
        "NOME": str(item.get("nome_exportacao") or item.get("cliente") or ""),
        "CNPJ_CPF": str(item.get("cpf_cnpj") or ""),
        "FONE 1": phones[0], "FONE 2": phones[1], "FONE 3": phones[2], "EMAIL": str(person.get("email") or ""),
        "ENDERECO": str(addr.get("logradouro") or ""), "NUMERO": str(addr.get("numero") or ""),
        "COMPLEMENTO": str(addr.get("complemento") or ""), "BAIRRO": str(addr.get("bairro") or ""),
        "CIDADE": str(addr.get("cidade") or ""), "ESTADO": str(addr.get("uf") or ""), "CEP": str(addr.get("cep") or ""),
        "DADOS_ADICIONAIS": " | ".join(extras), "COD_TITULO": str(title.get("titulo") or ""),
        "PARCELA": str(title.get("parcela") or ""), "CONTRATO": str(title.get("lancamento") or ""),
        "DT_VENCIMENTO": str(title.get("vencimento") or ""), " VL_TITULO ": fmt_money_csv(title.get("pendente") or 0),
    }


def write_model_csv(state: dict[str, Any]) -> int:
    rows=[]
    for item in state.get("items") or []:
        if str(item.get("status") or "").lower() not in {"pronto", "enviado"}:
            continue
        for title in item.get("titulos") or []:
            rows.append(build_csv_row(item,title))
    with CSV_PATH.open("w",encoding="utf-8-sig",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=MODEL_HEADER,delimiter=";",extrasaction="ignore",quoting=csv.QUOTE_MINIMAL)
        w.writeheader(); w.writerows(rows)
    return len(rows)


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    items=state.get("items") or []
    counts={}
    for x in items:
        st=str(x.get("status") or "sem_status").lower(); counts[st]=counts.get(st,0)+1
    ready=[x for x in items if str(x.get("status") or "").lower()=="pronto"]
    return {"total_cpfs":len(items),"por_status":counts,"prontos":len(ready),"valor_pronto":round(sum(sum(float(t.get('pendente') or 0) for t in x.get('titulos') or []) for x in ready),2)}


def public_blocklist(state: dict[str, Any]) -> dict[str, Any]:
    hashes = sorted({doc_hash(x.get("cpf_cnpj")) for x in (state.get("items") or []) if str(x.get("status") or "").lower() in ACTIVE_STATUSES and doc_hash(x.get("cpf_cnpj"))})
    return {"version": VERSION, "updated_at": now_br().isoformat(), "algorithm": "sha256", "active_hashes": hashes, "active_count": len(hashes)}


def public_summary(state: dict[str, Any]) -> dict[str, Any]:
    today = now_br().date().isoformat(); items = state.get("items") or []
    def day(v: Any) -> str: return str(v or "")[:10]
    new = [x for x in items if day(x.get("ready_at") or x.get("trigger_at")) == today and str(x.get("status") or "").lower() in {"pronto","enviado"}]
    sent = [x for x in items if day(x.get("sent_at") or x.get("last_download_at")) == today and str(x.get("status") or "").lower() == "enviado"]
    holds = [x for x in items if str(x.get("status") or "").lower() == "hold_acordo"]
    errors = [x for x in items if str(x.get("status") or "").lower() in {"erro_sgi","bloqueado_marcador"}]
    return {
        "version": VERSION, "updated_at": now_br().isoformat(), "date": today,
        "new_cpfs_today": len(new), "sent_cpfs_today": len(sent),
        "sent_titles_today": sum(len(x.get("titulos") or []) for x in sent),
        "new_value_today": round(sum(sum(float(t.get("pendente") or 0) for t in (x.get("titulos") or [])) for x in new), 2),
        "hold_count": len(holds), "error_count": len(errors),
        "ready_count": sum(1 for x in items if str(x.get("status") or "").lower() == "pronto"),
        "sent_total": sum(1 for x in items if str(x.get("status") or "").lower() == "enviado"),
    }


def publish_state_files(state: dict[str, Any], preview_data: dict[str, Any] | None = None) -> bool:
    save_json_atomic(BLOCKLIST_PATH, public_blocklist(state))
    save_json_atomic(SUMMARY_PATH, public_summary(state))
    results = [
        ftp_upload_bytes(protected_payload(state), "cobranca_terceira_fila_privada.php"),
        ftp_upload(BLOCKLIST_PATH, "cobranca_terceira_bloqueios.json"),
        ftp_upload(SUMMARY_PATH, "cobranca_terceira_resumo.json"),
    ]
    if preview_data is not None:
        results.append(ftp_upload_bytes(protected_payload(preview_data), "cobranca_terceira_preview_privado.php"))
    return all(results)



def notify_cob_external_ready(state: dict[str, Any]) -> tuple[bool, str]:
    """Avisa somente os contatos marcados como COB externa. Nunca envia PII."""
    pending = [
        x for x in (state.get("items") or [])
        if str(x.get("status") or "").lower() == "pronto"
        and not str(x.get("cob_notified_at") or "").strip()
    ]
    if not pending:
        return True, "nenhum_lote_novo"
    cpfs = len(pending)
    titulos = sum(len(x.get("titulos") or []) for x in pending)
    valor = round(sum(sum(float(t.get("pendente") or 0) for t in (x.get("titulos") or [])) for x in pending), 2)
    summary = {
        "cpfs": cpfs,
        "titulos": titulos,
        "valor": valor,
        "test_mode": TEST_MODE,
        "test_limit": TEST_LIMIT,
        "dashboard": PUBLIC_BASE,
    }
    try:
        from whatsapp_master_notificacoes import whatsapp_send, build_cob_external_base_alert
        text = build_cob_external_base_alert(summary)
        ok, resp = whatsapp_send(text, alert_type="cob_externa", base_dir=str(BASE_DIR))
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if ok:
        ts = now_br().isoformat()
        ids = {str(x.get("id") or "") for x in pending}
        for item in state.get("items") or []:
            if str(item.get("id") or "") in ids:
                item["cob_notified_at"] = ts
        return True, resp
    return False, resp


def main() -> int:
    if not ENABLED:
        log("ℹ️ COB_TERCEIRA_ENABLED=0; nada executado."); return 0
    log(f"🤝 COB Externa {VERSION} | D+{DIAS} | janela={JANELA}d | hold={HOLD_DIAS}d | dry_run={DRY_RUN} | dry_run_fast={DRY_RUN_FAST} | test_mode={TEST_MODE} | test_limit={TEST_LIMIT}")
    state=load_remote_state(); state.setdefault("items",[]); state.setdefault("batches",[])
    old_map={norm_doc(x.get("cpf_cnpj")):x for x in state["items"] if isinstance(x,dict) and norm_doc(x.get("cpf_cnpj"))}
    for _doc_old, _item_old in list(old_map.items()):
        if str((_item_old or {}).get("status") or "").lower() == "ja_marcado_cob":
            _item_old["status"] = "pronto"
            _item_old["marker_info"] = _item_old.get("marker_info") or "Cadastro já estava com (COB); recuperado como pronto."
            _item_old["ready_at"] = _item_old.get("ready_at") or now_br().isoformat()
    url,user,pwd=credentials()
    work=Path(tempfile.mkdtemp(prefix="cob-terceira-"))
    driver=None
    try:
        driver=chrome_driver(work); login_sgi(driver,url,user,pwd)
        trigger_path=generate_trigger_report(driver,url,work)
        trigger_rows=parse_report_rows(trigger_path)
        main_rows=parse_report_rows(MAIN_FIXED) if MAIN_FIXED.exists() else []
        prev_rows=parse_report_rows(PREVENTIVA_FIXED) if PREVENTIVA_FIXED.exists() else []
        today=now_br().date()
        trigger_rows=[r for r in trigger_rows if r.get("dias",0)>=DIAS and r.get("pendente",0)>0]
        trigger_docs=sorted({r["cpf_cnpj"] for r in trigger_rows if r.get("cpf_cnpj")})
        # Reavalia holds antigos todos os dias, mesmo se já saíram da janela D+91..97.
        revisit_docs=[d for d,x in old_map.items() if str(x.get("status") or "").lower()=="hold_acordo"]

        # V10.88: homologação real com teto TOTAL, não "30 por clique".
        # Prioriza os CPFs com maior atraso e só libera novos até completar TEST_LIMIT ativos.
        trigger_priority = sorted(
            trigger_docs,
            key=lambda d: (
                -max([int(r.get("dias") or 0) for r in trigger_rows if r.get("cpf_cnpj")==d] or [DIAS]),
                d,
            )
        )
        if (not DRY_RUN) and TEST_MODE:
            active_existing = {
                d for d,x in old_map.items()
                if str((x or {}).get("status") or "").lower() in ACTIVE_STATUSES
            }
            blocked_existing = {
                d for d,x in old_map.items()
                if str((x or {}).get("status") or "").lower() == "bloqueado_marcador"
            }
            remaining = max(0, TEST_LIMIT - len(active_existing))
            eligible_new = [d for d in trigger_priority if d not in active_existing and d not in blocked_existing]
            selected_new = eligible_new[:remaining]
            docs = sorted(set(selected_new + revisit_docs))
            log(
                f"🧰 V10.88 homologação: {len(active_existing)}/{TEST_LIMIT} CPF(s) já externalizados; "
                f"restam {remaining}; {len(selected_new)} novo(s) serão processados nesta execução."
            )
        else:
            docs=sorted(set(trigger_priority+revisit_docs))
        log(f"🔎 {len(trigger_rows)} título(s) gatilho; {len(trigger_docs)} CPF(s) novos/na janela; {len(revisit_docs)} hold(s) reavaliados; {len(docs)} CPF(s) selecionados para esta execução.")
        preview=[]
        total_docs=len(docs)
        if DRY_RUN and DRY_RUN_FAST:
            log("⚡ V10.88 DRY RUN rápido: não abrirá 1 cadastro SGI por CPF. O preview usa os dados do relatório; enriquecimento individual fica para a ativação real.")
        for pos, doc in enumerate(docs, 1):
            if pos == 1 or pos % PROGRESS_EVERY == 0 or pos == total_docs:
                log(f"⏳ V10.88 processamento COB Externa: {pos}/{total_docs} CPF(s).")
            existing=old_map.get(doc)
            if existing and str(existing.get("status") or "").lower() in {"pronto","enviado","bloqueado_marcador"}:
                continue
            trig=[r for r in trigger_rows if r["cpf_cnpj"]==doc]
            oldest=min((parse_date(r.get("vencimento")) for r in trig if parse_date(r.get("vencimento"))), default=today-timedelta(days=DIAS))
            hold,hold_reason,hold_at=recent_hold(doc,oldest)
            seed=(trig[0] if trig else (existing or {}))
            if hold:
                item={**(existing or {}),"id":item_id(doc),"cpf_cnpj":doc,"cliente":seed.get("cliente") or (existing or {}).get("cliente") or "","status":"hold_acordo","hold_reason":hold_reason,"hold_at":hold_at,"hold_until":(today+timedelta(days=HOLD_DIAS)).isoformat(),"updated_at":now_br().isoformat()}
                old_map[doc]=item; preview.append(item); continue
            all_doc=[r for r in merge_title_rows(trig,main_rows,prev_rows) if r.get("cpf_cnpj")==doc and int(r.get("dias") or 0)>=0 and float(r.get("pendente") or 0)>0]
            if not all_doc and existing:
                all_doc=list(existing.get("titulos") or [])
            client_name=(trig[0].get("cliente") if trig else (existing or {}).get("cliente") or "")
            try:
                if DRY_RUN and DRY_RUN_FAST:
                    # Preview rápido: usa os dados já presentes no relatório de Contas a Receber.
                    # Não abre /pessoas 264 vezes apenas para simulação.
                    contato = str(seed.get("contato") or "")
                    phones = []
                    for bloco in re.split(r"[/;,|]+", contato):
                        d = re.sub(r"\D+", "", bloco)
                        if len(d) >= 8 and d not in phones:
                            phones.append(d)
                    marker = blocked_marker(client_name)
                    if marker:
                        name_status, name_info = "bloqueado_marcador", marker
                        status = "bloqueado_marcador"
                    elif has_cob_marker(client_name):
                        name_status, name_info = "ja_marcado_cob", client_name
                        status = "ja_marcado_cob"
                    else:
                        name_status, name_info = "simulado_nome", clean_customer_name_for_cob(client_name)
                        status = "simulado"
                    person = {
                        "phones": phones[:3],
                        "email": "",
                        "address": {},
                        "pessoa_id": "",
                        "nome_atual": client_name,
                        "nome_final_simulado": clean_customer_name_for_cob(client_name),
                        "preview_sem_enriquecimento_sgi": True,
                    }
                else:
                    person,name_status,name_info=find_person_and_enrich(driver,url,doc,client_name,mutate=(not DRY_RUN))
                    if name_status=="bloqueado_marcador":
                        status="bloqueado_marcador"
                    elif name_status=="ja_marcado_cob":
                        status="pronto"
                        name_info="Já estava com (COB) no SGI; considerado pronto para a COB Externa."
                    elif DRY_RUN:
                        status="simulado"
                    else:
                        status="pronto"
                item={**(existing or {}),"id":item_id(doc),"cpf_cnpj":doc,"cliente":client_name,"nome_exportacao":clean_customer_name_for_cob(client_name),"status":status,"marker_info":name_info,"pessoa":person,"titulos":all_doc,"trigger_dias_max":max([int(r.get('dias') or 0) for r in trig] or [int((existing or {}).get('trigger_dias_max') or DIAS)]),"trigger_at":(existing or {}).get("trigger_at") or now_br().isoformat(),"ready_at":((existing or {}).get("ready_at") or (now_br().isoformat() if status=="pronto" else "")),"updated_at":now_br().isoformat()}
            except Exception as exc:
                status="simulado_erro_sgi" if DRY_RUN else "erro_sgi"
                item={**(existing or {}),"id":item_id(doc),"cpf_cnpj":doc,"cliente":client_name,"status":status,"erro_sgi":str(exc)[:1200],"titulos":all_doc,"trigger_at":(existing or {}).get("trigger_at") or now_br().isoformat(),"updated_at":now_br().isoformat()}
            old_map[doc]=item; preview.append(item)
        # Mantém todos os registros antigos e ordena por trigger_at.
        state["items"]=sorted(old_map.values(), key=lambda x:(str(x.get("trigger_at") or ""),str(x.get("cpf_cnpj") or "")), reverse=True)
        state["version"]=VERSION; state["updated_at"]=now_br().isoformat(); state["dry_run"]=DRY_RUN
        state["rule"]={"dias":DIAS,"janela_captura_dias":JANELA,"hold_acordo_dias":HOLD_DIAS,"cpf_inteiro":True,"prioridade_externa":True,"bloqueia_interno_somente_apos_sgi_ok":True,"test_mode":TEST_MODE,"test_limit":TEST_LIMIT,"formas_pagamento":["Carnê Loja (AP)","Carnê Loja Safira (AP)","Renegociação/Acordo"]}
        state["summary"]=state_summary(state)
        preview_data={"version":VERSION,"updated_at":now_br().isoformat(),"dry_run":DRY_RUN,"rule":{"test_mode":TEST_MODE,"test_limit":TEST_LIMIT},"items":preview,"summary":state_summary({"items":preview})}
        save_json_atomic(PREVIEW_PATH,preview_data)
        if DRY_RUN:
            # Preview completo fica protegido por PHP; nenhum CPF é exposto em JSON público.
            if not ftp_upload_bytes(protected_payload(preview_data),"cobranca_terceira_preview_privado.php"):
                raise RuntimeError("não foi possível publicar o preview protegido da Cobrança Terceira")
            log(f"🧪 V10.88 DRY RUN concluído: {len(preview)} CPF(s) simulados; nenhum nome/estado oficial alterado. Enriquecimento SGI individual={"adiado para ativação real" if DRY_RUN_FAST else "executado"}.")
            return 0
        state=merge_download_status(state)
        state["summary"]=state_summary(state)
        save_json_atomic(STATE_PATH,state)
        rows=write_model_csv(state)
        if not publish_state_files(state, preview_data):
            raise RuntimeError("publicação FTP incompleta; scheduler deve tentar novamente para evitar divergência entre SGI e dashboard")

        # A base já está publicada antes de avisar a parceira.
        notify_ok, notify_resp = notify_cob_external_ready(state)
        if notify_ok and notify_resp != "nenhum_lote_novo":
            save_json_atomic(STATE_PATH, state)
            state["summary"] = state_summary(state)
            publish_state_files(state, preview_data)
            log(f"💬 V10.88 aviso de nova base COB Externa enviado sem PII: {notify_resp}")
        elif not notify_ok:
            log(f"ℹ️ V10.88 base pronta, mas aviso COB Externa não enviado: {notify_resp}")

        # CSV consolidado técnico não é publicado no webroot; o download oficial passa pela API autenticada.
        log(f"✅ Fila oficial COB Externa atualizada/protegida: {state['summary']} | {rows} linha(s) no CSV local consolidado.")
        return 0
    except Exception as exc:
        log(f"❌ Cobrança Terceira falhou: {type(exc).__name__}: {exc}")
        return 2
    finally:
        try:
            if driver: driver.quit()
        except Exception: pass
        shutil.rmtree(work,ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

# V10.88_COB_EXTERNA_TESTE30_BLOQUEIO_APOS_SGI_OK
