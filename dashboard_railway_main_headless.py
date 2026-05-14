# VERSAO: COBRANCA10_V3_FIX_NAMEERROR
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
import pandas as pd
import time
import re
import os
import webbrowser
import random
import json
import unicodedata
import urllib.request
import urllib.error
import tempfile
from zoneinfo import ZoneInfo

LOGIN = "administrativo01.moveisdolar"
SENHA = "mdladm01"
URL   = "https://smart.sgisistemas.com.br"
APP_TZ = ZoneInfo(os.getenv("APP_TZ", "America/Sao_Paulo"))

def now_brasilia():
    return datetime.now(APP_TZ)

# ===== DATAS
hoje        = datetime.now()
data_inicio = (hoje - timedelta(days=90)).strftime("%d/%m/%Y")
data_fim    = (hoje - timedelta(days=15)).strftime("%d/%m/%Y")

# ===== CHROME
options = Options()
IS_RAILWAY = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RUN_ON_RAILWAY") == "1")
pasta = os.path.dirname(os.path.abspath(__file__))
download_dir = pasta if not IS_RAILWAY else tempfile.gettempdir()

if IS_RAILWAY:
    options.page_load_strategy = 'eager'
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    options.add_argument("--hide-scrollbars")
    options.add_argument("--mute-audio")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-infobars")
    options.add_argument("--ignore-certificate-errors")
    options.add_argument("--allow-insecure-localhost")
else:
    options.add_argument("--start-maximized")

prefs = {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
}
options.add_experimental_option("prefs", prefs)
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

chrome_bin = (
    os.getenv("GOOGLE_CHROME_BIN")
    or os.getenv("CHROME_BIN")
    or "/usr/bin/google-chrome"
    or "/usr/bin/chromium"
)

chrome_driver_bin = (
    os.getenv("CHROMEDRIVER")
    or os.getenv("CHROMEDRIVER_PATH")
)

if os.path.exists(chrome_bin):
    options.binary_location = chrome_bin

try:
    if chrome_driver_bin and os.path.exists(chrome_driver_bin):
        driver = webdriver.Chrome(service=Service(chrome_driver_bin), options=options)
    else:
        driver = webdriver.Chrome(options=options)
except WebDriverException as e:
    print(f"❌ Erro ao iniciar Chrome/Chromedriver: {e}")
    print(f"   binary_location={getattr(options, 'binary_location', '')}")
    print(f"   GOOGLE_CHROME_BIN={os.getenv('GOOGLE_CHROME_BIN')}")
    print(f"   CHROME_BIN={os.getenv('CHROME_BIN')}")
    print(f"   CHROMEDRIVER={os.getenv('CHROMEDRIVER')}")
    print(f"   CHROMEDRIVER_PATH={os.getenv('CHROMEDRIVER_PATH')}")
    raise

driver.set_page_load_timeout(120)
wait   = WebDriverWait(driver, 40)


# ===== SELENIUM HELPERS
def esperar_sumir_overlays(timeout=10):
    fim = time.time() + timeout
    overlays = [
        ".blockUI", ".modal-backdrop", ".loading", ".spinner",
        ".ui-widget-overlay", ".select2-drop-mask"
    ]
    while time.time() < fim:
        try:
            ativos = driver.execute_script("""
                const sels = arguments[0];
                return sels.some(sel =>
                    Array.from(document.querySelectorAll(sel)).some(el => {
                        const s = window.getComputedStyle(el);
                        return s.display !== 'none' && s.visibility !== 'hidden' && el.offsetParent !== null;
                    })
                );
            """, overlays)
            if not ativos:
                return True
        except Exception:
            return True
        time.sleep(0.2)
    return False


def localizar_xpath_clickavel(xpath, timeout=20):
    elem = wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'center'});", elem
    )
    esperar_sumir_overlays()
    try:
        elem = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        )
    except Exception:
        elem = driver.find_element(By.XPATH, xpath)
    return elem


def clicar_seguro_xpath(xpath, timeout=20):
    ultimo_erro = None
    for _ in range(3):
        try:
            elem = localizar_xpath_clickavel(xpath, timeout=timeout)
            try:
                elem.click()
            except Exception:
                driver.execute_script("arguments[0].click();", elem)
            return elem
        except Exception as e:
            ultimo_erro = e
            time.sleep(0.5)
    raise ultimo_erro


def abrir_multiselect_por_label(label_texto, timeout=20):
    xpath_botao = (
        f"//label[contains(normalize-space(.),'{label_texto}')]/following::button[1]"
    )
    botao = clicar_seguro_xpath(xpath_botao, timeout=timeout)
    time.sleep(1)
    return botao


def marcar_multiselect_por_label(label_texto, valores, timeout=20, limpar_antes=True):
    abrir_multiselect_por_label(label_texto, timeout=timeout)
    xpath_ul = f"//label[contains(normalize-space(.),'{label_texto}')]/following::ul[1]"
    container = wait.until(EC.presence_of_element_located((By.XPATH, xpath_ul)))
    driver.execute_script(
        "arguments[0].scrollIntoView({block:'center', inline:'nearest'});", container
    )
    time.sleep(0.5)
    checkboxes = container.find_elements(By.XPATH, ".//input[@type='checkbox']")
    valores = {str(v) for v in valores}

    if limpar_antes:
        for c in checkboxes:
            if c.is_selected():
                driver.execute_script("arguments[0].click();", c)
                time.sleep(0.05)

    for c in checkboxes:
        if c.get_attribute("value") in valores and not c.is_selected():
            driver.execute_script("arguments[0].click();", c)
            time.sleep(0.05)

    driver.execute_script("document.body.click();")
    time.sleep(0.5)
    return checkboxes


def normalizar_texto_match(texto):
    s = str(texto or "").strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def set_input_value_safe(by, locator, value):
    el = wait.until(EC.presence_of_element_located((by, locator)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
        el.send_keys(Keys.CONTROL, "a")
        el.send_keys(Keys.DELETE)
        el.send_keys(value)
    except Exception:
        driver.execute_script("arguments[0].value = arguments[1];", el, value)
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", el)
    return el


def clicar_primeiro_filtro_metas():
    xpaths = [
        "//button[contains(.,'Filtrar')]",
        "//a[contains(.,'Filtrar')]",
        "//button[@type='submit' and contains(.,'Filtrar')]",
    ]
    ultimo = None
    for xp in xpaths:
        try:
            return clicar_seguro_xpath(xp, timeout=10)
        except Exception as e:
            ultimo = e
    if ultimo:
        raise ultimo



def extrair_linhas_tabela_metas():
    """
    Lê a tabela de metas de forma robusta usando os atributos data-title/data-value.
    O SGI muda os IDs das metas todo mês (ex.: 208, 209, 210, 211), então não usamos ID fixo.
    """
    wait.until(EC.presence_of_all_elements_located((By.XPATH, "//table//tbody/tr")))
    linhas = []

    # Primeira tentativa: via JavaScript, pegando data-title/data-value da própria tabela.
    try:
        rows = driver.execute_script("""
            const out = [];
            document.querySelectorAll('table tbody tr').forEach(tr => {
                const obj = {};
                tr.querySelectorAll('td').forEach((td, idx) => {
                    const title = (td.getAttribute('data-title') || '').trim();
                    const val = (td.getAttribute('data-value') || td.innerText || '').trim();
                    if (title) obj[title] = val;
                    obj['col_' + idx] = val;
                    const a = td.querySelector('a[href]');
                    if (a && !obj['_href_id']) obj['_href_id'] = a.getAttribute('href') || '';
                    if (a && (a.getAttribute('href')||'').includes('/metas/consulta/')) obj['_href_resultado'] = a.getAttribute('href') || '';
                });
                if (Object.keys(obj).length) out.push(obj);
            });
            return out;
        """) or []

        for obj in rows:
            id_meta = str(obj.get('ID') or obj.get('Id') or obj.get('id') or obj.get('col_0') or '').strip()
            id_meta = re.sub(r"\D", "", id_meta)
            if not id_meta:
                continue

            tipo = str(obj.get('Tipo') or obj.get('tipo') or obj.get('col_1') or '').strip()
            escopo = str(obj.get('Escopo') or obj.get('escopo') or obj.get('col_2') or '').strip()
            descricao = str(obj.get('Descrição') or obj.get('Descricao') or obj.get('descricao') or obj.get('col_3') or '').strip()
            data_inicial = str(obj.get('Data Inicial') or obj.get('data inicial') or obj.get('col_4') or '').strip()
            data_final = str(obj.get('Data Final') or obj.get('data final') or obj.get('col_5') or '').strip()

            href_resultado = str(obj.get('_href_resultado') or '').strip()
            if href_resultado.startswith('/'):
                href_resultado = URL + href_resultado
            if not href_resultado:
                href_resultado = f"{URL}/metas/consulta/{id_meta}"

            linhas.append({
                "id": id_meta,
                "tipo": tipo,
                "escopo": escopo,
                "descricao": descricao,
                "data_inicial": data_inicial,
                "data_final": data_final,
                "href_resultado": href_resultado,
            })

        if linhas:
            return linhas
    except Exception as e:
        print(f"⚠️ Leitura JS da tabela de metas falhou, tentando Selenium comum: {e}")

    # Fallback: leitura Selenium tradicional.
    for tr in driver.find_elements(By.XPATH, "//table//tbody/tr"):
        tds = tr.find_elements(By.TAG_NAME, "td")
        if len(tds) < 4:
            continue
        vals = []
        for td in tds:
            vals.append((td.get_attribute('data-value') or td.text or '').strip())
        id_meta = re.sub(r"\D", "", vals[0] if vals else "")
        if not id_meta:
            continue
        item = {
            "id": id_meta,
            "tipo": vals[1] if len(vals) > 1 else "",
            "escopo": vals[2] if len(vals) > 2 else "",
            "descricao": vals[3] if len(vals) > 3 else "",
            "data_inicial": vals[4] if len(vals) > 4 else "",
            "data_final": vals[5] if len(vals) > 5 else "",
            "href_resultado": f"{URL}/metas/consulta/{id_meta}",
        }
        linhas.append(item)
    return linhas


def linha_meta_match(item, spec):
    tipo = normalizar_texto_match(item.get("tipo"))
    escopo = normalizar_texto_match(item.get("escopo"))
    desc = normalizar_texto_match(item.get("descricao"))

    tipo_spec = normalizar_texto_match(spec.get("tipo", ""))
    escopo_spec = normalizar_texto_match(spec.get("escopo", ""))

    if tipo_spec and tipo_spec != tipo:
        return False
    if escopo_spec and escopo_spec != escopo:
        return False

    partes = [normalizar_texto_match(p) for p in spec.get("descricao_contem", [])]
    return all(parte in desc for parte in partes if parte)


def escolher_melhor_linha_meta(linhas, spec):
    """
    Escolhe a meta do mês pela linha exibida na tela.
    Não usa IDs fixos, porque o SGI cria novos IDs todo mês.
    """
    candidatos = [x for x in linhas if linha_meta_match(x, spec)]
    if not candidatos:
        return None

    def id_int(x):
        return int(re.sub(r"\D", "", str(x.get("id") or "0")) or "0")

    candidatos.sort(key=id_int, reverse=True)
    escolhido = dict(candidatos[0])
    id_meta = str(escolhido.get("id", "")).strip()
    if id_meta and not escolhido.get("href_resultado"):
        escolhido["href_resultado"] = f"{URL}/metas/consulta/{id_meta}"
    return escolhido

def limpar_df_tabela(df):
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    return df


def encontrar_df_resultado_metas():
    # Lê direto da tabela HTML visível via Selenium, sem depender de lxml/pandas.read_html
    possiveis = [
        "//table[@id='tabela_metas']",
        "//table[contains(@class,'tabela-metas')]",
        "(//table[contains(@class,'table') and .//tbody/tr])[1]",
    ]
    tabela = None
    ultimo_erro = None

    for xp in possiveis:
        try:
            tabela = wait.until(EC.presence_of_element_located((By.XPATH, xp)))
            if tabela and tabela.find_elements(By.XPATH, ".//tbody/tr"):
                break
        except Exception as e:
            ultimo_erro = e
            tabela = None

    if tabela is None:
        raise Exception(f"Tabela de resultados das metas não encontrada na tela: {ultimo_erro}")

    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", tabela)
    time.sleep(0.6)

    headers = []
    for th in tabela.find_elements(By.XPATH, ".//thead//th"):
        txt = th.text.strip()
        if txt:
            headers.append(re.sub(r"\s+", " ", txt))

    # Alguns layouts têm a 1ª coluna sem texto no header. Ajusta pelo data-title do tbody.
    linhas = []
    trs = tabela.find_elements(By.XPATH, ".//tbody/tr[td]")
    for tr in trs:
        tds = tr.find_elements(By.XPATH, "./td")
        vals = []
        for td in tds:
            txt = td.text.strip()
            if not txt:
                txt = td.get_attribute("data-value") or ""
            vals.append(re.sub(r"\s+", " ", txt).strip())
        if any(v for v in vals):
            linhas.append(vals)

        # Le tfoot - o SGI coloca a linha de Total aqui
    trs_tfoot = tabela.find_elements(By.XPATH, ".//tfoot/tr[td]")
    for tr in trs_tfoot:
        tds = tr.find_elements(By.XPATH, "./td")
        vals = []
        for td in tds:
            txt = td.text.strip()
            if not txt:
                txt = td.get_attribute("data-value") or ""
            vals.append(re.sub(r"\\s+", " ", txt).strip())
        if any(v for v in vals):
            linhas.append(vals)

    if not linhas:
        raise Exception("Tabela de metas encontrada, mas sem linhas no tbody")

    max_cols = max(len(x) for x in linhas)
    while len(headers) < max_cols:
        idx = len(headers)
        if idx == 0:
            # tenta descobrir pelo data-title da primeira célula
            try:
                data_title = trs[0].find_elements(By.XPATH, "./td")[0].get_attribute("data-title") or ""
                headers.append(data_title.strip() or "Nome")
            except Exception:
                headers.append("Nome")
        else:
            headers.append(f"Coluna_{idx+1}")

    headers = headers[:max_cols]
    linhas = [row + [""] * (max_cols - len(row)) for row in linhas]
    df = pd.DataFrame(linhas, columns=headers)

    # Normaliza nomes esperados das colunas
    ren = {}
    for i, c in enumerate(df.columns):
        uc = normalizar_texto_match(c)
        nome = c
        if uc in ("FILIAL", "VENDEDOR", "SUBGRUPO", "FILIAL/VENDEDOR", "VENDEDOR/SUBGRUPO"):
            nome = c.title()
        elif "META(R$) TOTAL" in uc:
            nome = "Meta(R$) Total"
        elif "REALIZADO(R$) TOTAL" in uc:
            nome = "Realizado(R$) Total"
        elif "ATINGIDO TOTAL" in uc:
            nome = "Atingido Total"
        elif "META(R$) PERIODO" in uc:
            nome = "Meta(R$) Período"
        elif "REALIZADO(R$) PERIODO" in uc:
            nome = "Realizado(R$) Período"
        elif "ATINGIDO PERIODO" in uc:
            nome = "Atingido Período"
        elif "PROJETADO(R$)" in uc:
            nome = "Projetado(R$)"
        ren[c] = nome
    df = df.rename(columns=ren)

    # Garante nomes únicos: ex. Vendedor, Vendedor_2
    cols = []
    usados = {}
    for c in df.columns:
        if c not in usados:
            usados[c] = 1
            cols.append(c)
        else:
            usados[c] += 1
            cols.append(f"{c}_{usados[c]}")
    df.columns = cols
    return limpar_df_tabela(df)


def valor_float_brasil(v):
    try:
        s = str(v).strip()
        if s in ("", "nan", "None"):
            return None
        # Se já é um número puro (ex: 0.1995 vindo da seção numérica do xlsx),
        # não faz replace de "." que quebraria o valor
        s_clean = s.replace("%", "").strip()
        # Detecta formato brasileiro (tem vírgula como decimal): "13.031,84"
        if "," in s_clean and s_clean.index(",") > s_clean.index(".") if "." in s_clean else False:
            # Formato BR: remove pontos de milhar, troca vírgula por ponto
            s_clean = s_clean.replace(".", "").replace(",", ".")
        elif "," in s_clean and "." not in s_clean:
            # Só vírgula: "13031,84" -> "13031.84"
            s_clean = s_clean.replace(",", ".")
        # else: formato puro com ponto: "13031.84" ou "0.1995" — usa direto
        return float(s_clean)
    except Exception:
        return None


def nome_arquivo_contas_valido(fname):
    s = str(fname or "").lower().strip()
    if s.startswith("~$"):
        return False
    if not (s.endswith(".xls") or s.endswith(".xlsx")):
        return False

    # nunca aceitar relatórios de margem ou arquivos auxiliares
    bloqueados = [
        "margem",
        "margens",
        "metas_vendas_mes_atual",
        "dashboard",
        "historico",
        "fechamentos",
        "credenciais",
        "config_meta",
        "cobrancas_log",
    ]
    if any(b in s for b in bloqueados):
        return False

    # aceitar apenas nomes típicos do Contas a Receber
    permitidos = [
        "relatorio_contas",
        "contas_pagar_receber",
        "contas_receber",
    ]
    return any(p in s for p in permitidos)


def _is_total_row(reg):
    """Detecta se uma linha é a linha de Total (tfoot ou primeira coluna contém "Total")."""
    # Verifica colunas conhecidas de identificação
    for k in ["Filial", "Vendedor", "Subgrupo", "Nome", "col_0"]:
        v = str(reg.get(k, "") or "").strip()
        if re.search(r"\btotal\b", v, re.IGNORECASE):
            return True
    # Verifica a primeira coluna de dados (não meta)
    for k, v in reg.items():
        if k.startswith("_"):
            continue
        sv = str(v or "").strip()
        if re.search(r"\btotal\b", sv, re.IGNORECASE):
            return True
        break  # só verifica a primeira coluna de dados
    return False


def df_meta_para_registros(df, spec, origem):
    saida = []
    for _, row in df.iterrows():
        reg = {}
        for c in df.columns:
            v = row[c]
            if isinstance(v, pd.Series):
                v = " | ".join("" if pd.isna(x) else str(x).strip() for x in v.tolist())
            reg[str(c)] = "" if pd.isna(v) else str(v).strip()
        reg["_meta_chave"] = spec["chave"]
        reg["_meta_label"] = spec["label"]
        reg["_meta_tipo"] = origem.get("tipo")
        reg["_meta_escopo"] = origem.get("escopo")
        reg["_meta_descricao"] = origem.get("descricao")
        reg["_meta_id"] = origem.get("id")
        reg["_meta_href"] = origem.get("href_resultado")
        # Marca linha de total (tfoot)
        reg["_is_total"] = _is_total_row(reg)
        for k in list(reg.keys()):
            if "META(R$)" in k.upper() or "REALIZADO(R$)" in k.upper() or "PROJETADO(R$)" in k.upper():
                reg[k + "_float"] = valor_float_brasil(reg[k])
            if "ATINGIDO" in k.upper():
                reg[k + "_float"] = valor_float_brasil(reg[k])
        saida.append(reg)
    return saida




def _extrair_totais_do_xlsx(xlsx_path):
    """
    Extrai os totais das abas de metas a partir das células finais do XLSX.
    Regra pedida pelo usuário:
      - venda_filial_meta           -> linha 11
      - servico_filial_ouro_fob     -> linha 10
      - venda_filial_subgrupo_20k   -> linha 10

    Mapeamento usado:
      B = Meta Total
      D = Atingido Total (%)
      E = Meta Período
      F = Realizado (valor exibido no card)
      H = Projetado

    Se a célula fixa não existir, faz fallback para localizar a última linha "Total"
    ou somar as linhas de filial.
    """
    from openpyxl import load_workbook

    def _br_float(v):
        try:
            s = str(v).strip()
            if s in ("", "None", "nan"):
                return 0.0
            s = s.replace("R$", "").replace("%", "").strip()
            if "," in s:
                s = s.replace(".", "").replace(",", ".")
            return float(s)
        except Exception:
            return 0.0

    def _sheet_by_prefix(wb, nome_base):
        for s in wb.sheetnames:
            if s == nome_base or s.startswith(nome_base[:20]):
                return wb[s]
        return None

    def _fallback_from_sheet(ws):
        # 1) tenta achar a última linha "Total"
        max_row = ws.max_row
        for r in range(max_row, 1, -1):
            a = str(ws.cell(r, 1).value or "").strip().upper()
            if a == "TOTAL":
                return {
                    "meta_total":  round(_br_float(ws.cell(r, 2).value), 2),
                    "real_total":  round(_br_float(ws.cell(r, 6).value), 2),
                    "ating_total": round(_br_float(ws.cell(r, 4).value), 2),
                    "meta_per":    round(_br_float(ws.cell(r, 5).value), 2),
                    "real_per":    round(_br_float(ws.cell(r, 6).value), 2),
                    "proj":        round(_br_float(ws.cell(r, 8).value), 2),
                }

        # 2) fallback final: soma linhas FILIAL
        meta_total = real_total = meta_per = proj = 0.0
        for r in range(2, max_row + 1):
            a = str(ws.cell(r, 1).value or "").strip().upper()
            if a.startswith("FILIAL"):
                meta_total += _br_float(ws.cell(r, 2).value)
                real_total += _br_float(ws.cell(r, 6).value)
                meta_per   += _br_float(ws.cell(r, 5).value)
                proj       += _br_float(ws.cell(r, 8).value)
        ating = round((real_total / meta_total * 100.0), 2) if meta_total > 0 else 0.0
        return {
            "meta_total": round(meta_total, 2),
            "real_total": round(real_total, 2),
            "ating_total": ating,
            "meta_per": round(meta_per, 2),
            "real_per": round(real_total, 2),
            "proj": round(proj, 2),
        }

    _MAP = {
        "venda_filial_meta":       {"sheet": "venda_filial_meta", "row": 11},
        "servico_filial_ouro_fob": {"sheet": "servico_filial_ouro_fob", "row": 10},
        "venda_filial_subgrupo_20k": {"sheet": "venda_filial_subgrupo_20k", "row": 10},
    }
    out = {}

    try:
        wb = load_workbook(xlsx_path, data_only=True)
    except Exception as e:
        print(f"⚠️ Não consegui abrir xlsx de metas: {e}")
        return out

    for chave, cfg in _MAP.items():
        ws = _sheet_by_prefix(wb, cfg["sheet"])
        if ws is None:
            print(f"⚠️ Sheet não encontrada no xlsx: {cfg['sheet']}")
            out[chave] = {"meta_total": 0.0, "real_total": 0.0, "ating_total": 0.0, "meta_per": 0.0, "real_per": 0.0, "proj": 0.0}
            continue

        r = int(cfg["row"])
        a = str(ws.cell(r, 1).value or "").strip().upper()
        # Usa a linha fixa se houver conteúdo e parecer ser a linha final/total
        if a in ("TOTAL",) or ws.cell(r, 2).value not in (None, ""):
            meta_total = round(_br_float(ws.cell(r, 2).value), 2)
            real_total = round(_br_float(ws.cell(r, 6).value), 2)
            ating_total = round(_br_float(ws.cell(r, 4).value), 2)
            meta_per = round(_br_float(ws.cell(r, 5).value), 2)
            real_per = round(_br_float(ws.cell(r, 6).value), 2)
            proj = round(_br_float(ws.cell(r, 8).value), 2)
            item = {
                "meta_total": meta_total,
                "real_total": real_total,
                "ating_total": ating_total,
                "meta_per": meta_per,
                "real_per": real_per,
                "proj": proj,
            }
        else:
            item = _fallback_from_sheet(ws)

        out[chave] = item
        print(f"✅ Total xlsx [{chave}]: meta={item['meta_total']:.2f}  real={item['real_total']:.2f}  ating={item['ating_total']:.2f}%  proj={item['proj']:.2f}")

    return out



def coletar_metas_vendas_mes_atual():
    primeiro_dia = hoje.replace(day=1).strftime("%d/%m/%Y")
    prox_mes = (hoje.replace(day=28) + timedelta(days=4)).replace(day=1)
    ultimo_dia = (prox_mes - timedelta(days=1)).strftime("%d/%m/%Y")

    print("\n📊 Iniciando coleta de metas/vendas do mês atual...")
    driver.get(URL + "/metas")
    wait.until(EC.presence_of_element_located((By.ID, "data_inicial_maior_igual")))
    set_input_value_safe(By.ID, "data_inicial_maior_igual", primeiro_dia)
    set_input_value_safe(By.ID, "data_final_menor_igual", ultimo_dia)
    clicar_primeiro_filtro_metas()
    time.sleep(2)

    linhas = extrair_linhas_tabela_metas()
    print(f"📋 Metas listadas na tela: {len(linhas)}")

    # IDs das metas mudam todo mês. Buscar sempre pelo Tipo + Escopo + Descrição da tela filtrada.
    specs = [
        {"chave": "venda_filial_meta", "label": "Venda / Filial / Meta Filial", "tipo": "Venda", "escopo": "Filial", "descricao_contem": ["META FILIAL"]},
        {"chave": "venda_filial_vendedor_meta", "label": "Venda / Filial-Vendedor / Meta Vendedor", "tipo": "Venda", "escopo": "Filial/Vendedor", "descricao_contem": ["META VENDEDOR"]},
        {"chave": "venda_filial_subgrupo_20k", "label": "Venda / Filial-Subgrupo / Caminhão 20K", "tipo": "Venda", "escopo": "Filial/Subgrupo", "descricao_contem": ["CAMINHAO", "20K"]},
        {"chave": "servico_filial_ouro_fob", "label": "Serviço / Filial / Ouro-FOB", "tipo": "Serviço", "escopo": "Filial", "descricao_contem": ["OURO", "FOB"]},
        {"chave": "servico_filial_vendedor_ouro_fob", "label": "Serviço / Filial-Vendedor / Ouro-FOB", "tipo": "Serviço", "escopo": "Filial/Vendedor", "descricao_contem": ["OURO", "FOB"]},
        {"chave": "venda_vendedor_subgrupo_20k", "label": "Venda / Vendedor-Subgrupo / Caminhão 20K", "tipo": "Venda", "escopo": "Vendedor/Subgrupo", "descricao_contem": ["CAMINHAO", "20K"]},
    ]

    resultados = {
        "coletado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "periodo_meta": {"data_inicial": primeiro_dia, "data_final": ultimo_dia},
        "lista_index": linhas,
        "metas": {}
    }

    xlsx_path = os.path.join(pasta, "metas_vendas_mes_atual.xlsx")
    json_path = os.path.join(pasta, "metas_vendas_mes_atual.json")

    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame(linhas).to_excel(writer, sheet_name="index_metas", index=False)

        for spec in specs:
            origem = escolher_melhor_linha_meta(linhas, spec)
            if not origem:
                print(f"⚠️ Meta não encontrada: {spec['label']}")
                resultados["metas"][spec["chave"]] = {"ok": False, "erro": "meta_nao_encontrada", "spec": spec}
                continue

            try:
                print(f"➡️ Abrindo resultados: {spec['label']} -> {origem['href_resultado']}")
                driver.get(origem["href_resultado"])
                time.sleep(2)
                df_result = encontrar_df_resultado_metas()
                df_result = limpar_df_tabela(df_result)
                print(f"   ↳ Colunas lidas: {list(df_result.columns)}")
                print(f"   ↳ Primeiras linhas: {len(df_result)}")
                resultados["metas"][spec["chave"]] = {
                    "ok": True,
                    "spec": spec,
                    "origem": origem,
                    "colunas": list(df_result.columns),
                    "linhas": df_meta_para_registros(df_result, spec, origem),
                }
                sheet = spec["chave"][:31]
                df_result.to_excel(writer, sheet_name=sheet, index=False)
                print(f"✅ {spec['label']}: {len(df_result)} linha(s)")
            except Exception as e:
                print(f"⚠️ Erro em {spec['label']}: {e}")
                resultados["metas"][spec["chave"]] = {
                    "ok": False,
                    "spec": spec,
                    "origem": origem,
                    "erro": str(e),
                }

    # ── Pós-coleta: relê o xlsx para extrair totais numéricos limpos ──────────────
    # O xlsx já está fechado aqui. Relemos e injetamos a linha Total em cada spec
    # que a precisa, garantindo que _sales_emp receba os valores corretos.
    _totais_xlsx = _extrair_totais_do_xlsx(xlsx_path)
    for _chave_t, _tot in _totais_xlsx.items():
        _meta_obj_t = resultados["metas"].get(_chave_t)
        if not isinstance(_meta_obj_t, dict) or not _meta_obj_t.get("ok"):
            continue
        _linhas_t = _meta_obj_t.get("linhas") or []
        # Remove qualquer linha Total anterior (evita duplicata)
        _linhas_t = [_r for _r in _linhas_t if not _r.get("_is_total")]
        # Constrói linha Total canônica com todos os campos _float prontos
        _total_reg = {
            "Filial": "Total",
            "Meta(R$) Total":           str(_tot["meta_total"]),
            "Realizado(R$) Total":       str(_tot["real_total"]),
            "Atingido Total":            f"{_tot['ating_total']:.2f}%",
            "Meta(R$) Período":          str(_tot["meta_per"]),
            "Realizado(R$) Período":     str(_tot["real_per"]),
            "Projetado(R$)":             str(_tot["proj"]),
            "Meta(R$) Total_float":      _tot["meta_total"],
            "Realizado(R$) Total_float": _tot["real_total"],
            "Atingido Total_float":      _tot["ating_total"],
            "Meta(R$) Período_float":    _tot["meta_per"],
            "Realizado(R$) Período_float": _tot["real_per"],
            "Projetado(R$)_float":       _tot["proj"],
            "_is_total": True,
            "_meta_chave": _chave_t,
        }
        _linhas_t.append(_total_reg)
        resultados["metas"][_chave_t]["linhas"] = _linhas_t
    # ── Fim do pós-coleta ──────────────────────────────────────────────────────────

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    print(f"💾 Metas JSON: {json_path}")
    print(f"💾 Metas XLSX: {xlsx_path}")
    return {"json_path": json_path, "xlsx_path": xlsx_path, "dados": resultados}


# =========================================
# 📈 RELATÓRIO DE MARGEM BRUTA / RENTABILIDADE
# Coleta 2 relatórios do SGI:
#   1) Lucratividade por FILIAL
#   2) Lucratividade por VENDEDOR
# Alimenta o dashboard com Margem Bruta (%) do mês atual.
# =========================================

def _select_by_text_contains(select_el, texto_alvo):
    texto_alvo_n = normalizar_texto_match(texto_alvo)
    sel = Select(select_el)
    for opt in sel.options:
        if texto_alvo_n in normalizar_texto_match(opt.text):
            sel.select_by_visible_text(opt.text)
            try:
                driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", select_el)
            except Exception:
                pass
            return True
    return False


def _label_contains_xpath(txt):
    return f"//label[contains(normalize-space(.),'{txt}')] | //strong[contains(normalize-space(.),'{txt}')] | //div[contains(normalize-space(.),'{txt}') and not(*)]"


def _find_relatorio_block_by_label(label_texto):
    ultimo = None
    xp = _label_contains_xpath(label_texto)
    candidatos = [
        f"({xp})[1]/ancestor::div[contains(@class,'row') or contains(@class,'col') or contains(@class,'form-group')][1]",
        f"({xp})[1]/parent::*",
        f"({xp})[1]/ancestor::div[1]",
    ]
    for cp in candidatos:
        try:
            bloco = wait.until(EC.presence_of_element_located((By.XPATH, cp)))
            if bloco:
                return bloco
        except Exception as e:
            ultimo = e
    raise ultimo or Exception(f"Bloco do label {label_texto} não encontrado")


def _set_relatorio_periodo_emissao(data_inicial, data_final):
    bloco = _find_relatorio_block_by_label('Período de Emissão')
    try:
        sels = [s for s in bloco.find_elements(By.TAG_NAME, 'select') if s.is_displayed()]
        if sels:
            try:
                Select(sels[0]).select_by_value('intervalo')
            except Exception:
                _select_by_text_contains(sels[0], 'Intervalo')
            driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", sels[0])
    except Exception:
        pass

    inputs = [i for i in bloco.find_elements(By.XPATH, ".//input[not(@type='hidden')]") if i.is_displayed()]
    if len(inputs) < 2:
        # fallback geral: pega os 2 primeiros inputs visíveis de data/texto do formulário
        form = wait.until(EC.presence_of_element_located((By.XPATH, "//form[contains(@action,'relatorio_margens_brutas')]")))
        inputs = [i for i in form.find_elements(By.XPATH, ".//input[not(@type='hidden')]") if i.is_displayed()]
    if len(inputs) < 2:
        raise Exception('Não encontrei os 2 campos de data do relatório de margens')

    for el, valor in [(inputs[0], data_inicial), (inputs[1], data_final)]:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        try:
            el.click()
            el.send_keys(Keys.CONTROL, 'a')
            el.send_keys(Keys.DELETE)
            el.send_keys(valor)
        except Exception:
            driver.execute_script("arguments[0].value = arguments[1];", el, valor)
        driver.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", el)
        driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", el)


def _select_relatorio_por_label(label_texto, texto_opcao=None, value=None):
    bloco = _find_relatorio_block_by_label(label_texto)
    selects = [s for s in bloco.find_elements(By.TAG_NAME, 'select') if s.is_displayed()]
    if not selects:
        # fallback: primeiro select visível após o label no DOM
        xp = f"({_label_contains_xpath(label_texto)})[1]/following::select[1]"
        selects = [wait.until(EC.presence_of_element_located((By.XPATH, xp)))]
    el = selects[0]
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    sel = Select(el)
    if value is not None:
        try:
            sel.select_by_value(str(value))
        except Exception:
            pass
    if texto_opcao is not None:
        if not _select_by_text_contains(el, texto_opcao):
            try:
                sel.select_by_visible_text(texto_opcao)
            except Exception:
                # último fallback: tentativa por option text normalizado
                achou = False
                alvo = normalizar_texto_match(texto_opcao)
                for opt in sel.options:
                    if alvo == normalizar_texto_match(opt.text):
                        sel.select_by_visible_text(opt.text)
                        achou = True
                        break
                if not achou:
                    raise Exception(f'Opção {texto_opcao} não encontrada em {label_texto}')
    driver.execute_script("arguments[0].dispatchEvent(new Event('change', {bubbles:true}));", el)
    return el



def _tratar_valor_margem(v):
    try:
        s = str(v).strip()
        if s in ("", "nan", "None"):
            return 0.0
        s = s.replace("R$", "").replace("%", "").strip()
        s = s.replace(".", "").replace(",", ".")
        return float(s)
    except Exception:
        return 0.0


def _limpar_nome_margem(nome):
    s = str(nome or "").strip()
    s = re.sub(r"^Vendedor:\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^\d+\s*-\s*", "", s)
    s = re.sub(r"^C\.\d+\s*-\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(GER\s*F\d+\)\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*\(F\d+\)\s*$", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_key_margem(nome):
    s = _limpar_nome_margem(nome).upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _filial_key_from_text(texto):
    s = str(texto or "").upper()
    m = re.search(r"FILIAL\s*0*(\d{1,3})", s)
    if not m:
        return ""
    n = int(m.group(1))
    return "FDEP" if n in (90, 99) else f"F{n}"


def _select_all_multiselect_by_label(label_texto):
    abrir_multiselect_por_label(label_texto, timeout=20)
    xpath_ul = f"//label[contains(normalize-space(.),'{label_texto}')]/following::ul[1]"
    container = wait.until(EC.presence_of_element_located((By.XPATH, xpath_ul)))
    driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'nearest'});", container)
    time.sleep(0.5)
    checkboxes = container.find_elements(By.XPATH, ".//input[@type='checkbox']")
    for c in checkboxes:
        try:
            if not c.is_selected():
                driver.execute_script("arguments[0].click();", c)
                time.sleep(0.05)
        except Exception:
            pass
    driver.execute_script("document.body.click();")
    time.sleep(0.5)
    return len(checkboxes)


def _nome_arquivo_margem_valido(fname):
    s = str(fname or '').lower()
    if s.startswith('~$'):
        return False
    if not (s.endswith('.xls') or s.endswith('.xlsx')):
        return False
    return ('margem' in s) or ('margens' in s)


def _ler_xls_ou_xlsx(caminho):
    erros = []
    for engine in ('openpyxl', None):
        try:
            if engine:
                return pd.read_excel(caminho, header=None, engine=engine)
            return pd.read_excel(caminho, header=None)
        except Exception as e:
            erros.append(f'read_excel[{engine}]: {e}')
    try:
        tabelas = pd.read_html(caminho, decimal=',', thousands='.')
        if tabelas:
            return tabelas[0]
    except Exception as e:
        erros.append(f'read_html: {e}')
    raise Exception('Não consegui ler XLS/XLSX de margem: ' + ' | '.join(erros))


def _parse_relatorio_margem_xls(caminho, tipo):
    df_m = _ler_xls_ou_xlsx(caminho).fillna('')
    filiais = {}
    vendedores = {}
    empresa = {}

    for _, row in df_m.iterrows():
        vals = [str(x).strip() for x in row.tolist()]
        vals += [''] * max(0, 8 - len(vals))

        if tipo == 'filial':
            filial_txt = vals[0]
            norm0 = normalizar_texto_match(filial_txt)
            if not filial_txt or norm0 == 'FILIAL':
                continue
            if norm0 == 'TOTAL':
                empresa = {
                    'label': 'TOTAL',
                    'margem_bruta_pct': round(_tratar_valor_margem(vals[5]), 2),
                    'valor_total_liquido': _tratar_valor_margem(vals[1]),
                    'valor_total': _tratar_valor_margem(vals[2]),
                    'custo_total': _tratar_valor_margem(vals[3]),
                    'margem_bruta_valor': _tratar_valor_margem(vals[4]),
                    'markup_realizado': _tratar_valor_margem(vals[6]) if len(vals) > 6 else 0.0,
                    'pmr_vendas_prazo': _tratar_valor_margem(vals[7]) if len(vals) > 7 else 0.0,
                }
                continue
            if 'FILIAL' not in norm0:
                continue
            fk = _filial_key_from_text(filial_txt)
            if not fk:
                continue
            margem_pct = _tratar_valor_margem(vals[5])
            filiais[fk] = {
                'filial': fk,
                'label': filial_txt,
                'margem_bruta_pct': round(margem_pct, 2),
                'valor_total_liquido': _tratar_valor_margem(vals[1]),
                'valor_total': _tratar_valor_margem(vals[2]),
                'custo_total': _tratar_valor_margem(vals[3]),
                'margem_bruta_valor': _tratar_valor_margem(vals[4]),
                'markup_realizado': _tratar_valor_margem(vals[6]) if len(vals) > 6 else 0.0,
            }

        else:
            filial_txt = vals[0]
            vendedor_txt = vals[1]
            if not vendedor_txt or normalizar_texto_match(vendedor_txt) in ('VENDEDOR', 'TOTAL'):
                continue
            fk = _filial_key_from_text(filial_txt)
            if not fk:
                continue
            nome = _limpar_nome_margem(vendedor_txt)
            if not nome:
                continue
            margem_pct = _tratar_valor_margem(vals[6])
            key = f'{_norm_key_margem(nome)}_{fk}'
            vendedores[key] = {
                'nome': nome,
                'filial': fk,
                'key': key,
                'label_filial': filial_txt,
                'margem_bruta_pct': round(margem_pct, 2),
                'valor_total_liquido': _tratar_valor_margem(vals[2]),
                'valor_total': _tratar_valor_margem(vals[3]),
                'custo_total': _tratar_valor_margem(vals[4]),
                'margem_bruta_valor': _tratar_valor_margem(vals[5]),
                'markup_realizado': _tratar_valor_margem(vals[7]) if len(vals) > 7 else 0.0,
            }

    return {'filiais': filiais, 'vendedores': vendedores, 'empresa': empresa}


def _gerar_relatorio_margem(tipo):
    primeiro_dia = hoje.replace(day=1).strftime("%d/%m/%Y")
    prox_mes = (hoje.replace(day=28) + timedelta(days=4)).replace(day=1)
    ultimo_dia = (prox_mes - timedelta(days=1)).strftime("%d/%m/%Y")

    driver.get(URL + "/relatorio_margens_brutas")
    wait.until(EC.presence_of_element_located((By.ID, "gerar")))
    time.sleep(1.5)
    esperar_sumir_overlays(10)

    _set_relatorio_periodo_emissao(primeiro_dia, ultimo_dia)

    try:
        _select_relatorio_por_label("Tipo de Custo", texto_opcao="Custo Médio Gerencial")
    except Exception as e:
        print(f"⚠️ Não consegui selecionar Tipo de Custo automaticamente: {e}")

    try:
        _select_relatorio_por_label("Lucratividade por", texto_opcao=("Filial" if tipo == "filial" else "Vendedor"))
    except Exception as e:
        print(f"⚠️ Não consegui selecionar Lucratividade por {tipo}: {e}")

    try:
        total_ops = _select_all_multiselect_by_label("Operações de Devolução")
        print(f"✅ Operações de Devolução: {total_ops} opções marcadas")
    except Exception as e:
        print(f"⚠️ Não consegui marcar Operações de Devolução: {e}")

    try:
        Select(wait.until(EC.presence_of_element_located((By.ID, "_formato")))).select_by_value("xls")
        print("✅ Formato XLS para Margem Bruta")
    except Exception as e:
        print(f"⚠️ Não consegui selecionar formato XLS de Margem Bruta: {e}")

    arquivos_antes = set(f for f in os.listdir(download_dir) if _nome_arquivo_margem_valido(f))

    gerar_btn = wait.until(EC.presence_of_element_located((By.ID, 'gerar')))
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", gerar_btn)
    esperar_sumir_overlays(10)
    try:
        wait.until(EC.element_to_be_clickable((By.ID, 'gerar'))).click()
    except Exception:
        driver.execute_script("arguments[0].click();", gerar_btn)
    print(f"📈 Gerando Margem Bruta por {tipo.upper()}...")

    caminho = None
    for _ in range(60):
        time.sleep(2)
        baixando = any(f.endswith('.crdownload') or f.endswith('.tmp') for f in os.listdir(download_dir))
        if baixando:
            continue
        novos = set(f for f in os.listdir(download_dir) if _nome_arquivo_margem_valido(f)) - arquivos_antes
        if novos:
            caminho = max([os.path.join(download_dir, f) for f in novos], key=os.path.getctime)
            break

    if not caminho:
        todos = [os.path.join(download_dir, f) for f in os.listdir(download_dir) if _nome_arquivo_margem_valido(f)]
        if not todos:
            raise Exception('Nenhum arquivo XLS/XLSX de margem foi baixado')
        caminho = max(todos, key=os.path.getctime)
        print(f"⚠️ Usando último arquivo de margem encontrado: {caminho}")
    else:
        print(f"✅ Download margem OK: {caminho}")

    return _parse_relatorio_margem_xls(caminho, tipo)


def coletar_margens_brutas_mes_atual():
    print("\n📈 Iniciando coleta de Margem Bruta/Rentabilidade do mês atual...")
    json_path = os.path.join(pasta, "margens_brutas_mes_atual.json")
    xlsx_path = os.path.join(pasta, "margens_brutas_mes_atual.xlsx")
    resultados = {
        "coletado_em": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "periodo": {
            "data_inicial": hoje.replace(day=1).strftime("%d/%m/%Y"),
            "data_final": ((hoje.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).strftime("%d/%m/%Y"),
        },
        "filiais": {},
        "vendedores": {},
        "empresa": {},
        "ok": False,
    }

    try:
        res_fil = _gerar_relatorio_margem("filial")
        resultados["filiais"] = res_fil.get("filiais", {})
        resultados["empresa"] = res_fil.get("empresa", {})
        print(f"✅ Margem por FILIAL: {len(resultados['filiais'])} registro(s)")
    except Exception as e:
        resultados["erro_filial"] = str(e)
        print(f"⚠️ Erro ao coletar margem por FILIAL: {e}")

    try:
        res_vend = _gerar_relatorio_margem("vendedor")
        resultados["vendedores"] = res_vend.get("vendedores", {})
        print(f"✅ Margem por VENDEDOR: {len(resultados['vendedores'])} registro(s)")
    except Exception as e:
        resultados["erro_vendedor"] = str(e)
        print(f"⚠️ Erro ao coletar margem por VENDEDOR: {e}")

    resultados["ok"] = bool(resultados.get("filiais") or resultados.get("vendedores"))

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)

    try:
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            pd.DataFrame(list(resultados.get("filiais", {}).values())).to_excel(writer, sheet_name="filiais", index=False)
            pd.DataFrame([resultados.get("empresa", {})]).to_excel(writer, sheet_name="empresa", index=False)
            pd.DataFrame(list(resultados.get("vendedores", {}).values())).to_excel(writer, sheet_name="vendedores", index=False)
    except Exception as e:
        print(f"⚠️ Não consegui salvar XLSX de margens: {e}")
        xlsx_path = None

    print(f"💾 Margens JSON: {json_path}")
    if xlsx_path:
        print(f"💾 Margens XLSX: {xlsx_path}")
    return {"json_path": json_path, "xlsx_path": xlsx_path, "dados": resultados}



# ===== LOGIN
driver.get(URL)
time.sleep(8)
print("TITLE:", driver.title)
print("URL ATUAL:", driver.current_url)

campo_usuario = None
seletores_usuario = [
    (By.NAME, "usuario"),
    (By.ID, "usuario"),
    (By.CSS_SELECTOR, "input[name='usuario']"),
    (By.CSS_SELECTOR, "input[id='usuario']"),
    (By.XPATH, "//input[contains(@name,'usuario') or contains(@id,'usuario')]"),
    (By.XPATH, "//input[@type='text']"),
]

for by, sel in seletores_usuario:
    try:
        campo_usuario = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((by, sel))
        )
        if campo_usuario:
            print(f"✅ Campo usuário encontrado em: {by} = {sel}")
            break
    except Exception:
        pass

if not campo_usuario:
    print("❌ Campo usuário não encontrado")
    print("URL:", driver.current_url)
    print("TITLE:", driver.title)
    try:
        print(driver.page_source[:5000])
    except Exception:
        pass
    try:
        driver.save_screenshot(os.path.join(download_dir, "debug_login.png"))
    except Exception:
        pass
    raise Exception("Campo usuário não encontrado na tela de login")

try:
    campo_usuario.click()
    campo_usuario.send_keys(Keys.CONTROL, "a")
    campo_usuario.send_keys(Keys.DELETE)
except Exception:
    pass
campo_usuario.send_keys(LOGIN)

senha_field = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='password']")))
senha_field.send_keys(SENHA)
senha_field.send_keys(Keys.ENTER)

try:
    wait.until(EC.element_to_be_clickable((By.ID, "botao_prosseguir_informa_local_trabalho"))).click()
    print("✅ Filial OK")
except Exception:
    print("⚠️ Tela de filial não apareceu")
time.sleep(5)

# ===== RELATÓRIO
driver.get(URL + "/relatorio_contas_receber")
wait.until(EC.presence_of_element_located((By.ID, "data_vencimento_inicial")))
Select(driver.find_element(By.ID, "data_vencimento")).select_by_value("intervalo")
time.sleep(2)

inicio = driver.find_element(By.ID, "data_vencimento_inicial")
driver.execute_script("arguments[0].value = '';", inicio)
inicio.send_keys(data_inicio)

fim = driver.find_element(By.ID, "data_vencimento_final")
driver.execute_script("arguments[0].value = '';", fim)
fim.send_keys(data_fim)

# Filiais
try:
    driver.find_element(By.XPATH, "//label[contains(text(),'Filiais')]/following::button[1]").click()
    time.sleep(2)
    filiais_sel = ["1", "2", "3", "4", "5", "6", "7", "8", "10"]
    container = driver.find_element(By.XPATH, "//label[contains(text(),'Filiais')]/following::ul[1]")

    for c in container.find_elements(By.XPATH, ".//input[@type='checkbox']"):
        if c.get_attribute("value") in filiais_sel:
            driver.execute_script("arguments[0].click();", c)

    print("✅ Filiais OK")
    time.sleep(3)
except Exception as e:
    print(f"⚠️ Erro filiais: {e}")

# 🔥 PULA TOTALIZAR POR VENDEDOR
# O XLS já virá totalizado corretamente, então vai direto pro botão "+"
try:
    clicar_seguro_xpath("//span[contains(@class,'glyphicon-plus')]", timeout=20)
    print("✅ Mais filtros")
    time.sleep(2)
except Exception as e:
    print(f"⚠️ Não abriu +: {e}")

# ===== FORMAS DE PAGAMENTO
try:
    marcar_multiselect_por_label("Forma de Pagamento", ["3", "47", "17"], timeout=20, limpar_antes=True)
    print("✅ Formas OK")
    time.sleep(2)
except Exception as e:
    print(f"⚠️ Erro formas: {e}")

try:
    Select(wait.until(EC.presence_of_element_located((By.ID, "_formato")))).select_by_value("xls")
    print("✅ Formato XLS")
    time.sleep(2)
except Exception as e:
    print(f"⚠️ Erro formato XLS: {e}")

# Conta Caixa já vem no relatório automaticamente — sem ação Selenium necessária

# ===== GERAR E AGUARDAR DOWNLOAD
arquivos_antes = set(
    f for f in os.listdir(download_dir)
    if nome_arquivo_contas_valido(f)
)
driver.find_element(By.ID, "gerar").click()
print("📥 Gerando XLS... aguardando download...")

caminho = None
for _ in range(60):
    time.sleep(2)
    baixando = any(f.endswith(".crdownload") or f.endswith(".tmp") for f in os.listdir(download_dir))
    if baixando:
        print("⏳ Ainda baixando..."); continue
    novos = set(
        f for f in os.listdir(download_dir)
        if nome_arquivo_contas_valido(f)
    ) - arquivos_antes
    if novos:
        caminho = max([os.path.join(download_dir, f) for f in novos], key=os.path.getctime)
        print(f"✅ Download OK: {caminho}"); break

if not caminho:
    print(f"📂 download_dir: {download_dir}")
    try:
        print("📂 Arquivos atuais:", os.listdir(download_dir))
    except Exception as e:
        print(f"⚠️ Não consegui listar download_dir: {e}")

    driver.quit()
    raise Exception("Nenhum XLS válido de Contas a Receber foi baixado nesta execução")

# ===== LEITURA DO XLS
if not nome_arquivo_contas_valido(os.path.basename(caminho)):
    raise Exception(f"Arquivo selecionado não é o relatório de contas a receber: {caminho}")
df_raw = pd.read_excel(caminho, header=None, engine="openpyxl")
print(f"📋 {df_raw.shape[0]} linhas lidas")

metas_vendas_info = {"json_path": None, "xlsx_path": None, "dados": {}}
try:
    metas_vendas_info = coletar_metas_vendas_mes_atual()
except Exception as e:
    print(f"⚠️ Erro ao coletar metas/vendas do SGI: {e}")

margens_brutas_info = {"json_path": None, "xlsx_path": None, "dados": {}}
try:
    margens_brutas_info = coletar_margens_brutas_mes_atual()
except Exception as e:
    print(f"⚠️ Erro ao coletar Margem Bruta/Rentabilidade do SGI: {e}")

# ===== MAPA DE COLUNAS DO XLS NOVO
COL = {
    "filial": 0,
    "cliente": 1,
    "contato": 2,
    "conta_caixa": 3,
    "restricao_credito": 4,
    "historico": 5,
    "num_lancamento": 6,
    "forma_pagamento": 7,
    "prev_real": 8,
    "num_titulo": 9,
    "num_parcela": 10,
    "emissao": 11,
    "vencimento": 12,
    "pagamento": 13,
    "nominal": 14,
    "pendente": 15,
    "pago_total": 16,
    "juros_total": 17,
    "avalistas": 18,
}

# ===== HELPERS
def tratar_valor(v):
    try:
        v = str(v).strip()
        if v in ("","nan","None"): return 0.0
        return float(v.replace(".","").replace(",","."))
    except:
        return 0.0


def extrair_filial_nome(nome):
    """
    Gerente: (GERFx) → filial='Fx', is_gerente=True
    Ativo:   (Fx)    → filial='Fx', is_gerente=False
    Inativo: sem tag → None, False
    """
    s = str(nome).upper()
    m = re.search(r"\(GER\s*F(\d+)\)", s)
    if m: return f"F{int(m.group(1))}", True
    m = re.search(r"\(F(\d+)\)", s)
    if m: return f"F{int(m.group(1))}", False
    return None, False


def limpar_nome_erp(texto):
    """Remove prefixo numérico do ERP"""
    s = re.sub(r"^Vendedor:\s*", "", str(texto).strip(), flags=re.IGNORECASE)
    s = re.sub(r"^\d+\s*-\s*", "", s)
    s = re.sub(r"^C\.\d+\s*-\s*", "", s, flags=re.IGNORECASE)
    return s.strip()


def limpar_nome_display(nome):
    """Remove sufixo (Fx) ou (GERFx)"""
    s = re.sub(r"\s*\(GER\s*F\d+\)\s*$", "", str(nome).strip(), flags=re.IGNORECASE)
    s = re.sub(r"\s*\(F\d+\)\s*$",       "", s,                  flags=re.IGNORECASE)
    return s.strip()


def normalizar_login(texto):
    """Primeiro token 100% letras"""
    for token in str(texto).strip().split():
        if token.isalpha():
            nfkd = unicodedata.normalize("NFKD", token)
            return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()

    nfkd = unicodedata.normalize("NFKD", str(texto).strip())
    sem  = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-zA-Z]","",sem)[:10].lower() or "vendedor"


# =========================================
# 🔥 NOVOS HELPERS (WHATSAPP + CONTATO)
# =========================================

def extrair_telefones(texto):
    """
    Extrai múltiplos números de telefone de um campo
    """
    s = str(texto or "").strip()

    if not s or s.lower() in ("nan", "none"):
        return []

    # separa por ; , / |
    partes = re.split(r"[;,/|]+", s)

    telefones = []

    for parte in partes:
        numero = "".join(re.findall(r"\d", parte))

        if len(numero) >= 10:
            if not numero.startswith("55"):
                numero = "55" + numero

            telefones.append(numero)

    # remove duplicados mantendo ordem
    vistos = set()
    unicos = []

    for n in telefones:
        if n not in vistos:
            vistos.add(n)
            unicos.append(n)

    return unicos


def primeiro_nome_cliente(nome):
    nome = str(nome or "").strip()
    if not nome:
        return "Cliente"
    return nome.split()[0].title()


def mensagem_cobranca_padrao(cliente, vencimento, valor_pendente):
    primeiro_nome = primeiro_nome_cliente(cliente)

    valor_fmt = f"R$ {float(valor_pendente):,.2f}"
    valor_fmt = valor_fmt.replace(",", "X").replace(".", ",").replace("X", ".")

    return (
        f"Olá, {primeiro_nome} tudo bem? Aqui é da Lojas MDL - Móveis do Lar. "
        f"Passando para lembrar que tem uma parcelinha vencida na data de {vencimento}, "
        f"no valor de {valor_fmt}. Caso o pagamento já tenha sido realizado, por gentileza, "
        f"desconsidere esta mensagem. Se precisar do boleto, chave PIX ou tiver qualquer dúvida, "
        f"fico à disposição para ajudar. Agradecemos a atenção e desejamos um excelente dia."
    )

# ===== PARSE LINHA A LINHA
registros = []
vendedor_atual = None

for i in range(len(df_raw)):
    row = df_raw.iloc[i]
    cel0 = str(row[COL["filial"]]).strip()

    if "Vendedor:" in cel0:
        vendedor_atual = limpar_nome_erp(cel0)
        continue

    if vendedor_atual and cel0.upper().startswith("FILIAL"):
        m = re.search(r"FILIAL\s+(\d+)", cel0.upper())
        if not m:
            continue

        pendente = tratar_valor(row[COL["pendente"]])
        pago = tratar_valor(row[COL["pago_total"]])

        registros.append({
            "vendedor": vendedor_atual,
            "filial_num": int(m.group(1)),
            "pendente": pendente,
            "pago": pago,
        })





df = pd.DataFrame(registros)

# Totaliza BRUTO (deve bater com "Total Geral" do arquivo)
total_bruto_p  = df["pendente"].sum()
total_bruto_pg = df["pago"].sum()
print(f"\n📊 TOTAL BRUTO (deve bater com Total Geral do XLS):")
print(f"   Pendente : R$ {total_bruto_p:>12,.2f}")
print(f"   Pago     : R$ {total_bruto_pg:>12,.2f}")

# ===== IDENTIFICAR TIPO DE CADA VENDEDOR
df[["filial_vendedor","is_gerente"]] = df["vendedor"].apply(
    lambda n: pd.Series(extrair_filial_nome(n))
)

# Filial do registro (onde está no ERP)
df["filial_erp"] = df["filial_num"].apply(
    lambda n: "FDEP" if n in (90,99) else f"F{n}"
)

# Filial definitiva:
# - ativo/gerente → usa a filial do nome (ex: SANDY (F1) → F1)
# - inativo       → usa a filial do ERP (onde estão os créditos)
df["filial"] = df.apply(
    lambda r: r["filial_vendedor"] if r["filial_vendedor"] else r["filial_erp"],
    axis=1
)

# Separa ANTES de agrupar para não perder inativos com múltiplas filiais
df_ativos_raw   = df[df["filial_vendedor"].notna()].copy()
df_inativos_raw = df[df["filial_vendedor"].isna()].copy()

# Lookup de filial real para inativos (usando df já processado)
_filial_inativo_lookup = {}
_nomes_fdep = set()
for _, _rr in df_inativos_raw.iterrows():
    _nd_i = limpar_nome_display(limpar_nome_erp(str(_rr["vendedor"])))
    _fi   = str(_rr.get("filial_erp","")).strip()
    if _fi and _fi not in ("nan","None",""):
        if _fi == "FDEP":
            _nomes_fdep.add(_nd_i)
        _filial_inativo_lookup[_nd_i] = _fi


# ===== PARSE CLIENTES E RECEBIMENTOS POR FAIXA
# Lógica:
#   recebido_faixa  = pago nos títulos com pagto > data_corte (delta do período)
#                     inclui ativos + inativos + FDEP (para rateio na meta)
#   clientes_cobrar = títulos PENDENTES por faixa (para cobrança)
from datetime import datetime as _dt
_hoje = _dt.now()

def _parse_data(v):
    try:
        s = str(v).strip()
        if s in ("nan", "None", ""):
            return None
        return _dt.strptime(s, "%d/%m/%Y")
    except:
        return None

clientes_cobrar   = []
recebido_faixa    = {}   # {key: {grave, alerta, atencao, is_ativo, is_fdep, filial}}
clientes_key_hoje = set()
_vend_cli_atual   = None

# Data de corte para recebimentos do período:
# 1. Prioridade: snapshot_referencia_YYYY-MM.json
# 2. Se não existir: snapshot de ontem
# 3. Fallback: snapshot mais recente disponível
import json as _json_tmp

_mes_atual_str   = _dt.now().strftime("%Y-%m")
_ref_path        = os.path.join(pasta, "cache_historico", f"snapshot_referencia_{_mes_atual_str}.json")
_ontem_str_parse = (_dt.now() - __import__("datetime").timedelta(days=1)).strftime("%Y-%m-%d")
_snap_ontem_path = os.path.join(pasta, "cache_historico", f"snapshot_{_ontem_str_parse}.json")

if os.path.exists(_ref_path):
    with open(_ref_path, encoding="utf-8") as _f_tmp:
        _ref_tmp = _json_tmp.load(_f_tmp)
    _data_corte_parse = _dt.strptime(_ref_tmp.get("data", f"{_mes_atual_str}-01"), "%Y-%m-%d")
    print(f"📅 Referência do mês (base): {_data_corte_parse.strftime('%d/%m/%Y')} → acumulando desde início do mês")
elif os.path.exists(_snap_ontem_path):
    with open(_snap_ontem_path, encoding="utf-8") as _f_tmp:
        _snap_ontem_tmp = _json_tmp.load(_f_tmp)
    _data_corte_parse = _dt.strptime(_snap_ontem_tmp.get("data", _ontem_str_parse), "%Y-%m-%d")
    print(f"📅 Data de corte (ontem): {_data_corte_parse.strftime('%d/%m/%Y')}")
else:
    _data_corte_parse = None
    for _d in range(1, 60):
        _d_str = (_dt.now() - __import__("datetime").timedelta(days=_d)).strftime("%Y-%m-%d")
        _p = os.path.join(pasta, "cache_historico", f"snapshot_{_d_str}.json")
        if os.path.exists(_p):
            _data_corte_parse = _dt.strptime(_d_str, "%Y-%m-%d")
            break
    if _data_corte_parse is None:
        _data_corte_parse = _dt(_dt.now().year, _dt.now().month, 1)
    print(f"📅 Data de corte (snapshot disponível): {_data_corte_parse.strftime('%d/%m/%Y')}")

for _i in range(len(df_raw)):
    _row = df_raw.iloc[_i]

    _c0 = str(_row[COL["filial"]]).strip()
    _c1 = str(_row[COL["cliente"]]).strip()
    _contato = str(_row[COL["contato"]]).strip() if len(_row) > COL["contato"] else ""
    _avalista = str(_row[COL["avalistas"]]).strip() if len(_row) > COL["avalistas"] else ""

    if "Vendedor:" in _c0:
        _vend_cli_atual = limpar_nome_erp(_c0)
        continue

    if _c1 in ("nan", "", "Cliente", "Filial"):
        continue
    if _c0.upper().startswith("FILIAL") and _c1 in ("nan", "", "Cliente", "Filial"):
        continue
    if not _vend_cli_atual:
        continue

    _venc     = _parse_data(_row[COL["vencimento"]])
    _pagto    = _parse_data(_row[COL["pagamento"]])
    _pendente = tratar_valor(_row[COL["pendente"]])
    _pago_val = tratar_valor(_row[COL["pago_total"]])

    if not _venc:
        continue

    # 🔥 IGNORA CONTA CAIXA 100
    if str(_row[COL["conta_caixa"]]).strip() == "Caixa Filial 100":
        continue

    _dias_venc = (_hoje - _venc).days

    if _dias_venc >= 60:
        _faixa = "grave"
    elif 30 <= _dias_venc < 60:
        _faixa = "alerta"
    elif 15 <= _dias_venc < 30:
        _faixa = "atencao"
    else:
        _faixa = None

    _fv, _ig = extrair_filial_nome(_vend_cli_atual)
    _nd_parse = limpar_nome_display(_vend_cli_atual)

    # =========================================
    # DEFINIÇÃO DE FILIAL
    # =========================================
    if _fv is not None:
        _fv_key   = _fv.strip().upper()
        _is_ativo = True
        _is_fdep  = False
    else:
        _fv_lookup = _filial_inativo_lookup.get(_nd_parse, "")

        # tenta extrair do nome
        if not _fv_lookup and "F" in _vend_cli_atual:
            _fv_lookup, _ = extrair_filial_nome(_vend_cli_atual)

        # tenta via cliente
        if not _fv_lookup:
            _fv_lookup = _filial_inativo_lookup.get(_c1[:30], "")

        if _fv_lookup == "FDEP" or _nd_parse in _nomes_fdep:
            _fv_key   = "FDEP"
            _is_ativo = False
            _is_fdep  = True
        elif _fv_lookup:
            _fv_key   = str(_fv_lookup).strip().upper()
            _is_ativo = False
            _is_fdep  = False
        else:
            _filial_txt = str(_row[COL["filial"]]).upper()
            m_fil = re.search(r"FILIAL\s*(\d+)", _filial_txt)

            if m_fil:
                _fv_key = f"F{int(m_fil.group(1))}"
            else:
                _fv_key = "OUTROS"

            _is_ativo = False
            _is_fdep  = False

    _fv_key = str(_fv_key).strip().upper()
    _key_vend = f"{_nd_parse}_{_fv_key}"

    # =========================================
    # RECEBIMENTOS
    # =========================================
    if _faixa and _pagto and _pago_val > 0 and _pagto > _data_corte_parse:
        if _key_vend not in recebido_faixa:
            recebido_faixa[_key_vend] = {
                "grave": 0.0,
                "alerta": 0.0,
                "atencao": 0.0,
                "filial": _fv_key,
                "is_ativo": _is_ativo,
                "is_fdep": _is_fdep,
                "vendedor_nome": _nd_parse,
            }

        recebido_faixa[_key_vend][_faixa] += _pago_val

    # =========================================
    # CLIENTES A COBRAR
    # =========================================
    if _faixa and _pendente > 0:
        _titulo  = str(_row[COL["num_titulo"]]).strip()
        _parcela = str(_row[COL["num_parcela"]]).strip()

        _titulo_key = f"{_c1[:30]}_{_titulo}_{_parcela}"
        clientes_key_hoje.add(_titulo_key)

        _telefones = extrair_telefones(_contato)
        _mensagem = mensagem_cobranca_padrao(
            cliente=_c1[:50],
            vencimento=str(_row[COL["vencimento"]]).strip(),
            valor_pendente=_pendente,
        )

        clientes_cobrar.append({
            "vendedor": _vend_cli_atual,
            "filial": _fv_key,
            "is_ativo": _is_ativo,
            "is_fdep": _is_fdep,
            "cliente": _c1[:50],
            "contato": _contato,
            "telefones": _telefones,
            "avalista": _avalista[:50],
            "restricao": str(_row[COL["restricao_credito"]])[:40],
            "lancamento": str(_row[COL["num_lancamento"]]).strip(),
            "titulo": _titulo,
            "parcela": _parcela,
            "vencimento": str(_row[COL["vencimento"]]).strip(),
            "pagamento": str(_row[COL["pagamento"]]).strip(),
            "dias": _dias_venc,
            "pendente": _pendente,
            "pago": _pago_val,
            "faixa": _faixa,
            "titulo_key": _titulo_key,
            "mensagem_whatsapp": _mensagem,
        })


# Contagem
_ng = sum(1 for c in clientes_cobrar if c['faixa']=='grave')
_na = sum(1 for c in clientes_cobrar if c['faixa']=='alerta')
_nt = sum(1 for c in clientes_cobrar if c['faixa']=='atencao')
_nr = sum(1 for v in recebido_faixa.values() if v.get('is_ativo'))
print(f"👥 Clientes a cobrar: {len(clientes_cobrar)} ({_ng}g/{_na}a/{_nt}t)")
print(f"💰 Vendedores com recebimento no período: {_nr}")

print(f"\U0001f465 Clientes a cobrar: {len(clientes_cobrar)} títulos ({_ng} grave / {_na} alerta / {_nt} atenção)")

# =========================================
# COBRANÇA10 — helpers e config
# =========================================
import hashlib as _hashlib

COBRANCA10_LOGIN = "cobranca10"
COBRANCA10_NOME = "Cobrança10"
COBRANCA10_FILIAL = "FTER"
COBRANCA10_RATEIO_DEFAULT = 20.0

def _load_cobranca_global_rateio_pct():
    try:
        _cfgp = os.path.join(pasta, "cache_historico", "config_meta.json")
        if os.path.exists(_cfgp):
            with open(_cfgp, "r", encoding="utf-8") as _fcg:
                _rawcg = json.load(_fcg)
            _globalcg = _rawcg.get("global", _rawcg) if isinstance(_rawcg, dict) else {}
            _pctcg = float(_globalcg.get("cobranca_global_rateio_pct", COBRANCA10_RATEIO_DEFAULT) or COBRANCA10_RATEIO_DEFAULT)
            return max(0.0, min(100.0, _pctcg))
    except Exception:
        pass
    return COBRANCA10_RATEIO_DEFAULT

COBRANCA10_RATEIO = _load_cobranca_global_rateio_pct() / 100.0

CREDIARISTAS_FILIAIS = {
    "F2": "crediaristaf02",
    "F3": "crediaristaf03",
    "F4": "crediaristaf04",
    "F5": "crediaristaf05",
    "F6": "crediaristaf06",
    "F8": "crediaristaf08",
    "F9": "crediaristaf09",
}

def nome_crediarista_filial(filial):
    return f"CREDIARISTA{str(filial).upper()}"

def cobranca_row_key_py(r):
    return "|".join([
        str(r.get("cliente", r.get("nome", "")) or "").strip().upper(),
        str(r.get("titulo", "") or "").strip(),
        str(r.get("parcela", "") or "").strip(),
        str(r.get("vencimento", "") or "").strip(),
    ])

# =========================================
# COBRANÇA10 — 20% global dos títulos de cobrança
# Cada título vai para 1 destino apenas, sem duplicidade.
# =========================================
_clientes_cobrar_sorted = sorted(clientes_cobrar, key=lambda x: (cobranca_row_key_py(x), -float(x.get("pendente", 0) or 0)))
_clientes_cobrar_unicos = {}
for _c_tmp in _clientes_cobrar_sorted:
    _k_tmp = cobranca_row_key_py(_c_tmp)
    if _k_tmp not in _clientes_cobrar_unicos:
        _clientes_cobrar_unicos[_k_tmp] = _c_tmp
_clientes_cobrar_base = list(_clientes_cobrar_unicos.values())
_clientes_cobrar_base.sort(key=lambda x: x["pendente"], reverse=True)
_qtd_terceiro = int(round(len(_clientes_cobrar_base) * COBRANCA10_RATEIO))
_clientes_cobrar_hash = sorted(_clientes_cobrar_base, key=lambda x: _hashlib.md5(cobranca_row_key_py(x).encode("utf-8")).hexdigest())
_clientes_terceiro_lista = _clientes_cobrar_hash[:_qtd_terceiro]
_clientes_terceiro_keys = {cobranca_row_key_py(x) for x in _clientes_terceiro_lista}
clientes_cobrar = [x for x in clientes_cobrar if cobranca_row_key_py(x) not in _clientes_terceiro_keys]
print(f"🤝 Cobrança10 separado com {len(_clientes_terceiro_lista)} títulos ({COBRANCA10_RATEIO*100:.0f}% do total único)")

# Ativos: agrupa por (vendedor, filial_vendedor) — pertence a uma filial pelo nome
ativos = df_ativos_raw.groupby(["vendedor","filial_vendedor","is_gerente"]).agg(
    pendente=("pendente","sum"), pago=("pago","sum")
).reset_index()
# Coluna "filial" nos ativos = filial_vendedor (necessária para o passo 2)
ativos["filial"] = ativos["filial_vendedor"]

# Garante uma linha "gerente/filial" sintética quando a filial tem vendedor ativo,
# mas não tem gerente ativo no relatório. Assim o rateio 60/40 continua valendo:
# 60% fica na filial/gerente e 40% vai para os vendedores.
_gerentes_sint = []
for _fil_syn in sorted(set(str(x) for x in ativos["filial_vendedor"].dropna().tolist())):
    _sub_syn = ativos[ativos["filial_vendedor"] == _fil_syn]
    if _sub_syn.empty:
        continue
    _tem_vend_syn = bool((_sub_syn["is_gerente"] == False).any())
    _tem_ger_syn = bool((_sub_syn["is_gerente"] == True).any())
    if _tem_vend_syn and not _tem_ger_syn:
        _gerentes_sint.append({
            "vendedor": f"GERENTE {_fil_syn}",
            "filial_vendedor": _fil_syn,
            "is_gerente": True,
            "pendente": 0.0,
            "pago": 0.0,
            "filial": _fil_syn,
            "_synthetic_manager": True,
        })

if _gerentes_sint:
    ativos = pd.concat([ativos, pd.DataFrame(_gerentes_sint)], ignore_index=True)
    print(f"🧩 Gerentes sintéticos criados para manter rateio 60/40: {', '.join(sorted(x['filial_vendedor'] for x in _gerentes_sint))}")

# Inativos: agrupa por (vendedor, filial_erp) — preserva a filial de cada crédito
inativos = df_inativos_raw.groupby(["vendedor","filial_erp"]).agg(
    pendente=("pendente","sum"), pago=("pago","sum")
).reset_index()
inativos.rename(columns={"filial_erp":"filial"}, inplace=True)
inativos["is_gerente"] = False

print(f"\n👥 Ativos (vendedor+gerente): {ativos['vendedor'].nunique()}")
print(f"👥 Inativos:                  {inativos['vendedor'].nunique()}")

# =========================================
# RATEIO: regra 60% gerente / 40% vendedores
# =========================================
PESO_GER  = 0.60
PESO_VEND = 0.40

ORDEM_FILIAIS = ["F1","F2","F3","F4","F5","F6","F8","F9"]

def ratear(ativos_df, filial, total_p, total_pg):
    """Distribui total_p/total_pg entre ativos da filial. Gerentes: 60%, vendedores: 40%."""
    mask = ativos_df["filial_vendedor"] == filial
    ger  = ativos_df[mask &  ativos_df["is_gerente"]]
    vend = ativos_df[mask & ~ativos_df["is_gerente"]]
    ng, nv = len(ger), len(vend)
    if ng == 0 and nv == 0:
        return ativos_df
    updates = {}
    if ng > 0 and nv > 0:
        for idx in ger.index:  updates[idx] = (total_p*PESO_GER/ng,   total_pg*PESO_GER/ng)
        for idx in vend.index: updates[idx] = (total_p*PESO_VEND/nv,  total_pg*PESO_VEND/nv)
    elif ng > 0:
        for idx in ger.index:  updates[idx] = (total_p/ng,  total_pg/ng)
    else:
        for idx in vend.index: updates[idx] = (total_p/nv,  total_pg/nv)
    for idx,(dp,dpg) in updates.items():
        ativos_df.loc[idx,"pendente"] += dp
        ativos_df.loc[idx,"pago"]     += dpg
    return ativos_df

# =========================================
# PASSO 1 — INATIVOS → ATIVOS DA MESMA FILIAL
# Filiais sem ativo ficam como bloco consolidado
# =========================================
filiais_sem_ativo = {}   # ex: {"F5": {"pendente":45169, "pago":77222}}

# Passo 1 trata apenas filiais normais — FDEP dos inativos é tratado no Passo 2
inat_normais = inativos[inativos["filial"] != "FDEP"].copy()
inat_fdep    = inativos[inativos["filial"] == "FDEP"].copy()

inat_agg = (
    inat_normais.groupby("filial", dropna=True)[["pendente","pago"]]
    .sum().reset_index()
)
for _, row_in in inat_agg.iterrows():
    filial   = row_in["filial"]
    total_p  = row_in["pendente"]
    total_pg = row_in["pago"]
    if total_p == 0 and total_pg == 0: continue

    tem_ativo = (ativos["filial_vendedor"] == filial).any()
    if tem_ativo:
        ativos = ratear(ativos, filial, total_p, total_pg)
        print(f"  ↳ Inativos→{filial}: rateado pend={total_p:,.2f} pago={total_pg:,.2f}")
    else:
        filiais_sem_ativo[filial] = {"pendente": total_p, "pago": total_pg}
        print(f"  ↳ Inativos→{filial}: SEM ATIVO, consolidado pend={total_p:,.2f} pago={total_pg:,.2f}")

# =========================================
# PASSO 2 — FDEP (F90/F99) → FILIAIS NORMAIS
# Peso por filial = pendente+pago dos ativos daquela filial
# Dentro de cada filial aplica regra 60/40 gerente/vendedor
# Filiais sem ativo recebem a fatia proporcional no bloco consolidado
# =========================================
mask_dep  = ativos["filial"] == "FDEP"
df_dep    = ativos[mask_dep].copy()
df_normal = ativos[~mask_dep].copy()

# Soma também o FDEP vindo de inativos (vendedores inativos com créditos na F90/F99)
fdep_inat_p  = inat_fdep["pendente"].sum() if not inat_fdep.empty else 0.0
fdep_inat_pg = inat_fdep["pago"].sum()     if not inat_fdep.empty else 0.0

# pesos e tw expostos fora do bloco condicional para uso na serialização
pesos = {}
tw    = 0.0
fdep_total_rateado_p  = 0.0
fdep_total_rateado_pg = 0.0

if not df_dep.empty or (fdep_inat_p + fdep_inat_pg) > 0:
    total_dep_p  = df_dep["pendente"].sum() + fdep_inat_p
    total_dep_pg = df_dep["pago"].sum()     + fdep_inat_pg
    fdep_total_rateado_p  = total_dep_p
    fdep_total_rateado_pg = total_dep_pg
    print(f"\n💰 FDEP a ratear: pend={total_dep_p:,.2f}  pago={total_dep_pg:,.2f} (ativos={df_dep['pendente'].sum():,.2f} + inativos={fdep_inat_p:,.2f})")

    # Calcula peso de cada filial
    for f in ORDEM_FILIAIS:
        sub = df_normal[df_normal["filial_vendedor"] == f]
        if not sub.empty:
            pesos[f] = (sub["pendente"] + sub["pago"]).sum()
        elif f in filiais_sem_ativo:
            pesos[f] = filiais_sem_ativo[f]["pendente"] + filiais_sem_ativo[f]["pago"]

    tw = sum(pesos.values())
    if tw > 0:
        for filial, peso in pesos.items():
            prop   = peso / tw
            vp     = total_dep_p  * prop
            vpg    = total_dep_pg * prop
            if filial in filiais_sem_ativo:
                filiais_sem_ativo[filial]["pendente"] += vp
                filiais_sem_ativo[filial]["pago"]     += vpg
                print(f"  ↳ FDEP→{filial} (sem ativo): pend={vp:,.2f} pago={vpg:,.2f}")
            else:
                df_normal = ratear(df_normal, filial, vp, vpg)
                print(f"  ↳ FDEP→{filial}: pend={vp:,.2f} pago={vpg:,.2f}")
    print("✅ Rateio FDEP concluído")
else:
    print("ℹ️  Nenhum registro FDEP")

# ===== RESULTADO FINAL (ativos + blocos consolidados)
df_vend = df_normal.copy()
df_vend["nome_exibicao"] = df_vend["vendedor"].apply(limpar_nome_display)
df_vend["total"]         = df_vend["pendente"] + df_vend["pago"]

total_por_filial = df_vend.groupby("filial_vendedor")["pendente"].sum().rename("total_filial")
df_vend = df_vend.merge(total_por_filial, on="filial_vendedor", how="left")
df_vend["perc_filial"] = (df_vend["pendente"] / df_vend["total_filial"].replace(0,1) * 100).round(2)

df_vend["filial_ordem"] = pd.Categorical(df_vend["filial_vendedor"], categories=ORDEM_FILIAIS, ordered=True)
df_vend = df_vend.sort_values(
    ["filial_ordem","is_gerente","pendente"], ascending=[True,False,False]
).reset_index(drop=True)

# ===== VERIFICAÇÃO DE TOTAIS (deve bater com o arquivo bruto)
total_vend_p  = df_vend["pendente"].sum()
total_vend_pg = df_vend["pago"].sum()
total_cons_p  = sum(v["pendente"] for v in filiais_sem_ativo.values())
total_cons_pg = sum(v["pago"]     for v in filiais_sem_ativo.values())
total_final_p  = total_vend_p  + total_cons_p
total_final_pg = total_vend_pg + total_cons_pg

print(f"\n{'='*55}")
print(f"📊 TOTAIS POR FILIAL (após rateio):")
for f in ORDEM_FILIAIS:
    sub = df_vend[df_vend["filial_vendedor"] == f]
    if not sub.empty:
        tag = ""
    elif f in filiais_sem_ativo:
        sub_p  = filiais_sem_ativo[f]["pendente"]
        sub_pg = filiais_sem_ativo[f]["pago"]
        print(f"  {f} [sem ativo]: pend={sub_p:>12,.2f}  pago={sub_pg:>12,.2f}")
        continue
    else:
        continue
    print(f"  {f}: pend={sub['pendente'].sum():>12,.2f}  pago={sub['pago'].sum():>12,.2f}  ({len(sub)} vendedores)")

print(f"\n  TOTAL ativos   : pend={total_vend_p:>12,.2f}  pago={total_vend_pg:>12,.2f}")
print(f"  TOTAL consolid.: pend={total_cons_p:>12,.2f}  pago={total_cons_pg:>12,.2f}")
print(f"  TOTAL GERAL    : pend={total_final_p:>12,.2f}  pago={total_final_pg:>12,.2f}")
print(f"  BRUTO original : pend={total_bruto_p:>12,.2f}  pago={total_bruto_pg:>12,.2f}")
diff_p  = total_final_p  - total_bruto_p
diff_pg = total_final_pg - total_bruto_pg
print(f"  DIFERENÇA      : pend={diff_p:>+12,.2f}  pago={diff_pg:>+12,.2f}  {'✅ OK' if abs(diff_p)<0.02 and abs(diff_pg)<0.02 else '⚠️ VERIFICAR'}")
print(f"{'='*55}")

# ===== SALVAR CSV
csv_path = os.path.join(pasta, "dashboard_vendedores.csv")
df_vend.to_csv(csv_path, index=False)
print(f"\n💾 CSV salvo: {csv_path}")

# =========================================
# 🔐 CREDENCIAIS
# =========================================
SENHA_MASTER = "mdladm01"
LOGIN_MASTER = "master"
SENHA_DIRETOR = "mdldir01"
LOGIN_DIRETOR = "diretorcomercial"
LOGIN_PAINEL = "painel"
SENHA_PAINEL = "painelmdl10"
EMAIL_RECUPERACAO = "sac@moveisdolar.com.br"
cred_path    = os.path.join(pasta, "credenciais_vendedores.txt")
cred_state_path = os.path.join(pasta, "credenciais_dashboard.json")

def _load_json_safe(path, default):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, type(default)) else default
    except Exception:
        pass
    return default

# Tenta baixar o estado remoto das credenciais para manter as senhas alteradas no dashboard
try:
    import ftplib
    from io import BytesIO
    _ftp = ftplib.FTP()
    _ftp.connect("moveisdolar.com.br", 21, timeout=20)
    _ftp.login("moveisdolar3", "Deg27ll02mdl2301#")
    _ftp.encoding = "utf-8"
    _ftp.cwd("/public_html/colaborador")
    with open(cred_state_path, "wb") as _fcred:
        _ftp.retrbinary("RETR credenciais_dashboard.json", _fcred.write)
    _ftp.quit()
    print("🔄 Credenciais remotas sincronizadas do FTP.")
except Exception:
    pass

# Carrega senhas existentes do TXT antigo para não trocar entre execuções
creds_salvas = {}
if os.path.exists(cred_path):
    with open(cred_path, "r", encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if "|" in linha and not linha.startswith(("=","-")):
                p = [x.strip() for x in linha.split("|")]
                if len(p) >= 4 and p[0] and p[2]:
                    creds_salvas[f"{p[0]}_{p[3]}"] = p[2]

cred_state = _load_json_safe(cred_state_path, {"users": {}, "director": {}, "password_reset_requests": []})

credenciais = {}
linhas_txt  = []
auth_users  = {}

for _, row in df_vend.iterrows():
    nome_exib = str(row["nome_exibicao"]).strip()
    filial    = str(row["filial_vendedor"]).strip()
    is_ger    = bool(row["is_gerente"])
    login     = normalizar_login(nome_exib)
    chave     = f"{login}_{filial}"
    senha_inicial = creds_salvas.get(chave) or (login.upper() + str(random.randint(100,999)))
    login_fin = login
    if login in credenciais and credenciais[login]["filial"] != filial:
        login_fin = f"{login}_{filial.lower()}"

    estado_ant = cred_state.get("users", {}).get(login_fin, {})
    senha_atual = estado_ant.get("password") or senha_inicial
    precisa_trocar = bool(estado_ant.get("must_change_password", senha_atual == senha_inicial))

    credenciais[login_fin] = {
        "senha":      senha_atual,
        "senha_inicial": senha_inicial,
        "nome":       nome_exib,
        "filial":     filial,
        "is_gerente": is_ger,
        "pendente":   round(float(row["pendente"]),   2),
        "pago":       round(float(row["pago"]),       2),
        "total":      round(float(row["total"]),      2),
        "perc_filial":round(float(row["perc_filial"]),2),
    }
    auth_users[login_fin] = {
        "login": login_fin,
        "password": senha_atual,
        "initial_password": senha_inicial,
        "must_change_password": precisa_trocar,
        "nome": nome_exib,
        "filial": filial,
        "is_gerente": is_ger,
        "email_recuperacao": EMAIL_RECUPERACAO,
    }
    tipo = "GERENTE" if is_ger else "VENDEDOR"
    linhas_txt.append(f"{login_fin} | {nome_exib} | {senha_atual} | {filial} | {tipo}")

# Usuário especial de cobrança terceirizada
_chave_cob10 = COBRANCA10_LOGIN
_senha_cob10_inicial = creds_salvas.get(f"{COBRANCA10_LOGIN}_{COBRANCA10_FILIAL}") or ("COB10" + str(random.randint(100,999)))
_estado_cob10 = cred_state.get("users", {}).get(_chave_cob10, {})
_senha_cob10 = _estado_cob10.get("password") or _senha_cob10_inicial
_precisa_cob10 = bool(_estado_cob10.get("must_change_password", _senha_cob10 == _senha_cob10_inicial))
_terceiro_pendente = sum(float(x.get("pendente", 0) or 0) for x in _clientes_terceiro_lista)
credenciais[_chave_cob10] = {
    "senha": _senha_cob10,
    "senha_inicial": _senha_cob10_inicial,
    "nome": COBRANCA10_NOME,
    "filial": COBRANCA10_FILIAL,
    "is_gerente": False,
    "is_terceiro": True,
    "pendente": round(_terceiro_pendente, 2),
    "pago": 0.0,
    "total": round(_terceiro_pendente, 2),
    "perc_filial": 100.0,
    "only_cobranca": True,
}
auth_users[_chave_cob10] = {
    "login": _chave_cob10,
    "password": _senha_cob10,
    "initial_password": _senha_cob10_inicial,
    "must_change_password": _precisa_cob10,
    "nome": COBRANCA10_NOME,
    "filial": COBRANCA10_FILIAL,
    "is_gerente": False,
    "is_terceiro": True,
    "only_cobranca": True,
    "email_recuperacao": EMAIL_RECUPERACAO,
}
linhas_txt.append(f"{_chave_cob10} | {COBRANCA10_NOME} | {_senha_cob10} | {COBRANCA10_FILIAL} | COBRANÇA TERCEIRO")


# Inicialização antecipada para evitar NameError antes da montagem final
clientes_crediarista_js = {}
recebimentos_crediarista_js = {}

# Usuários CREDIARISTAS por filial
for _fil_cred, _login_cred in CREDIARISTAS_FILIAIS.items():
    _nome_cred = nome_crediarista_filial(_fil_cred)
    _senha_ini = creds_salvas.get(f"{_login_cred}_{_fil_cred}") or (_login_cred.upper() + str(random.randint(100,999)))
    _estado_cred = cred_state.get("users", {}).get(_login_cred, {})
    _senha_cred = _estado_cred.get("password") or _senha_ini
    _troca_cred = bool(_estado_cred.get("must_change_password", _senha_cred == _senha_ini))
    _pend_cred = sum(float(x.get("pendente", 0) or 0) for _fx in ['grave','alerta','atencao'] for x in clientes_crediarista_js.get(_login_cred, {}).get(_fx, []))
    _pago_cred = sum(float(x.get("pago", 0) or 0) for _fx in ['grave','alerta','atencao'] for x in recebimentos_crediarista_js.get(_login_cred, {}).get(_fx, []))
    credenciais[_login_cred] = {
        "senha": _senha_cred,
        "senha_inicial": _senha_ini,
        "nome": _nome_cred,
        "filial": _fil_cred,
        "is_gerente": False,
        "is_crediarista": True,
        "only_cobranca": True,
        "pendente": round(_pend_cred, 2),
        "pago": round(_pago_cred, 2),
        "total": round(_pend_cred + _pago_cred, 2),
        "perc_filial": 100.0,
    }
    auth_users[_login_cred] = {
        "login": _login_cred,
        "password": _senha_cred,
        "initial_password": _senha_ini,
        "must_change_password": _troca_cred,
        "nome": _nome_cred,
        "filial": _fil_cred,
        "is_gerente": False,
        "is_crediarista": True,
        "only_cobranca": True,
        "email_recuperacao": EMAIL_RECUPERACAO,
    }
    linhas_txt.append(f"{_login_cred} | {_nome_cred} | {_senha_cred} | {_fil_cred} | CREDIARISTA")


# Usuário somente visualização da tela inicial
_estado_painel = cred_state.get("users", {}).get(LOGIN_PAINEL, {})
_senha_painel = _estado_painel.get("password") or SENHA_PAINEL
_troca_painel = bool(_estado_painel.get("must_change_password", False))
credenciais[LOGIN_PAINEL] = {
    "senha": _senha_painel,
    "senha_inicial": SENHA_PAINEL,
    "nome": "Painel",
    "filial": "",
    "is_gerente": False,
    "is_viewer": True,
    "pendente": 0.0,
    "pago": 0.0,
    "total": 0.0,
    "perc_filial": 0.0,
}
auth_users[LOGIN_PAINEL] = {
    "login": LOGIN_PAINEL,
    "password": _senha_painel,
    "initial_password": SENHA_PAINEL,
    "must_change_password": _troca_painel,
    "nome": "Painel",
    "filial": "",
    "is_gerente": False,
    "is_viewer": True,
    "email_recuperacao": EMAIL_RECUPERACAO,
}
linhas_txt.append(f"{LOGIN_PAINEL} | Painel | {_senha_painel} | --- | VISUALIZAÇÃO")

cred_state["users"] = auth_users
cred_state["director"] = {
    "login": LOGIN_DIRETOR,
    "password": cred_state.get("director", {}).get("password") or SENHA_DIRETOR,
    "initial_password": SENHA_DIRETOR,
    "must_change_password": bool(cred_state.get("director", {}).get("must_change_password", True)),
    "nome": "Diretor Comercial",
    "email_recuperacao": EMAIL_RECUPERACAO,
}
cred_state.setdefault("password_reset_requests", [])

with open(cred_state_path, "w", encoding="utf-8") as f:
    json.dump(cred_state, f, ensure_ascii=False, indent=2)

with open(cred_path, "w", encoding="utf-8") as f:
    f.write("=" * 70 + "\n")
    f.write("   CREDENCIAIS DASHBOARD – MÓVEIS DOLAR\n")
    f.write("=" * 70 + "\n\n")
    f.write(f"  MASTER             login: {LOGIN_MASTER}   senha: {SENHA_MASTER}\n")
    f.write(f"  DIRETOR COMERCIAL  login: {LOGIN_DIRETOR}   senha atual: {cred_state['director']['password']}\n")
    f.write(f"  PAINEL            login: {LOGIN_PAINEL}   senha atual: {_senha_painel}\n\n")
    f.write("-" * 70 + "\n")
    f.write(f"  {'LOGIN':<20} {'NOME':<35} {'SENHA':<14} {'FILIAL':<6} TIPO\n")
    f.write("-" * 70 + "\n")
    for linha in sorted(linhas_txt):
        p = [x.strip() for x in linha.split("|")]
        if len(p) >= 5:
            f.write(f"  {p[0]:<20} {p[1]:<35} {p[2]:<14} {p[3]:<6} {p[4]}\n")
    f.write("\n" + "=" * 70 + "\n")

print(f"🔐 Credenciais: {cred_path} ({len(credenciais)} vendedores)")
js_auth_state = json.dumps(cred_state, ensure_ascii=False)


# =========================================
# 💾 MÓDULO DE CACHE / HISTÓRICO / METAS (v2)
# Nova lógica: 3 gráficos por faixa + 1 geral
# Grave=20% do pendente grave, Alerta=15%, Atenção=10%
# Geral: ponderado 60/30/10 dos 3 gráficos
# =========================================
import json
from datetime import datetime, timedelta, date
from pathlib import Path

CACHE_DIR  = os.path.join(pasta, "cache_historico")
Path(CACHE_DIR).mkdir(exist_ok=True)

hoje_str = datetime.now().strftime("%Y-%m-%d")
mes_str  = datetime.now().strftime("%Y-%m")

# Carrega configurações de meta (definidas pelo master no dashboard)
# Estrutura: config_meta.json tem "global" (padrão) e "individual" (por vendedor/filial)

_config_meta_path = os.path.join(CACHE_DIR, "config_meta.json")
REMOTE_PUBLIC_BASE = "https://moveisdolar.com.br/colaborador"
REMOTE_CONFIG_URL = REMOTE_PUBLIC_BASE + "/config_meta.json"
_hist_dash_path = os.path.join(CACHE_DIR, 'historico_dashboard.json')
_fechamento_path = os.path.join(CACHE_DIR, 'fechamentos_mensais.json')
REMOTE_HIST_URL = REMOTE_PUBLIC_BASE + '/historico_dashboard.json'
REMOTE_FECHAMENTO_URL = REMOTE_PUBLIC_BASE + '/fechamentos_mensais.json'
try:
    with urllib.request.urlopen(REMOTE_HIST_URL, timeout=10) as _resp_hist:
        _remote_hist = _resp_hist.read().decode('utf-8', errors='ignore').strip()
    if _remote_hist and _remote_hist.startswith('{'):
        with open(_hist_dash_path, 'w', encoding='utf-8') as _f_hist_local:
            _f_hist_local.write(_remote_hist)
        print('🌐 Histórico dashboard sincronizado do servidor')
except Exception:
    pass
try:
    with urllib.request.urlopen(REMOTE_FECHAMENTO_URL, timeout=10) as _resp_fech:
        _remote_fech = _resp_fech.read().decode('utf-8', errors='ignore').strip()
    if _remote_fech and _remote_fech.startswith('{'):
        with open(_fechamento_path, 'w', encoding='utf-8') as _f_fech_local:
            _f_fech_local.write(_remote_fech)
        print('🌐 Fechamentos mensais sincronizados do servidor')
except Exception:
    pass
try:
    with urllib.request.urlopen(REMOTE_CONFIG_URL, timeout=10) as _resp_cfg:
        _remote_cfg = _resp_cfg.read().decode("utf-8", errors="ignore").strip()
    if _remote_cfg and _remote_cfg.startswith("{"):
        with open(_config_meta_path, "w", encoding="utf-8") as _f_cfg_local:
            _f_cfg_local.write(_remote_cfg)
        print("🌐 Config meta sincronizada do servidor")
except Exception:
    pass
_config_meta_default_global = {
    "grave_pct":   20.0,
    "alerta_pct":  15.0,
    "atencao_pct": 10.0,
    "peso_grave":  60.0,
    "peso_alerta": 30.0,
    "peso_atencao":10.0,
    "vendas_min_pct": 80.0,
    "servicos_min_pct": 80.0,
    "gerente_vendas_min_pct": 90.0,
    "gerente_servicos_min_pct": 90.0,
    "vendedor_policy": [],
    "gerente_policy": [],
    "vendedor_policy_headers": [],
    "gerente_policy_headers": [],
    "camp_cobranca_terceiro": [
        {"faixa": "atencao", "pct": "1.00"},
        {"faixa": "alerta", "pct": "2.00"},
        {"faixa": "grave", "pct": "3.00"}
    ],
    "camp_cob_crediarista": [
        {"faixa": "atencao", "pct": "1.00"},
        {"faixa": "alerta", "pct": "2.00"},
        {"faixa": "grave", "pct": "3.00"}
    ],
    "cob_cred_rateio_filial_pct": 50.0,
    "cob_cred_rateio_cred_pct": 50.0,
    "cobranca_global_rateio_pct": 20.0,
}
if os.path.exists(_config_meta_path):
    with open(_config_meta_path, encoding="utf-8") as _f:
        _cfg_raw = json.load(_f)
    # Suporte ao formato antigo (sem chave "global")
    if "global" in _cfg_raw:
        CONFIG_META        = {**_config_meta_default_global, **_cfg_raw["global"]}
        CONFIG_META_IND    = _cfg_raw.get("individual", {})  # {key_vend: {...}}
    else:
        CONFIG_META        = {**_config_meta_default_global, **_cfg_raw}
        CONFIG_META_IND    = {}
else:
    CONFIG_META     = _config_meta_default_global.copy()
    CONFIG_META_IND = {}
    with open(_config_meta_path, "w", encoding="utf-8") as _f:
        json.dump({"global": CONFIG_META, "individual": {}}, _f, ensure_ascii=False, indent=2)

def get_config_meta(key):
    """Retorna config de meta para um vendedor/filial, com fallback para global."""
    aliases = [str(key or ''), str(key or '').upper()]
    if isinstance(key, str) and '::' in key:
        _kind, _pure = key.split('::', 1)
        aliases += [_pure, _pure.upper(), ('vend:' if _kind == 'VEND' else 'fil:') + _pure]
    for ak in aliases:
        if ak in CONFIG_META_IND:
            return {**CONFIG_META, **CONFIG_META_IND[ak]}
    return CONFIG_META

print(f"⚙️  Config meta global: Grave={CONFIG_META['grave_pct']}% Alerta={CONFIG_META['alerta_pct']}% Atenção={CONFIG_META['atencao_pct']}% | Pesos: {CONFIG_META['peso_grave']}/{CONFIG_META['peso_alerta']}/{CONFIG_META['peso_atencao']}")
print(f"⚙️  Configs individuais: {len(CONFIG_META_IND)} sobreposições")

# Histórico mensal de comissão de cobrança (pagamento dia 10 do mês seguinte)
COMISSAO_HIST_PATH = os.path.join(pasta, "historico_comissao_cobranca.json")

def _row_key_cob_json(r):
    return "|".join([
        str(r.get("cliente", r.get("nome", "")) or "").strip().upper(),
        str(r.get("titulo", "") or "").strip(),
        str(r.get("parcela", "") or "").strip(),
        str(r.get("vencimento", "") or "").strip(),
    ])

def _mes_data_br(s):
    try:
        d = _dt.strptime(str(s or '').strip(), "%d/%m/%Y")
        return d.strftime("%Y-%m")
    except Exception:
        return ''

def _proximo_pagamento_mes(mes_ref):
    try:
        y,m = [int(x) for x in str(mes_ref).split('-')]
        if m == 12:
            y2,m2 = y+1,1
        else:
            y2,m2 = y,m+1
        return f"10/{m2:02d}/{y2}"
    except Exception:
        return ''

def _ftp_json(nome, default):
    try:
        import ftplib
        from io import BytesIO
        bio = BytesIO()
        ftp = ftplib.FTP()
        ftp.connect("moveisdolar.com.br", 21, timeout=20)
        ftp.login("moveisdolar3", "Deg27ll02mdl2301#")
        ftp.encoding = 'utf-8'
        ftp.cwd('/public_html/colaborador')
        ftp.retrbinary(f'RETR {nome}', bio.write)
        ftp.quit()
        bio.seek(0)
        return json.loads(bio.read().decode('utf-8'))
    except Exception:
        return default

# Atualiza métricas finais dos crediaristas após montar carteiras/recebimentos reais
for _fil_cred, _login_cred in CREDIARISTAS_FILIAIS.items():
    _pend_cred = sum(float(x.get('pendente', 0) or 0) for _fx in ['grave','alerta','atencao'] for x in clientes_crediarista_js.get(_login_cred, {}).get(_fx, []))
    _pago_cred = sum(float(x.get('pago', 0) or 0) for _fx in ['grave','alerta','atencao'] for x in recebimentos_crediarista_js.get(_login_cred, {}).get(_fx, []))
    if _login_cred in credenciais:
        credenciais[_login_cred]['pendente'] = round(_pend_cred, 2)
        credenciais[_login_cred]['pago'] = round(_pago_cred, 2)
        credenciais[_login_cred]['total'] = round(_pend_cred + _pago_cred, 2)

def _historico_comissao_cobranca10():
    hist = _load_json_safe(COMISSAO_HIST_PATH, {"months": {}})
    logs = _ftp_json('cobrancas_log.json', [])
    mes_atual = _dt.now().strftime('%Y-%m')
    cfg_rows = (CONFIG_META.get('camp_cobranca_terceiro') or _config_meta_default_global.get('camp_cobranca_terceiro') or [])
    pct_fx = {str(x.get('faixa','')).lower(): float(str(x.get('pct',0)).replace(',','.')) for x in cfg_rows if x}
    logs_mes = [x for x in (logs or []) if str(x.get('usuario','')).lower() in (COBRANCA10_LOGIN, COBRANCA10_NOME.lower()) and str(x.get('server_time',''))[:7] == mes_atual]
    keys = {_row_key_cob_json(x) for x in logs_mes}
    recebido = {'atencao':0.0,'alerta':0.0,'grave':0.0}
    for fx in ['atencao','alerta','grave']:
        for r in recebimentos_terceiro_js.get(fx, []):
            if _row_key_cob_json(r) in keys and _mes_data_br(r.get('pagamento','')) == mes_atual:
                recebido[fx] += float(r.get('pago',0) or 0)
    com = {fx: round(recebido[fx] * (pct_fx.get(fx,0)/100.0), 2) for fx in recebido}
    hist.setdefault('months', {})[mes_atual] = {
        'mes': mes_atual,
        'usuario': COBRANCA10_LOGIN,
        'nome': COBRANCA10_NOME,
        'pagamento_previsto_em': _proximo_pagamento_mes(mes_atual),
        'recebido': recebido,
        'comissao': com,
        'total_comissao': round(sum(com.values()), 2),
        'updated_at': datetime.now().isoformat(),
    }
    with open(COMISSAO_HIST_PATH, 'w', encoding='utf-8') as f:
        json.dump(hist, f, ensure_ascii=False, indent=2)
    return hist


def cache_path(d):   return os.path.join(CACHE_DIR, f"snapshot_{d}.json")
def meta_path(m):    return os.path.join(CACHE_DIR, f"meta_{m}.json")
def ref_path(m):     return os.path.join(CACHE_DIR, f"snapshot_referencia_{m}.json")

def _load_json_file(_path, _default):
    try:
        if os.path.exists(_path):
            with open(_path, encoding='utf-8') as _f:
                _data = json.load(_f)
            if isinstance(_data, type(_default)):
                return _data
    except Exception:
        pass
    return _default

def _list_snapshot_dates():
    _out=[]
    for _name in os.listdir(CACHE_DIR):
        if _name.startswith('snapshot_') and _name.endswith('.json') and 'referencia' not in _name:
            _date=_name.replace('snapshot_','').replace('.json','')
            if len(_date)==10:
                _out.append(_date)
    return sorted(set(_out))

def _find_last_snapshot_before_date(_date_str):
    _cands=[d for d in _list_snapshot_dates() if d < _date_str]
    if not _cands:
        return None
    _last=_cands[-1]
    _path=cache_path(_last)
    try:
        with open(_path, encoding='utf-8') as _f:
            _snap=json.load(_f)
        _snap['_path']=_path
        return _snap
    except Exception:
        return None

def _find_last_snapshot_of_month(_month_str):
    _cands=[d for d in _list_snapshot_dates() if str(d).startswith(_month_str)]
    if not _cands:
        return None
    _last=_cands[-1]
    try:
        with open(cache_path(_last), encoding='utf-8') as _f:
            _snap=json.load(_f)
        _snap['_path']=cache_path(_last)
        return _snap
    except Exception:
        return None

def ensure_month_reference_locked(_month_str, _today_str):
    _rp = ref_path(_month_str)
    if os.path.exists(_rp):
        return _rp
    _base_snap = _find_last_snapshot_before_date(_today_str)
    if _base_snap:
        _ref_payload = {
            'data': _base_snap.get('data', _today_str),
            'gerado_em': datetime.now().isoformat(),
            'origem': 'ultimo_snapshot_anterior',
            'snapshot_origem_path': _base_snap.get('_path',''),
            'snapshot_origem_data': _base_snap.get('data', _today_str),
        }
    else:
        _ref_payload = {
            'data': f'{_month_str}-01',
            'gerado_em': datetime.now().isoformat(),
            'origem': 'inicio_mes_sem_snapshot_anterior',
            'snapshot_origem_path': '',
            'snapshot_origem_data': f'{_month_str}-01',
        }
    with open(_rp, 'w', encoding='utf-8') as _f:
        json.dump(_ref_payload, _f, ensure_ascii=False, indent=2)
    print(f'🧷 Referência mensal travada: {_rp} → base {_ref_payload["data"]}')
    return _rp

def fechar_mes_anterior_travado(_mes_atual, _hist_dash, _config_global, _config_ind):
    _fech = _load_json_file(_fechamento_path, {'months':{}})
    _fech.setdefault('months', {})
    _first_day = datetime.strptime(_mes_atual + '-01', '%Y-%m-%d')
    _prev_month = (_first_day - timedelta(days=1)).strftime('%Y-%m')
    if _prev_month in _fech['months']:
        return _fech
    _prev_meta_path = meta_path(_prev_month)
    if not os.path.exists(_prev_meta_path):
        return _fech
    try:
        with open(_prev_meta_path, encoding='utf-8') as _f:
            _prev_meta = json.load(_f)
    except Exception:
        return _fech
    _last_prev_snap = _find_last_snapshot_of_month(_prev_month)
    _prev_dates = sorted([d for d in (_hist_dash.get('dates', {}) or {}).keys() if str(d).startswith(_prev_month)])
    _last_hist_date = _prev_dates[-1] if _prev_dates else None
    _resumo_final = (_hist_dash.get('dates', {}).get(_last_hist_date, {}) if _last_hist_date else {})
    _entry = {
        'mes': _prev_month,
        'fechado_em': datetime.now().isoformat(),
        'meta_file': os.path.basename(_prev_meta_path),
        'meta_final': _prev_meta,
        'empresa_final': _resumo_final.get('empresa', {}),
        'filiais_finais': _resumo_final.get('filiais', {}),
        'vendedores_finais': _resumo_final.get('vendedores', {}),
        'ultimo_dia_historico': _last_hist_date,
        'snapshot_final_data': (_last_prev_snap or {}).get('data', _last_hist_date),
        'snapshot_final_path': (_last_prev_snap or {}).get('_path', ''),
        'config_global_fechamento': _config_global,
        'config_individual_fechamento': _config_ind,
    }
    _fech['months'][_prev_month] = _entry
    with open(_fechamento_path, 'w', encoding='utf-8') as _f:
        json.dump(_fech, _f, ensure_ascii=False, indent=2)
    print(f'📦 Fechamento mensal travado salvo: {_prev_month}')
    return _fech


ensure_month_reference_locked(mes_str, hoje_str)

# ── Base mensal opcional via relatório de início do mês ───────────────
MESES_PT = {
    "jan": "01", "janeiro": "01",
    "fev": "02", "fevereiro": "02",
    "mar": "03", "marco": "03", "março": "03",
    "abr": "04", "abril": "04",
    "mai": "05", "maio": "05",
    "jun": "06", "junho": "06",
    "jul": "07", "julho": "07",
    "ago": "08", "agosto": "08",
    "set": "09", "setembro": "09",
    "out": "10", "outubro": "10",
    "nov": "11", "novembro": "11",
    "dez": "12", "dezembro": "12",
}

def _month_from_filename(_name):
    _n = os.path.basename(str(_name)).lower()
    _n = _n.replace("ç", "c")
    for _mes_nome, _mes_num in sorted(MESES_PT.items(), key=lambda x: len(x[0]), reverse=True):
        if _mes_nome in _n:
            _m = re.search(r"(20\d{2}|\d{2})", _n)
            if _m:
                _yy = _m.group(1)
                _yy = f"20{_yy}" if len(_yy) == 2 else _yy
                return f"{_yy}-{_mes_num}"
    return None

def _find_base_report_for_month(_month_str):
    _cands = []
    for _root in [pasta, CACHE_DIR]:
        try:
            for _name in os.listdir(_root):
                _low = _name.lower()
                if ("meta inicio" in _low or "meta_inicio" in _low) and _low.endswith((".xls", ".xlsx")):
                    if _month_from_filename(_name) == _month_str:
                        _cands.append(os.path.join(_root, _name))
        except Exception:
            pass
    if not _cands:
        return None
    _cands = sorted(set(_cands), key=lambda p: os.path.getmtime(p), reverse=True)
    return _cands[0]

def _parse_base_report_faixas(_path, _month_str):
    _base_date = datetime.strptime(f"{_month_str}-01", "%Y-%m-%d")
    _dfb = pd.read_excel(_path, header=None)
    _vend_atual = None
    _out_v = {}
    _out_f = {}

    for _i in range(len(_dfb)):
        _row = _dfb.iloc[_i]
        _c0 = str(_row[COL["filial"]]).strip()
        _c1 = str(_row[COL["cliente"]]).strip()

        if "Vendedor:" in _c0:
            _vend_atual = limpar_nome_erp(_c0)
            continue

        if _c1 in ("nan", "", "Cliente", "Filial"):
            continue
        if _c0.upper().startswith("FILIAL") and _c1 in ("nan", "", "Cliente", "Filial"):
            continue
        if not _vend_atual:
            continue

        _venc = _parse_data(_row[COL["vencimento"]])
        _pend = tratar_valor(_row[COL["pendente"]])
        if not _venc or _pend <= 0:
            continue
        if str(_row[COL["conta_caixa"]]).strip() == "Caixa Filial 100":
            continue

        _dias = (_base_date - _venc).days
        if _dias >= 60:
            _fx = "grave"
        elif 30 <= _dias < 60:
            _fx = "alerta"
        elif 15 <= _dias < 30:
            _fx = "atencao"
        else:
            continue

        _fv, _ig = extrair_filial_nome(_vend_atual)
        _nome = limpar_nome_display(_vend_atual)

        if _fv is not None:
            _filial = str(_fv).strip().upper()
        else:
            _lookup = _filial_inativo_lookup.get(_nome, "")
            if _lookup == "FDEP" or _nome in _nomes_fdep:
                continue
            elif _lookup:
                _filial = str(_lookup).strip().upper()
            else:
                _fil_txt = str(_row[COL["filial"]]).upper()
                _mfil = re.search(r"FILIAL\s*(\d+)", _fil_txt)
                _filial = f"F{int(_mfil.group(1))}" if _mfil else "OUTROS"

        _key = f"{_nome}_{_filial}"
        _out_v.setdefault(_key, {"grave": 0.0, "alerta": 0.0, "atencao": 0.0})
        _out_f.setdefault(_filial, {"grave": 0.0, "alerta": 0.0, "atencao": 0.0})
        _out_v[_key][_fx] += float(_pend)
        _out_f[_filial][_fx] += float(_pend)

    for _d in (_out_v, _out_f):
        for _k, _vals in _d.items():
            for _fx in ["grave", "alerta", "atencao"]:
                _vals[_fx] = round(float(_vals.get(_fx, 0) or 0), 2)
    return {"data": f"{_month_str}-01", "vendedores": _out_v, "filiais": _out_f, "arquivo": os.path.basename(_path)}

BASE_MENSAL_INFO = {"data": f"{mes_str}-01", "vendedores": {}, "filiais": {}, "arquivo": ""}
_base_report_path = _find_base_report_for_month(mes_str)
if _base_report_path:
    try:
        BASE_MENSAL_INFO = _parse_base_report_faixas(_base_report_path, mes_str)
        _base_meta_path = os.path.join(CACHE_DIR, f"base_meta_{mes_str}.json")
        with open(_base_meta_path, "w", encoding="utf-8") as _fbm:
            json.dump(BASE_MENSAL_INFO, _fbm, ensure_ascii=False, indent=2)
        with open(ref_path(mes_str), "w", encoding="utf-8") as _fr:
            json.dump({
                "data": BASE_MENSAL_INFO["data"],
                "gerado_em": datetime.now().isoformat(),
                "origem": "arquivo_base_relatorio",
                "arquivo_base": os.path.basename(_base_report_path),
                "snapshot_origem_data": BASE_MENSAL_INFO["data"],
            }, _fr, ensure_ascii=False, indent=2)
        print(f"🧷 Base mensal carregada do relatório: {os.path.basename(_base_report_path)}")
    except Exception as _e_base:
        print(f"⚠️ Erro lendo base mensal {_base_report_path}: {_e_base}")
else:
    _base_meta_path = os.path.join(CACHE_DIR, f"base_meta_{mes_str}.json")
    if os.path.exists(_base_meta_path):
        try:
            with open(_base_meta_path, "r", encoding="utf-8") as _fbm:
                BASE_MENSAL_INFO = json.load(_fbm)
            print(f"🧷 Base mensal reutilizada do cache: {os.path.basename(_base_meta_path)}")
        except Exception:
            pass

# ── Snapshot de hoje ──────────────────────────────────────────────────
snapshot_hoje = {
    "data": hoje_str, "gerado_em": datetime.now().isoformat(),
    "total_p": total_final_p, "total_pg": total_final_pg,
    "filiais": {}, "vendedores": {}
}

for f in ORDEM_FILIAIS:
    sub = df_vend[df_vend["filial_vendedor"] == f]
    if not sub.empty:
        snapshot_hoje["filiais"][f] = {
            "pendente": round(sub["pendente"].sum(), 2),
            "pago":     round(sub["pago"].sum(), 2), "sem_ativo": False
        }
    elif f in filiais_sem_ativo:
        snapshot_hoje["filiais"][f] = {
            "pendente": round(filiais_sem_ativo[f]["pendente"], 2),
            "pago":     round(filiais_sem_ativo[f]["pago"], 2), "sem_ativo": True
        }

for _, row in df_vend.iterrows():
    key = f"{row['nome_exibicao']}_{row['filial_vendedor']}"
    snapshot_hoje["vendedores"][key] = {
        "nome": str(row["nome_exibicao"]), "filial": str(row["filial_vendedor"]),
        "pendente": round(float(row["pendente"]), 2),
        "pago":     round(float(row["pago"]), 2),
        "total":    round(float(row["total"]), 2),
        "is_gerente": bool(row["is_gerente"]),
        # Totais de pago por faixa (para calcular delta no próximo dia)
        "pago_grave":   round(recebido_faixa.get(
            f"{row['nome_exibicao']}_{row['filial_vendedor']}", {}).get('grave', 0.0), 2),
        "pago_alerta":  round(recebido_faixa.get(
            f"{row['nome_exibicao']}_{row['filial_vendedor']}", {}).get('alerta', 0.0), 2),
        "pago_atencao": round(recebido_faixa.get(
            f"{row['nome_exibicao']}_{row['filial_vendedor']}", {}).get('atencao', 0.0), 2),
    }

# Salva chaves dos títulos de hoje para identificar novos amanhã
snapshot_hoje["clientes_keys"] = list(clientes_key_hoje)

with open(cache_path(hoje_str), "w", encoding="utf-8") as f:
    json.dump(snapshot_hoje, f, ensure_ascii=False, indent=2)
print(f"💾 Snapshot salvo: {cache_path(hoje_str)}")

# ── Comparativos ──────────────────────────────────────────────────────
def load_snapshot(d):
    p = cache_path(d)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f: return json.load(f)
    return None

ontem_str  = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
snap_ontem = load_snapshot(ontem_str)
semana_str = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
snap_semana= load_snapshot(semana_str)

if not snap_ontem:
    for d in range(2, 30):
        snap_ontem = load_snapshot((datetime.now()-timedelta(days=d)).strftime("%Y-%m-%d"))
        if snap_ontem: break

# Identifica clientes NOVOS agora que snap_ontem está disponível
_clientes_ontem = set(snap_ontem.get("clientes_keys", [])) if snap_ontem else set()
_novos_keys = clientes_key_hoje - _clientes_ontem
for _c in clientes_cobrar:
    _c['novo'] = _c['titulo_key'] in _novos_keys
_nn = sum(1 for _c in clientes_cobrar if _c.get('novo'))
print(f"   🆕 Clientes novos hoje: {_nn}")

# ── Variações ─────────────────────────────────────────────────────────
var_vendedores = {}
if snap_ontem:
    for key, vd in snapshot_hoje["vendedores"].items():
        ant = snap_ontem.get("vendedores", {}).get(key)
        if ant:
            delta = round(vd["pago"] - ant["pago"], 2)
            perc  = round(delta / ant["pago"] * 100, 1) if ant["pago"] > 0 else None
            var_vendedores[key] = {
                "delta_pago": delta, "perc_pago": perc,
                "periodo": snap_ontem["data"]
            }

var_filiais = {}
if snap_ontem:
    for f, fd in snapshot_hoje["filiais"].items():
        ant = snap_ontem.get("filiais", {}).get(f)
        if ant:
            delta = round(fd["pago"] - ant["pago"], 2)
            perc  = round(delta / ant["pago"] * 100, 1) if ant["pago"] > 0 else None
            var_filiais[f] = {
                "delta_pago": delta, "perc_pago": perc,
                "periodo": snap_ontem["data"]
            }

# ── META MENSAL (nova lógica por faixa) ──────────────────────────────
# Cada faixa tem meta própria baseada no PENDENTE daquela faixa:
#   Grave  → meta = 20% do pendente grave
#   Alerta → meta = 15% do pendente alerta
#   Atenção→ meta = 10% do pendente atenção
# Gráfico geral = média ponderada 60/30/10 dos 3 gráficos
#
# O pendente por faixa é estimado do total pendente com os pesos 50/30/20
# (grave≈50%, alerta≈30%, atenção≈20% do total — estimativa para o alvo)
# O recebimento por faixa é o delta acumulado × peso da faixa

meta_file = meta_path(mes_str)
if os.path.exists(meta_file):
    with open(meta_file, encoding="utf-8") as f:
        meta_mes = json.load(f)
    meta_mes["ultima_atualizacao"] = hoje_str
    meta_mes["snapshots_count"] = meta_mes.get("snapshots_count", 0) + 1
else:
    meta_mes = {
        "mes": mes_str, "criado_em": hoje_str,
        "ultima_atualizacao": hoje_str, "snapshots_count": 1,
        "vendedores": {}, "filiais": {}
    }

def calc_pendente_faixas(pendente_total):
    """Estima pendente por faixa a partir do total pendente."""
    return {
        "grave":   round(pendente_total * 0.50, 2),
        "alerta":  round(pendente_total * 0.30, 2),
        "atencao": round(pendente_total * 0.20, 2),
    }

def get_base_faixas_vendedor(key, pendente_total):
    _base = (BASE_MENSAL_INFO.get("vendedores", {}) or {}).get(key)
    if isinstance(_base, dict) and sum(float(_base.get(_fx, 0) or 0) for _fx in ["grave","alerta","atencao"]) > 0:
        return {
            "grave": round(float(_base.get("grave", 0) or 0), 2),
            "alerta": round(float(_base.get("alerta", 0) or 0), 2),
            "atencao": round(float(_base.get("atencao", 0) or 0), 2),
        }
    return calc_pendente_faixas(pendente_total)

def get_base_faixas_filial(filial, pendente_total):
    _base = (BASE_MENSAL_INFO.get("filiais", {}) or {}).get(filial)
    if isinstance(_base, dict) and sum(float(_base.get(_fx, 0) or 0) for _fx in ["grave","alerta","atencao"]) > 0:
        return {
            "grave": round(float(_base.get("grave", 0) or 0), 2),
            "alerta": round(float(_base.get("alerta", 0) or 0), 2),
            "atencao": round(float(_base.get("atencao", 0) or 0), 2),
        }
    return calc_pendente_faixas(pendente_total)

def calc_metas_alvo(faixas, cfg=None):
    """Calcula alvo de meta de cada faixa usando config (global ou individual)."""
    c = cfg or CONFIG_META
    return {
        "grave_alvo":   round(faixas["grave"]   * c["grave_pct"]   / 100, 2),
        "alerta_alvo":  round(faixas["alerta"]  * c["alerta_pct"]  / 100, 2),
        "atencao_alvo": round(faixas["atencao"] * c["atencao_pct"] / 100, 2),
    }

def calc_perc_geral(grave_perc, alerta_perc, atencao_perc, cfg=None):
    """Gráfico geral ponderado pelos pesos da config."""
    c = cfg or CONFIG_META
    pg = c["peso_grave"]   / 100
    pa = c["peso_alerta"]  / 100
    pt = c["peso_atencao"] / 100
    return round(grave_perc * pg + alerta_perc * pa + atencao_perc * pt, 1)

# =========================================================================
# RECEBIMENTOS E META — FONTE ÚNICA
# Regra:
#   1. Lê todos os títulos pagos no período (pagto > data_corte, conta caixa ≠ 100)
#   2. Classifica por faixa de vencimento (grave/alerta/atenção)
#   3. Distribui inativos e FDEP para ativos da filial (60% gerente / 40% vendedores)
#   4. recebimentos_det_js = relatório visual (com detalhes dos títulos)
#   5. recebido_faixa = somatório por faixa por vendedor (para os gráficos de meta)
#   OS DOIS SÃO DERIVADOS DA MESMA FONTE → valores sempre batem
# =========================================================================

# Passo A: Lê títulos brutos do XLS (todos os vendedores)
# _rec_raw[chave] = {grave:[], alerta:[], atencao:[], is_ativo, is_fdep, filial}
_rec_raw = {}
_vd2 = None

for _i2 in range(len(df_raw)):
    _row2 = df_raw.iloc[_i2]
    _c02 = str(_row2[COL["filial"]]).strip()
    _c12 = str(_row2[COL["cliente"]]).strip()

    if "Vendedor:" in _c02:
        _vd2 = limpar_nome_erp(_c02)
        continue

    if _c12 in ("nan", "", "Cliente", "Filial"):
        continue
    if not _vd2:
        continue

    _venc2 = _parse_data(_row2[COL["vencimento"]])
    _pagto2 = _parse_data(_row2[COL["pagamento"]])
    _pago2 = tratar_valor(_row2[COL["pago_total"]])

    if not _venc2 or not _pagto2 or _pago2 <= 0:
        continue
    if _pagto2 <= _data_corte_parse:
        continue

    if str(_row2[COL["conta_caixa"]]).strip() == "Caixa Filial 100":
        continue

    _dias2 = (_hoje - _venc2).days

    if _dias2 >= 60:
        _f2 = "grave"
    elif 30 <= _dias2 < 60:
        _f2 = "alerta"
    elif 15 <= _dias2 < 30:
        _f2 = "atencao"
    else:
        continue

    _fv2, _ = extrair_filial_nome(_vd2)
    _nome2 = limpar_nome_display(_vd2)

    if _fv2 is not None:
        _fv2k = _fv2
        _is_at2 = True
        _is_fp2 = False
    else:
        _lk2 = _filial_inativo_lookup.get(_nome2, "")
        if _lk2 == "FDEP" or _nome2 in _nomes_fdep:
            _fv2k = "FDEP"
            _is_at2 = False
            _is_fp2 = True
        elif _lk2:
            _fv2k = _lk2
            _is_at2 = False
            _is_fp2 = False
        else:
            _fv2k = "OUTROS"
            _is_at2 = False
            _is_fp2 = False

    _kv2 = f"{_nome2}_{_fv2k}"

    if _kv2 not in _rec_raw:
        _rec_raw[_kv2] = {
            "grave": [],
            "alerta": [],
            "atencao": [],
            "is_ativo": _is_at2,
            "is_fdep": _is_fp2,
            "filial": _fv2k,
        }

    _rec_raw[_kv2][_f2].append({
        "cliente": _c12[:40],
        "dias": _dias2,
        "pago": _pago2,
        "vencimento": str(_row2[COL["vencimento"]]).strip(),
        "pagamento": str(_row2[COL["pagamento"]]).strip(),
        "parcela": str(_row2[COL["num_parcela"]]).strip(),
        "titulo": str(_row2[COL["num_titulo"]]).strip(),
        "vendedor": (_nome2 + ("" if _is_at2 else (" [FDEP]" if _is_fp2 else " [Inativo]")))[:30],
    })

# Passo B: Separa ativos, inativos por filial, e FDEP (lista única)
_inat_por_fil = {}   # {filial: {faixa: [títulos]}}
_fdep_lista   = {'grave':[], 'alerta':[], 'atencao':[]}

for _kv2, _rb in _rec_raw.items():
    if _rb['is_ativo']:
        continue
    elif _rb['is_fdep']:
        for _fx in ['grave','alerta','atencao']:
            _fdep_lista[_fx].extend(_rb[_fx])
    else:
        _ff2 = _rb['filial']
        if _ff2 not in _inat_por_fil:
            _inat_por_fil[_ff2] = {'grave':[], 'alerta':[], 'atencao':[]}
        for _fx in ['grave','alerta','atencao']:
            _inat_por_fil[_ff2][_fx].extend(_rb[_fx])

# Distribui FDEP por filial proporcional ao peso (SEM duplicar títulos)
_fdep_por_fil = {}
if tw > 0:
    _fils_ord = sorted([(f, pesos.get(f,0)) for f in ORDEM_FILIAIS if pesos.get(f,0)>0],
                       key=lambda x: x[1], reverse=True)
    for _fx in ['grave','alerta','atencao']:
        _todos = _fdep_lista[_fx][:]
        _n = len(_todos); _s = 0
        for _ff_f, _w_f in _fils_ord:
            _q = round(_n * _w_f / tw)
            _e = min(_s + _q, _n)
            if _ff_f not in _fdep_por_fil:
                _fdep_por_fil[_ff_f] = {'grave':[], 'alerta':[], 'atencao':[]}
            _fdep_por_fil[_ff_f][_fx] = _todos[_s:_e]
            _s = _e

# Passo C: Constrói recebimentos_det_js (relatório visual)
# Chaves finais: "NOME_Fx" para ativos, "Filial Fx_Fx" para filiais sem ativo
_chaves_validas   = {f"{r['nome_exibicao']}_{r['filial_vendedor']}" for _, r in df_vend.iterrows()}
_chaves_sem_ativo = {f"Filial {f}_{f}" for f in filiais_sem_ativo}

recebimentos_det_js = {}

# 1) Títulos próprios dos ativos
for _kv2, _rb in _rec_raw.items():
    if _rb['is_ativo']:
        recebimentos_det_js[_kv2] = {
            'grave':  list(_rb['grave']),
            'alerta': list(_rb['alerta']),
            'atencao':list(_rb['atencao']),
        }

# 2) Distribui inativos e FDEP: 60% gerente / 40% vendedores por filial
for _fil_r in ORDEM_FILIAIS:
    _vends_r2   = [r['nome_exibicao'] for _, r in df_vend[
        (df_vend['filial_vendedor']==_fil_r)&(~df_vend['is_gerente'])].iterrows()]
    _gerents_r2 = [r['nome_exibicao'] for _, r in df_vend[
        (df_vend['filial_vendedor']==_fil_r)&( df_vend['is_gerente'])].iterrows()]
    _sem_at_r   = _fil_r in filiais_sem_ativo

    for _src2 in [_inat_por_fil.get(_fil_r,{}), _fdep_por_fil.get(_fil_r,{})]:
        for _fx in ['grave','alerta','atencao']:
            _titulos2 = _src2.get(_fx, [])
            if not _titulos2: continue

            if _sem_at_r:
                # Filial sem ativo: 100% vai para a filial
                _kf2 = f"Filial {_fil_r}_{_fil_r}"
                if _kf2 not in recebimentos_det_js:
                    recebimentos_det_js[_kf2] = {'grave':[],'alerta':[],'atencao':[]}
                recebimentos_det_js[_kf2][_fx].extend(_titulos2)
            else:
                _ng2  = round(len(_titulos2) * 0.60)
                _gp2  = _titulos2[:_ng2]
                _vp2  = _titulos2[_ng2:]
                # Gerente recebe 60%
                for _g2 in _gerents_r2:
                    _kg2 = f"{_g2}_{_fil_r}"
                    if _kg2 not in recebimentos_det_js:
                        recebimentos_det_js[_kg2] = {'grave':[],'alerta':[],'atencao':[]}
                    recebimentos_det_js[_kg2][_fx].extend(_gp2)
                # Vendedores recebem 40% em round-robin
                if _vends_r2:
                    for _ii2, _t2 in enumerate(_vp2):
                        _kv2d = f"{_vends_r2[_ii2 % len(_vends_r2)]}_{_fil_r}"
                        if _kv2d not in recebimentos_det_js:
                            recebimentos_det_js[_kv2d] = {'grave':[],'alerta':[],'atencao':[]}
                        recebimentos_det_js[_kv2d][_fx].append(_t2)
                elif _gerents_r2:
                    # Sem vendedores ativos: tudo vai para o gerente
                    for _t2 in _vp2:
                        _kg2 = f"{_gerents_r2[0]}_{_fil_r}"
                        if _kg2 not in recebimentos_det_js:
                            recebimentos_det_js[_kg2] = {'grave':[],'alerta':[],'atencao':[]}
                        recebimentos_det_js[_kg2][_fx].append(_t2)

# Filtra: mantém só chaves de vendedores ativos + filiais sem ativo
recebimentos_det_js = {
    k: {'grave': sorted(v['grave'], key=lambda x: x['pago'], reverse=True),
        'alerta':sorted(v['alerta'],key=lambda x: x['pago'], reverse=True),
        'atencao':sorted(v['atencao'],key=lambda x: x['pago'],reverse=True)}
    for k, v in recebimentos_det_js.items()
    if k in _chaves_validas or k in _chaves_sem_ativo
}

recebimentos_terceiro_js = {'grave': [], 'alerta': [], 'atencao': []}
for _krt, _vrt in recebimentos_det_js.items():
    for _fxrt in ['grave', 'alerta', 'atencao']:
        for _rrt in (_vrt.get(_fxrt) or []):
            if cobranca_row_key_py(_rrt) in _clientes_terceiro_keys:
                recebimentos_terceiro_js[_fxrt].append(_rrt)
for _fxrt in ['grave', 'alerta', 'atencao']:
    recebimentos_terceiro_js[_fxrt].sort(key=lambda x: float(x.get('pago', 0) or 0), reverse=True)

# Passo D: Deriva recebido_faixa — MESMA FONTE que o relatório
# recebido_faixa[chave] = soma dos valores pagos por faixa
# GARANTE que meta e relatório usam exatamente os mesmos números
recebido_faixa = {}

for _kd, _vd_det in recebimentos_det_js.items():
    _nome_d   = _kd.rsplit('_', 1)[0] if '_' in _kd else _kd
    _filial_d = _kd.rsplit('_', 1)[1] if '_' in _kd else 'OUTROS'

    # 🔥 identifica se é filial sem ativo
    _is_filial_sem_ativo = _kd in _chaves_sem_ativo

    recebido_faixa[_kd] = {
        'grave':   sum(t['pago'] for t in _vd_det['grave']),
        'alerta':  sum(t['pago'] for t in _vd_det['alerta']),
        'atencao': sum(t['pago'] for t in _vd_det['atencao']),

        # 🔥 CORREÇÃO PRINCIPAL
        'is_ativo': (_kd not in _chaves_sem_ativo),

        'is_fdep':  False,
        'filial':   _filial_d,
    }

    # 🔥 CORREÇÃO FINAL (ESSA RESOLVE A F5)
    if _kd.startswith("Filial "):
        recebido_faixa[_kd]['is_ativo'] = False


_pre_inat_rec = {f: {'grave':0.0,'alerta':0.0,'atencao':0.0} for f in ORDEM_FILIAIS}
_pre_fdep_rec = {f: {'grave':0.0,'alerta':0.0,'atencao':0.0} for f in ORDEM_FILIAIS}
_pre_ativos_filial = {f: 0 for f in ORDEM_FILIAIS}  # conta vendedores ativos p/ divisão

for _kk, _rv in recebido_faixa.items():
    _is_at = _rv.get('is_ativo', False)
    _is_fp = _rv.get('is_fdep', False)
    _ff_k  = _rv.get('filial', '')

    # 🔥 ATIVOS → contam normalmente
    if _is_at and _ff_k in _pre_ativos_filial:
        _pre_ativos_filial[_ff_k] += 1

    # 🔥 INATIVOS + FILIAL SEM ATIVO (CORRIGIDO)
    elif not _is_at and not _is_fp:

        # 🔥 DETECTA SE É BLOCO DE FILIAL (ex: "Filial F5_F5")
        if _kk.startswith("Filial "):
            if _ff_k in _pre_inat_rec:
                for _fx in ['grave','alerta','atencao']:
                    _pre_inat_rec[_ff_k][_fx] += _rv.get(_fx, 0.0)

        else:
            # 🔥 INATIVO NORMAL
            if _ff_k in _pre_inat_rec:
                for _fx in ['grave','alerta','atencao']:
                    _pre_inat_rec[_ff_k][_fx] += _rv.get(_fx, 0.0)

    # 🔥 FDEP → rateio proporcional
    elif _is_fp:
        for _ff2 in ORDEM_FILIAIS:
            _w2 = pesos.get(_ff2, 0)
            if tw > 0 and _w2 > 0:
                for _fx in ['grave','alerta','atencao']:
                    _pre_fdep_rec[_ff2][_fx] += _rv.get(_fx, 0.0) * _w2 / tw

# Atualiza meta de vendedores
for key, vd in snapshot_hoje["vendedores"].items():
    ant_pago = 0.0
    if snap_ontem:
        ant_vd = snap_ontem.get("vendedores", {}).get(key)
        if ant_vd: ant_pago = ant_vd["pago"]
    delta = max(vd["pago"] - ant_pago, 0)

    _cfg_key = get_config_meta(key)  # config individual ou global
    if key not in meta_mes["vendedores"]:
        faixas = get_base_faixas_vendedor(key, vd["pendente"])
        alvos  = calc_metas_alvo(faixas, _cfg_key)
        meta_mes["vendedores"][key] = {
            "nome": vd["nome"], "filial": vd["filial"], "is_gerente": vd["is_gerente"],
            # Recebimentos acumulados por faixa
            "grave_rec":   0.0, "alerta_rec":  0.0, "atencao_rec": 0.0,
            # Alvos fixos por faixa
            "grave_alvo":   alvos["grave_alvo"],
            "alerta_alvo":  alvos["alerta_alvo"],
            "atencao_alvo": alvos["atencao_alvo"],
            # Pendentes da faixa (base do alvo)
            "grave_pend":   faixas["grave"],
            "alerta_pend":  faixas["alerta"],
            "atencao_pend": faixas["atencao"],
            "snapshots": []
        }

    vm = meta_mes["vendedores"][key]
    # Acumula delta pelos pesos das faixas
    # Recebimento real do período por faixa (usa pré-cálculo feito antes do loop)
    _filial_vend = vd.get("filial", "")
    _is_ger      = vd.get("is_gerente", False)

    # Próprio: apenas se é vendedor ativo registrado em recebido_faixa
    _rv_proprio = recebido_faixa.get(key, {})
    _grave_delta   = _rv_proprio.get('grave',   0.0) if _rv_proprio.get('is_ativo') else 0.0
    _alerta_delta  = _rv_proprio.get('alerta',  0.0) if _rv_proprio.get('is_ativo') else 0.0
    _atencao_delta = _rv_proprio.get('atencao', 0.0) if _rv_proprio.get('is_ativo') else 0.0

    # Parcela de inativos + FDEP da filial
    if _filial_vend:
        _n_at = max(_pre_ativos_filial.get(_filial_vend, 1), 1)
        for _fx in ['grave','alerta','atencao']:
            _tot = (_pre_inat_rec.get(_filial_vend, {}).get(_fx, 0.0) +
                    _pre_fdep_rec.get(_filial_vend, {}).get(_fx, 0.0))
            _share = _tot * 0.60 if _is_ger else _tot * 0.40 / _n_at
            if _fx == 'grave':    _grave_delta   += _share
            elif _fx == 'alerta': _alerta_delta  += _share
            else:                 _atencao_delta += _share

    # 🔥 CORREÇÃO: não acumular novamente a cada reprocessamento do mesmo período.
    # O gráfico do vendedor deve refletir os valores reais atuais do período, assim como já ocorre nas filiais.
    vm["grave_rec"]   = round(_grave_delta,   2)
    vm["alerta_rec"]  = round(_alerta_delta,  2)
    vm["atencao_rec"] = round(_atencao_delta, 2)
    vm["snapshots"].append({
        "data": hoje_str, "delta": delta,
        "grave_delta": _grave_delta, "alerta_delta": _alerta_delta, "atencao_delta": _atencao_delta
    })

    # Migração: se registro antigo não tem campos de faixa, recalcula
    if "grave_alvo" not in vm:
        faixas_mig = get_base_faixas_vendedor(key, vd.get("pendente", 0))
        alvos_mig  = calc_metas_alvo(faixas_mig)
        vm.update({
            "grave_alvo":   alvos_mig["grave_alvo"],
            "alerta_alvo":  alvos_mig["alerta_alvo"],
            "atencao_alvo": alvos_mig["atencao_alvo"],
            "grave_pend":   faixas_mig["grave"],
            "alerta_pend":  faixas_mig["alerta"],
            "atencao_pend": faixas_mig["atencao"],
        })

    # Base mensal do relatório, se existir, prevalece como alvo do mês
    _faixas_base_vm = get_base_faixas_vendedor(key, vd.get("pendente", 0))
    _alvos_base_vm = calc_metas_alvo(_faixas_base_vm, _cfg_key)
    vm["grave_pend"] = _faixas_base_vm["grave"]
    vm["alerta_pend"] = _faixas_base_vm["alerta"]
    vm["atencao_pend"] = _faixas_base_vm["atencao"]
    vm["grave_alvo"] = _alvos_base_vm["grave_alvo"]
    vm["alerta_alvo"] = _alvos_base_vm["alerta_alvo"]
    vm["atencao_alvo"] = _alvos_base_vm["atencao_alvo"]

    # Percentuais por faixa
    ga = vm["grave_alvo"];   gr = vm["grave_rec"]
    aa = vm["alerta_alvo"];  ar = vm["alerta_rec"]
    ta = vm["atencao_alvo"]; tr = vm["atencao_rec"]
    vm["grave_perc"]   = round(min(gr/ga*100, 100), 1) if ga > 0 else 0.0
    vm["alerta_perc"]  = round(min(ar/aa*100, 100), 1) if aa > 0 else 0.0
    vm["atencao_perc"] = round(min(tr/ta*100, 100), 1) if ta > 0 else 0.0
    vm["perc_meta"]    = calc_perc_geral(vm["grave_perc"], vm["alerta_perc"], vm["atencao_perc"], _cfg_key)

# Atualiza meta de filiais
for f, fd in snapshot_hoje["filiais"].items():

    ant_fd_pago = 0.0
    if snap_ontem:
        ant_fd = snap_ontem.get("filiais", {}).get(f, {})
        ant_fd_pago = ant_fd.get("pago", 0)

    delta_f = max(fd["pago"] - ant_fd_pago, 0)

    # =========================================
    # CRIA META SE NÃO EXISTIR
    # =========================================
    if f not in meta_mes["filiais"]:
        faixas_f = get_base_faixas_filial(f, fd["pendente"])
        alvos_f  = calc_metas_alvo(faixas_f)

        meta_mes["filiais"][f] = {
            "grave_rec": 0.0,
            "alerta_rec": 0.0,
            "atencao_rec": 0.0,

            "grave_alvo":   alvos_f["grave_alvo"],
            "alerta_alvo":  alvos_f["alerta_alvo"],
            "atencao_alvo": alvos_f["atencao_alvo"],

            "grave_pend":   faixas_f["grave"],
            "alerta_pend":  faixas_f["alerta"],
            "atencao_pend": faixas_f["atencao"],
        }

    fm = meta_mes["filiais"][f]

    # =========================================
    # 🔥 CORREÇÃO DEFINITIVA
    # =========================================
    _f_grave_delta  = 0.0
    _f_alerta_delta = 0.0
    _f_atenc_delta  = 0.0

    for _rv in recebido_faixa.values():
        if _rv.get("filial") == f:
            _f_grave_delta  += _rv.get("grave", 0.0)
            _f_alerta_delta += _rv.get("alerta", 0.0)
            _f_atenc_delta  += _rv.get("atencao", 0.0)

    # 🔥 VALOR REAL DO PERÍODO (NÃO ACUMULA)
    fm["grave_rec"]   = round(_f_grave_delta,  2)
    fm["alerta_rec"]  = round(_f_alerta_delta, 2)
    fm["atencao_rec"] = round(_f_atenc_delta,  2)

    # =========================================
    # 🔄 SEGURANÇA (migração)
    # =========================================
    if "grave_alvo" not in fm:
        faixas_mig_f = get_base_faixas_filial(f, fd.get("pendente", 0))
        alvos_mig_f  = calc_metas_alvo(faixas_mig_f)

        fm.update({
            "grave_alvo":   alvos_mig_f["grave_alvo"],
            "alerta_alvo":  alvos_mig_f["alerta_alvo"],
            "atencao_alvo": alvos_mig_f["atencao_alvo"],
            "grave_pend":   faixas_mig_f["grave"],
            "alerta_pend":  faixas_mig_f["alerta"],
            "atencao_pend": faixas_mig_f["atencao"],
        })

    # Base mensal do relatório, se existir, prevalece como alvo do mês
    _faixas_base_fm = get_base_faixas_filial(f, fd.get("pendente", 0))
    _alvos_base_fm = calc_metas_alvo(_faixas_base_fm)
    fm["grave_pend"] = _faixas_base_fm["grave"]
    fm["alerta_pend"] = _faixas_base_fm["alerta"]
    fm["atencao_pend"] = _faixas_base_fm["atencao"]
    fm["grave_alvo"] = _alvos_base_fm["grave_alvo"]
    fm["alerta_alvo"] = _alvos_base_fm["alerta_alvo"]
    fm["atencao_alvo"] = _alvos_base_fm["atencao_alvo"]

    # =========================================
    # 📊 % META
    # =========================================
    ga = fm["grave_alvo"];   gr = fm["grave_rec"]
    aa = fm["alerta_alvo"];  ar = fm["alerta_rec"]
    ta = fm["atencao_alvo"]; tr = fm["atencao_rec"]

    fm["grave_perc"]   = round(min(gr/ga*100,100),1) if ga>0 else 0.0
    fm["alerta_perc"]  = round(min(ar/aa*100,100),1) if aa>0 else 0.0
    fm["atencao_perc"] = round(min(tr/ta*100,100),1) if ta>0 else 0.0

    fm["perc_meta"] = calc_perc_geral(
        fm["grave_perc"],
        fm["alerta_perc"],
        fm["atencao_perc"]
    )

# =========================================
# 💾 SALVA
# =========================================
with open(meta_file, "w", encoding="utf-8") as f:
    json.dump(meta_mes, f, ensure_ascii=False, indent=2)

print(f"🎯 Meta do mês atualizada: {meta_file}")
print("\n===== DEBUG FILIAL F5 =====")

for k, v in recebido_faixa.items():
    if "F5" in str(v.get("filial")):
        print(k, v)
# ── Média trimestral ──────────────────────────────────────────────────
meses_trim = []
for i in range(3):
    m = (datetime.now() - timedelta(days=30*i)).strftime("%Y-%m")
    if os.path.exists(meta_path(m)):
        with open(meta_path(m), encoding="utf-8") as f:
            meses_trim.append(json.load(f))

media_trimestral_vend = {}
if meses_trim:
    all_keys = set()
    for mm in meses_trim: all_keys.update(mm.get("vendedores",{}).keys())
    for key in all_keys:
        percs = [mm["vendedores"][key]["perc_meta"]
                 for mm in meses_trim if key in mm.get("vendedores",{})]
        if percs:
            ref = next(mm["vendedores"][key] for mm in meses_trim if key in mm.get("vendedores",{}))
            media_trimestral_vend[key] = {
                "nome": ref["nome"], "filial": ref["filial"],
                "media_perc": round(sum(percs)/len(percs), 1),
                "meses_count": len(percs)
            }

media_trimestral_fil = {}
for f in ORDEM_FILIAIS:
    percs_f = [mm["filiais"].get(f,{}).get("perc_meta",0)
               for mm in meses_trim if f in mm.get("filiais",{})]
    if percs_f:
        media_trimestral_fil[f] = round(sum(percs_f)/len(percs_f), 1)


# (filtro aplicado anteriormente)


# Pré-calcula recebimentos de inativos e FDEP por filial (para rateio na meta)
# Feito FORA do loop para não recalcular a cada vendedor
# ── Destaque da semana ─────────────────────────────────────────────────
destaque_semana = None
if snap_semana:
    melhor_f, melhor_d = None, -999999
    for f, fd in snapshot_hoje["filiais"].items():
        d = fd["pago"] - snap_semana.get("filiais",{}).get(f,{}).get("pago",0)
        if d > melhor_d: melhor_d, melhor_f = d, f
    if melhor_f:
        ref_pago = snap_semana["filiais"].get(melhor_f,{}).get("pago",1)
        destaque_semana = {
            "filial": melhor_f,
            "delta_pago": round(melhor_d, 2),
            "perc_ganho": round(melhor_d/ref_pago*100,1) if ref_pago>0 else 0,
            "periodo": snap_semana["data"]
        }
        print(f"🏆 Destaque da semana: {melhor_f} (+R$ {melhor_d:,.2f})")

print(f"📊 Histórico: {len(list(Path(CACHE_DIR).glob('snapshot_*.json')))} snapshots disponíveis")



# =========================================
# SERIALIZAR DADOS PARA O HTML (v2)
# =========================================
js_creds = json.dumps(credenciais, ensure_ascii=False)
js_metas_vendas = json.dumps(metas_vendas_info.get('dados', {}), ensure_ascii=False)
js_margens_brutas = json.dumps(margens_brutas_info.get('dados', {}), ensure_ascii=False)
# placeholders; valores reais serão definidos após montar _sales_emp/_sales_fil/_sales_vend
js_sales_empresa = json.dumps({}, ensure_ascii=False)
js_rent_empresa = json.dumps((margens_brutas_info.get('dados', {}) or {}).get('empresa', {}), ensure_ascii=False)

# relatório de serviços do mês atual (gerado pelo worker de vendas)
_servicos_rel_path = os.path.join(pasta, "relatorio_servicos_mes_atual.json")
_servicos_rel_data = {}
try:
    if os.path.exists(_servicos_rel_path):
        with open(_servicos_rel_path, "r", encoding="utf-8") as _fsrv:
            _servicos_rel_data = json.load(_fsrv) or {}
except Exception as _e:
    print(f"⚠️ Falha ao carregar relatorio_servicos_mes_atual.json: {_e}")
js_servicos_relatorio = json.dumps(_servicos_rel_data, ensure_ascii=False)

# Inativos e FDEP por filial
bruto_inat_p  = {f: 0.0 for f in ORDEM_FILIAIS + ["FDEP"]}
bruto_inat_pg = {f: 0.0 for f in ORDEM_FILIAIS + ["FDEP"]}
for _, r in inativos.iterrows():
    f = r["filial"]
    if f in bruto_inat_p:
        bruto_inat_p[f] += r["pendente"]; bruto_inat_pg[f] += r["pago"]

fdep_para_filial_p  = {}
fdep_para_filial_pg = {}
if tw > 0:
    for f, w in pesos.items():
        fdep_para_filial_p[f]  = round(fdep_total_rateado_p  * w / tw, 2)
        fdep_para_filial_pg[f] = round(fdep_total_rateado_pg * w / tw, 2)

def get_meta_vend(key):
    return meta_mes.get("vendedores", {}).get(key, {})

def get_meta_fil(f):
    return meta_mes.get("filiais", {}).get(f, {})

MARGENS_DADOS = margens_brutas_info.get("dados", {}) or {}
MARGENS_FILIAIS = MARGENS_DADOS.get("filiais", {}) or {}
MARGENS_VENDEDORES = MARGENS_DADOS.get("vendedores", {}) or {}

def margem_filial_pct(f):
    try:
        return round(float((MARGENS_FILIAIS.get(str(f), {}) or {}).get("margem_bruta_pct", 0) or 0), 2)
    except Exception:
        return 0.0

# Mesmo padrão usado na coleta de margens: nome normalizado + filial.
def margem_vendedor_pct(nome, filial):
    try:
        k = f"{_norm_key_margem(nome)}_{filial}"
        return round(float((MARGENS_VENDEDORES.get(k, {}) or {}).get("margem_bruta_pct", 0) or 0), 2)
    except Exception:
        return 0.0

# Vendedores por filial (somente NÃO gerentes para o painel individual)
todos_js = {}
for filial in ORDEM_FILIAIS:
    sub = df_vend[df_vend["filial_vendedor"] == filial]
    if sub.empty: continue
    # Somente vendedores (não gerentes) no painel individual
    sub_vend = sub[~sub["is_gerente"]]
    if sub_vend.empty:
        todos_js[filial] = []
        continue

    total_inat_p = bruto_inat_p.get(filial, 0.0)
    total_inat_pg= bruto_inat_pg.get(filial, 0.0)
    fdep_p       = fdep_para_filial_p.get(filial, 0.0)
    fdep_pg      = fdep_para_filial_pg.get(filial, 0.0)
    total_filial_pend = sub["pendente"].sum()

    todos_js[filial] = []
    for _, r in sub_vend.sort_values("pendente", ascending=False).iterrows():
        pf = float(r["pendente"])
        pg = float(r["pago"])
        prop = pf / total_filial_pend if total_filial_pend > 0 else 0
        inat_p = round(total_inat_p * prop, 2)
        fdp    = round(fdep_p * prop, 2)
        prop_p = round(pf - inat_p - fdp, 2)
        key    = f"{r['nome_exibicao']}_{filial}"
        mv     = get_meta_vend(key)
        tv     = media_trimestral_vend.get(key, {})
        vv     = var_vendedores.get(key, {})

        todos_js[filial].append({
            "nome": str(r["nome_exibicao"]), "filial": filial,
            "is_gerente": False,
            "pendente": round(pf,2), "pago": round(pg,2),
            "total": round(float(r["total"]),2),
            "perc_filial": round(float(r["perc_filial"]),2),
            "proprio_p": max(prop_p,0), "inat_p": inat_p, "fdep_p": fdp,
            "perc_inat": round(inat_p/pf*100,1) if pf>0 else 0,
            "perc_fdep": round(fdp/pf*100,1)    if pf>0 else 0,
            # variação
            "var_pago_perc":  vv.get("perc_pago"),
            "var_pago_delta": vv.get("delta_pago", 0),
            "var_periodo":    vv.get("periodo",""),
            # metas por faixa
            "grave_perc":    mv.get("grave_perc", 0),
            "alerta_perc":   mv.get("alerta_perc", 0),
            "atencao_perc":  mv.get("atencao_perc", 0),
            "perc_meta":     mv.get("perc_meta", 0),
            "grave_rec":     mv.get("grave_rec", 0),
            "alerta_rec":    mv.get("alerta_rec", 0),
            "atencao_rec":   mv.get("atencao_rec", 0),
            "grave_alvo":    mv.get("grave_alvo", 0),
            "alerta_alvo":   mv.get("alerta_alvo", 0),
            "atencao_alvo":  mv.get("atencao_alvo", 0),
            "grave_pend":    mv.get("grave_pend", 0),
            "alerta_pend":   mv.get("alerta_pend", 0),
            "atencao_pend":  mv.get("atencao_pend", 0),
            # trimestral
            "trim_media_perc": tv.get("media_perc", 0),
            "trim_meses":      tv.get("meses_count", 0),
            # rentabilidade / margem bruta SGI
            "rentabilidade_pct": margem_vendedor_pct(r["nome_exibicao"], filial),
        })

# Filiais (inclui totais de gerentes + vendedores)
filiais_js = {}

for f in ORDEM_FILIAIS:
    sub = df_vend[df_vend["filial_vendedor"] == f]

    inat_p = round(bruto_inat_p.get(f,0.0), 2)
    fdep_p = round(fdep_para_filial_p.get(f,0.0), 2)

    vf = var_filiais.get(f, {})
    mf = get_meta_fil(f) or {}
    tf = media_trimestral_fil.get(f, 0)

    # =========================================
    # 🔹 FILIAL COM VENDEDOR
    # =========================================
    if not sub.empty:
        pt = round(sub["pendente"].sum(), 2)
        pg = round(sub["pago"].sum(), 2)

        filiais_js[f] = {
            "pendente": pt,
            "pago": pg,
            "total": round(sub["total"].sum(), 2),
            "sem_ativo": False,

            "inat_p": inat_p,
            "fdep_p": fdep_p,

            "perc_inat": round(inat_p/pt*100,1) if pt>0 else 0,
            "perc_fdep": round(fdep_p/pt*100,1) if pt>0 else 0,

            "var_pago_perc":  vf.get("perc_pago"),
            "var_pago_delta": vf.get("delta_pago",0),
            "var_periodo":    vf.get("periodo",""),

            # 🔥 META
            "grave_perc":    mf.get("grave_perc",0),
            "alerta_perc":   mf.get("alerta_perc",0),
            "atencao_perc":  mf.get("atencao_perc",0),
            "perc_meta":     mf.get("perc_meta",0),

            "grave_rec":     mf.get("grave_rec",0),
            "alerta_rec":    mf.get("alerta_rec",0),
            "atencao_rec":   mf.get("atencao_rec",0),

            "grave_alvo":    mf.get("grave_alvo",0),
            "alerta_alvo":   mf.get("alerta_alvo",0),
            "atencao_alvo":  mf.get("atencao_alvo",0),
            "grave_pend":    mf.get("grave_pend",0),
            "alerta_pend":   mf.get("alerta_pend",0),
            "atencao_pend":  mf.get("atencao_pend",0),

            "trim_media_perc": tf,
            "rentabilidade_pct": margem_filial_pct(f),
        }

    # =========================================
    # 🔹 FILIAL SEM VENDEDOR (🔥 CORRETO AGORA)
    # =========================================
    elif f in filiais_sem_ativo:
        pt = round(filiais_sem_ativo[f]["pendente"], 2)
        pg = round(filiais_sem_ativo[f]["pago"], 2)

        filiais_js[f] = {
            "pendente": pt,
            "pago": pg,
            "total": round(pt + pg, 2),
            "sem_ativo": True,

            "inat_p": inat_p,
            "fdep_p": fdep_p,

            "perc_inat": 100.0,
            "perc_fdep": round(fdep_p/pt*100,1) if pt>0 else 0,

            "var_pago_perc": None,
            "var_pago_delta": 0,
            "var_periodo": "",

            # 🔥 AQUI ESTAVA O ERRO → NÃO PODE ZERAR
            "grave_perc":    mf.get("grave_perc",0),
            "alerta_perc":   mf.get("alerta_perc",0),
            "atencao_perc":  mf.get("atencao_perc",0),
            "perc_meta":     mf.get("perc_meta",0),

            "grave_rec":     mf.get("grave_rec",0),
            "alerta_rec":    mf.get("alerta_rec",0),
            "atencao_rec":   mf.get("atencao_rec",0),

            "grave_alvo":    mf.get("grave_alvo",0),
            "alerta_alvo":   mf.get("alerta_alvo",0),
            "atencao_alvo":  mf.get("atencao_alvo",0),
            "grave_pend":    mf.get("grave_pend",0),
            "alerta_pend":   mf.get("alerta_pend",0),
            "atencao_pend":  mf.get("atencao_pend",0),

            "trim_media_perc": tf,
            "rentabilidade_pct": margem_filial_pct(f),
        }

    # =========================================
    # 🔹 SEGURANÇA (caso raro)
    # =========================================
    else:
        filiais_js[f] = {
            "pendente": 0,
            "pago": 0,
            "total": 0,
            "sem_ativo": True,

            "inat_p": 0,
            "fdep_p": 0,

            "perc_inat": 0,
            "perc_fdep": 0,

            "var_pago_perc": None,
            "var_pago_delta": 0,
            "var_periodo": "",

            "grave_perc": 0,
            "alerta_perc": 0,
            "atencao_perc": 0,
            "perc_meta": 0,

            "grave_rec": 0,
            "alerta_rec": 0,
            "atencao_rec": 0,

            "grave_alvo": 0,
            "alerta_alvo": 0,
            "atencao_alvo": 0,
            "grave_pend": 0,
            "alerta_pend": 0,
            "atencao_pend": 0,

            "trim_media_perc": 0,
            "rentabilidade_pct": 0,
        }

filiais_js_ordered = {f: filiais_js[f] for f in ORDEM_FILIAIS if f in filiais_js}

# ── Histórico diário persistente (Master / Diretor Comercial) ───────────────
def _load_hist_dash():
    if os.path.exists(_hist_dash_path):
        try:
            with open(_hist_dash_path, encoding='utf-8') as _fh:
                _d = json.load(_fh)
            if isinstance(_d, dict):
                return _d
        except Exception:
            pass
    return {"dates": {}}

hist_dash = _load_hist_dash()
hist_dash.setdefault("dates", {})

_hist_empresa = {
    "pendente": round(sum(v.get("pendente", 0) for v in filiais_js_ordered.values()), 2),
    "recebido": round(sum(v.get("pago", 0) for v in filiais_js_ordered.values()), 2),
    "grave": round(sum(v.get("grave_pend", 0) for v in filiais_js_ordered.values()), 2),
    "alerta": round(sum(v.get("alerta_pend", 0) for v in filiais_js_ordered.values()), 2),
    "atencao": round(sum(v.get("atencao_pend", 0) for v in filiais_js_ordered.values()), 2),
    "config_global": CONFIG_META,
}

_hist_vends = {}
for _f_hist, _arr_hist in todos_js.items():
    for _v_hist in _arr_hist:
        _k_hist = f"{_v_hist.get('nome','')}_{_v_hist.get('filial','')}"
        _hist_vends[_k_hist] = {
            "nome": _v_hist.get("nome",""),
            "filial": _v_hist.get("filial",""),
            "pendente": round(float(_v_hist.get("pendente",0) or 0), 2),
            "recebido": round(float(_v_hist.get("pago",0) or 0), 2),
            "total": round(float(_v_hist.get("total",0) or 0), 2),
            "grave_pend": round(float(_v_hist.get("grave_pend",0) or 0), 2),
            "alerta_pend": round(float(_v_hist.get("alerta_pend",0) or 0), 2),
            "atencao_pend": round(float(_v_hist.get("atencao_pend",0) or 0), 2),
            "grave_rec": round(float(_v_hist.get("grave_rec",0) or 0), 2),
            "alerta_rec": round(float(_v_hist.get("alerta_rec",0) or 0), 2),
            "atencao_rec": round(float(_v_hist.get("atencao_rec",0) or 0), 2),
            "grave_alvo": round(float(_v_hist.get("grave_alvo",0) or 0), 2),
            "alerta_alvo": round(float(_v_hist.get("alerta_alvo",0) or 0), 2),
            "atencao_alvo": round(float(_v_hist.get("atencao_alvo",0) or 0), 2),
            "perc_meta": round(float(_v_hist.get("perc_meta",0) or 0), 1),
            "config_usada": get_config_meta(_k_hist),
        }

_hist_fils = {}
for _f_hist, _fd_hist in filiais_js_ordered.items():
    _hist_fils[_f_hist] = {
        "nome": f"Filial {_f_hist}",
        "filial": _f_hist,
        "pendente": round(float(_fd_hist.get("pendente",0) or 0), 2),
        "recebido": round(float(_fd_hist.get("pago",0) or 0), 2),
        "total": round(float(_fd_hist.get("total",0) or 0), 2),
        "grave_pend": round(float(_fd_hist.get("grave_pend",0) or 0), 2),
        "alerta_pend": round(float(_fd_hist.get("alerta_pend",0) or 0), 2),
        "atencao_pend": round(float(_fd_hist.get("atencao_pend",0) or 0), 2),
        "grave_rec": round(float(_fd_hist.get("grave_rec",0) or 0), 2),
        "alerta_rec": round(float(_fd_hist.get("alerta_rec",0) or 0), 2),
        "atencao_rec": round(float(_fd_hist.get("atencao_rec",0) or 0), 2),
        "grave_alvo": round(float(_fd_hist.get("grave_alvo",0) or 0), 2),
        "alerta_alvo": round(float(_fd_hist.get("alerta_alvo",0) or 0), 2),
        "atencao_alvo": round(float(_fd_hist.get("atencao_alvo",0) or 0), 2),
        "perc_meta": round(float(_fd_hist.get("perc_meta",0) or 0), 1),
        "config_usada": get_config_meta(f"FILIAL::{_f_hist}"),
    }


def _safe_pct_num(v):
    try:
        return round(float(v), 2)
    except Exception:
        return 0.0

def _norm_txt(v):
    s = str(v or "").strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s)

def _filial_key_from_text(txt):
    s = _norm_txt(txt)
    m = re.search(r"FILIAL\s+(\d{1,2})(?:/\d{1,2})?", s)
    if m:
        return f"F{int(m.group(1))}"
    return ""

def _ensure_sales_bucket(dct, key, nome="", filial=""):
    if key not in dct:
        dct[key] = {
            "nome": nome or key,
            "filial": filial or "",
            "venda_realizado_total": 0.0,
            "venda_atingido_total": 0.0,
            "venda_projetado": 0.0,
            "servico_realizado_total": 0.0,
            "servico_atingido_total": 0.0,
            "servico_projetado": 0.0,
            "caminhao_realizado_total": 0.0,
            "caminhao_atingido_total": 0.0,
            "caminhao_projetado": 0.0,
        }
    return dct[key]

# ── Carrega totais empresa direto do xlsx (fonte mais confiável) ─────────────
_xlsx_metas_path = os.path.join(pasta, "metas_vendas_mes_atual.xlsx")
_totais_direto = _extrair_totais_do_xlsx(_xlsx_metas_path) if os.path.exists(_xlsx_metas_path) else {}

_t_venda    = _totais_direto.get("venda_filial_meta", {})
_t_servico  = _totais_direto.get("servico_filial_ouro_fob", {})
_t_caminhao = _totais_direto.get("venda_filial_subgrupo_20k", {})

_sales_emp = {
    "venda_realizado_total":  _t_venda.get("real_total", 0.0),
    "venda_atingido_total":   _t_venda.get("ating_total", 0.0),
    "venda_projetado":        _t_venda.get("proj", 0.0),
    "venda_meta_total":       _t_venda.get("meta_total", 0.0),
    "venda_meta_periodo":     _t_venda.get("meta_per", 0.0),
    "servico_realizado_total":  _t_servico.get("real_total", 0.0),
    "servico_atingido_total":   _t_servico.get("ating_total", 0.0),
    "servico_projetado":        _t_servico.get("proj", 0.0),
    "servico_meta_total":       _t_servico.get("meta_total", 0.0),
    "servico_meta_periodo":     _t_servico.get("meta_per", 0.0),
    "caminhao_realizado_total": _t_caminhao.get("real_total", 0.0),
    "caminhao_atingido_total":  _t_caminhao.get("ating_total", 0.0),
    "caminhao_projetado":       _t_caminhao.get("proj", 0.0),
    "caminhao_meta_total":      _t_caminhao.get("meta_total", 0.0),
    "caminhao_meta_periodo":    _t_caminhao.get("meta_per", 0.0),
}
print(f"📊 _sales_emp carregado do xlsx:")
print(f"   Mercantil  : R$ {_sales_emp['venda_realizado_total']:>12,.2f}  proj R$ {_sales_emp['venda_projetado']:>12,.2f}  ating {_sales_emp['venda_atingido_total']:.2f}%")
print(f"   Serviços   : R$ {_sales_emp['servico_realizado_total']:>12,.2f}  proj R$ {_sales_emp['servico_projetado']:>12,.2f}  ating {_sales_emp['servico_atingido_total']:.2f}%")
print(f"   Caminhão   : R$ {_sales_emp['caminhao_realizado_total']:>12,.2f}  proj R$ {_sales_emp['caminhao_projetado']:>12,.2f}  ating {_sales_emp['caminhao_atingido_total']:.2f}%")
_sales_fil = {}
_sales_vend = {}

for _meta_key, _meta_obj in (metas_vendas_info.get("dados", {}).get("metas", {}) or {}).items():
    if not isinstance(_meta_obj, dict) or not _meta_obj.get("ok"):
        continue
    _rows = _meta_obj.get("linhas", []) or []
    # Separa linhas normais das linhas de total (tfoot)
    _rows_normal = [_r for _r in _rows if not _r.get("_is_total")]
    _rows_total  = [_r for _r in _rows if _r.get("_is_total")]
    # Usa a linha de total se disponível (é a mais precisa — vem direto do tfoot do SGI)
    _total_row   = _rows_total[-1] if _rows_total else None

    def _val_real(r):
        return float(r.get("Realizado (R$) Total_float") or r.get("Realizado(R$) Total_float") or 0)
    def _val_meta(r):
        return float(r.get("Meta (R$) Total_float") or r.get("Meta(R$) Total_float") or 0)
    def _val_meta_per(r):
        return float(r.get("Meta (R$) Período_float") or r.get("Meta(R$) Período_float") or 0)
    def _val_ating(r):
        return float(r.get("Atingido Total_float") or 0)
    def _val_proj(r):
        return float(r.get("Projetado (R$)_float") or r.get("Projetado(R$)_float") or 0)

    for _r in _rows_normal:
        _real  = _val_real(_r)
        _ating = _val_ating(_r)
        _proj  = _val_proj(_r)
        if _meta_key == "venda_filial_meta":
            _fil = _filial_key_from_text(_r.get("Filial", ""))
            if _fil:
                _b = _ensure_sales_bucket(_sales_fil, _fil, nome=f"Filial {_fil}", filial=_fil)
                _b["venda_realizado_total"] = _real
                _b["venda_atingido_total"]  = _ating
                _b["venda_projetado"]       = _proj
                _b["venda_meta_total"]      = _val_meta(_r)
                _b["venda_meta_periodo"]    = _val_meta_per(_r)
        elif _meta_key == "servico_filial_ouro_fob":
            _fil = _filial_key_from_text(_r.get("Filial", ""))
            if _fil:
                _b = _ensure_sales_bucket(_sales_fil, _fil, nome=f"Filial {_fil}", filial=_fil)
                _b["servico_realizado_total"] = _real
                _b["servico_atingido_total"]  = _ating
                _b["servico_projetado"]       = _proj
                _b["servico_meta_total"]      = _val_meta(_r)
                _b["servico_meta_periodo"]    = _val_meta_per(_r)
        elif _meta_key == "venda_filial_subgrupo_20k":
            _fil = _filial_key_from_text(_r.get("Filial", ""))
            if _fil:
                _b = _ensure_sales_bucket(_sales_fil, _fil, nome=f"Filial {_fil}", filial=_fil)
                _b["caminhao_realizado_total"] = _real
                _b["caminhao_atingido_total"]  = _ating
                _b["caminhao_projetado"]       = _proj
                _b["caminhao_meta_total"]      = _val_meta(_r)
                _b["caminhao_meta_periodo"]    = _val_meta_per(_r)
        elif _meta_key == "venda_filial_vendedor_meta":
            _nome = str(_r.get("Vendedor_2") or _r.get("Vendedor") or "").strip()
            _fil  = _filial_key_from_text(_r.get("Vendedor", "") or _r.get("Filial", ""))
            if _nome:
                _k = f"{_nome}_{_fil}" if _fil else _nome
                _b = _ensure_sales_bucket(_sales_vend, _k, nome=_nome, filial=_fil)
                _b["venda_realizado_total"] = _real
                _b["venda_atingido_total"]  = _ating
                _b["venda_projetado"]       = _proj
        elif _meta_key == "servico_filial_vendedor_ouro_fob":
            _nome = str(_r.get("Vendedor_2") or _r.get("Vendedor") or "").strip()
            _fil  = _filial_key_from_text(_r.get("Vendedor", "") or _r.get("Filial", ""))
            if _nome:
                _k = f"{_nome}_{_fil}" if _fil else _nome
                _b = _ensure_sales_bucket(_sales_vend, _k, nome=_nome, filial=_fil)
                _b["servico_realizado_total"] = _real
                _b["servico_atingido_total"]  = _ating
                _b["servico_projetado"]       = _proj

    # _sales_emp já foi carregado do xlsx diretamente (ver inicialização acima).
    # Este loop só precisa popular _sales_fil e _sales_vend (por filial/vendedor).
    pass
for _bucket in list(_sales_fil.values()) + list(_sales_vend.values()):
    for _k in list(_bucket.keys()):
        if isinstance(_bucket[_k], float):
            _bucket[_k] = round(_bucket[_k], 2)

# agora que _sales_emp foi montado, serializa corretamente para o HTML
js_sales_empresa = json.dumps(_sales_emp, ensure_ascii=False)
js_rent_empresa = json.dumps((margens_brutas_info.get('dados', {}) or {}).get('empresa', {}), ensure_ascii=False)

# relatório de serviços do mês atual (gerado pelo worker de vendas)
_servicos_rel_path = os.path.join(pasta, "relatorio_servicos_mes_atual.json")
_servicos_rel_data = {}
try:
    if os.path.exists(_servicos_rel_path):
        with open(_servicos_rel_path, "r", encoding="utf-8") as _fsrv:
            _servicos_rel_data = json.load(_fsrv) or {}
except Exception as _e:
    print(f"⚠️ Falha ao carregar relatorio_servicos_mes_atual.json: {_e}")
js_servicos_relatorio = json.dumps(_servicos_rel_data, ensure_ascii=False)

hist_dash.setdefault("sales_dates", {})
hist_dash.setdefault("sales_months", {})

# =========================================
# 🎯 HISTÓRICO REAL DA META DIÁRIA
# Regra corrigida:
#   - Meta diária = Meta Total / dias úteis configurados
#   - Ponto diário só é gerado se a VENDA DO DIA bater a meta diária.
#   - Não soma pelo acumulado dividido; salva dia a dia para valer no próximo mês.
# =========================================

def _last_sales_date_before(_today):
    try:
        _dates = sorted([d for d in (hist_dash.get("sales_dates", {}) or {}).keys() if str(d) < str(_today)])
        return _dates[-1] if _dates else None
    except Exception:
        return None


def _sales_lookup_prev(_prev_date, scope, key):
    if not _prev_date:
        return 0.0
    try:
        return float((hist_dash.get("sales_dates", {}).get(_prev_date, {}).get(scope, {}).get(key, {}) or {}).get("venda_realizado_total", 0) or 0)
    except Exception:
        return 0.0


def _dias_uteis_campanha_padrao(ent_type, ent_key):
    try:
        _cfg = get_config_meta(ent_key)
        if ent_type == "filial":
            _rows = (_cfg.get("camp_meta_diaria_ger") or [])
        else:
            _rows = (_cfg.get("camp_meta_diaria_vend") or [])
        if _rows:
            return max(1, int(float(str(_rows[0].get("dias_uteis", 26)).replace(",", "."))))
    except Exception:
        pass
    return 26


def _meta_total_from_rows(meta_key, lookup_filial=None, lookup_nome=None):
    try:
        _rows = metas_vendas_info.get("dados", {}).get("metas", {}).get(meta_key, {}).get("linhas", []) or []
        for _r in _rows:
            if lookup_filial:
                if _filial_key_from_text(_r.get("Filial", "") or _r.get("Vendedor", "")) != lookup_filial:
                    continue
            if lookup_nome:
                _nome_row = str(_r.get("Vendedor_2") or _r.get("Vendedor") or "").strip()
                if _norm_key_margem(_nome_row) != _norm_key_margem(lookup_nome):
                    continue
            return float(_r.get("Meta (R$) Total_float") or _r.get("Meta(R$) Total_float") or 0)
    except Exception:
        pass
    return 0.0


def _atualizar_meta_diaria_historico():
    _prev_date = _last_sales_date_before(hoje_str)
    _hist_md = hist_dash.setdefault("daily_meta", {})
    _hist_md.setdefault("dates", {})
    _hist_md.setdefault("months", {})
    _today_entry = {"filiais": {}, "vendedores": {}, "prev_date": _prev_date, "updated_at": datetime.now().isoformat()}
    _month_entry = _hist_md["months"].setdefault(mes_str, {"filiais": {}, "vendedores": {}})

    # Filiais
    for _f, _b in (_sales_fil or {}).items():
        _meta_total = _meta_total_from_rows("venda_filial_meta", lookup_filial=_f)
        _dias = _dias_uteis_campanha_padrao("filial", f"FILIAL::{_f}")
        _meta_dia = (_meta_total / _dias) if _meta_total > 0 else 0.0
        _real_hoje_acum = float(_b.get("venda_realizado_total", 0) or 0)
        _real_ant = _sales_lookup_prev(_prev_date, "filiais", _f)
        _real_dia = max(0.0, _real_hoje_acum - _real_ant)
        _bateu = bool(_meta_dia > 0 and _real_dia >= _meta_dia)
        _today_entry["filiais"][_f] = {
            "filial": _f,
            "meta_total": round(_meta_total, 2),
            "dias_uteis": _dias,
            "meta_diaria": round(_meta_dia, 2),
            "realizado_dia": round(_real_dia, 2),
            "realizado_total": round(_real_hoje_acum, 2),
            "ponto": 1 if _bateu else 0,
        }
        _me = _month_entry["filiais"].setdefault(_f, {"pontos": 0, "dias": {}})
        # Recalcula o ponto deste dia sem duplicar se o script rodar mais de uma vez.
        _old = int((_me.get("dias", {}).get(hoje_str, {}) or {}).get("ponto", 0) or 0)
        _new = 1 if _bateu else 0
        _me["pontos"] = max(0, int(_me.get("pontos", 0) or 0) - _old + _new)
        _me.setdefault("dias", {})[hoje_str] = _today_entry["filiais"][_f]

    # Vendedores
    for _k, _b in (_sales_vend or {}).items():
        _nome = _b.get("nome", "")
        _fil = _b.get("filial", "")
        _meta_total = _meta_total_from_rows("venda_filial_vendedor_meta", lookup_filial=_fil, lookup_nome=_nome)
        _dias = _dias_uteis_campanha_padrao("vendedor", f"VEND::{_limpar_nome_margem(_nome)}_{_fil}")
        _meta_dia = (_meta_total / _dias) if _meta_total > 0 else 0.0
        _real_hoje_acum = float(_b.get("venda_realizado_total", 0) or 0)
        _real_ant = _sales_lookup_prev(_prev_date, "vendedores", _k)
        _real_dia = max(0.0, _real_hoje_acum - _real_ant)
        _bateu = bool(_meta_dia > 0 and _real_dia >= _meta_dia)
        _today_entry["vendedores"][_k] = {
            "nome": _nome,
            "filial": _fil,
            "key": _k,
            "meta_total": round(_meta_total, 2),
            "dias_uteis": _dias,
            "meta_diaria": round(_meta_dia, 2),
            "realizado_dia": round(_real_dia, 2),
            "realizado_total": round(_real_hoje_acum, 2),
            "ponto": 1 if _bateu else 0,
        }
        _me = _month_entry["vendedores"].setdefault(_k, {"pontos": 0, "dias": {}})
        _old = int((_me.get("dias", {}).get(hoje_str, {}) or {}).get("ponto", 0) or 0)
        _new = 1 if _bateu else 0
        _me["pontos"] = max(0, int(_me.get("pontos", 0) or 0) - _old + _new)
        _me.setdefault("dias", {})[hoje_str] = _today_entry["vendedores"][_k]

    _hist_md["dates"][hoje_str] = _today_entry
    print(f"🎯 Meta diária histórica atualizada: {hoje_str} (base anterior: {_prev_date or 'sem histórico'})")

_atualizar_meta_diaria_historico()

hist_dash["sales_dates"][hoje_str] = {
    "empresa": _sales_emp,
    "filiais": _sales_fil,
    "vendedores": _sales_vend,
    "updated_at": datetime.now().isoformat(),
}
hist_dash["sales_months"][mes_str] = {
    "empresa": _sales_emp,
    "filiais": _sales_fil,
    "vendedores": _sales_vend,
    "updated_at": datetime.now().isoformat(),
}

hist_dash["dates"][hoje_str] = {
    "empresa": _hist_empresa,
    "vendedores": _hist_vends,
    "filiais": _hist_fils,
    "updated_at": datetime.now().isoformat(),
}
_fech_mensal = fechar_mes_anterior_travado(mes_str, hist_dash, CONFIG_META, CONFIG_META_IND)
hist_dash['months_closed'] = _fech_mensal.get('months', {})
with open(_hist_dash_path, "w", encoding="utf-8") as _f_hist_out:
    json.dump(hist_dash, _f_hist_out, ensure_ascii=False, indent=2)
print(f"🗂️ Histórico diário salvo: {_hist_dash_path}")

# Serializa relatório de clientes a cobrar
# Regras:
#   - Ativos: vão direto para o índice do próprio vendedor
#   - Inativos e FDEP: 60% para o gerente/filial, 40% dividido entre vendedores ativos
#   - Cada CLIENTE vai para apenas 1 destinatário (sem duplicatas)
#   - Determinismo: mesmo cliente sempre vai para mesmo destinatário (hash do nome)
import random as _random_mod

clientes_js = {}       # {filial: {faixa: [...]}} — para visualização da filial/gerente
clientes_por_vend_js = {}  # {nome_vend: {faixa: [...]}} — para painel individual
clientes_terceiro_js = {"grave": [], "alerta": [], "atencao": []}

for _ct in _clientes_terceiro_lista:
    clientes_terceiro_js[_ct["faixa"]].append({
        "nome": _ct.get("cliente", _ct.get("nome", "")),
        "cliente": _ct.get("cliente", ""),
        "restricao": _ct.get("restricao", ""),
        "vencimento": _ct.get("vencimento", ""),
        "pagamento": _ct.get("pagamento", ""),
        "dias": _ct.get("dias", 0),
        "pendente": _ct.get("pendente", 0),
        "pago": _ct.get("pago", 0.0),
        "parcela": _ct.get("parcela", ""),
        "titulo": _ct.get("titulo", ""),
        "avalista": _ct.get("avalista", ""),
        "contato": _ct.get("contato", ""),
        "telefones": _ct.get("telefones", []),
        "mensagem_whatsapp": _ct.get("mensagem_whatsapp", ""),
        "vendedor": COBRANCA10_NOME,
        "novo": _ct.get("novo", False),
    })

for f in ORDEM_FILIAIS:
    clientes_js[f] = {"grave": [], "alerta": [], "atencao": []}

# Separa: ativos vs inativos/FDEP por filial
_cli_ativos    = [c for c in clientes_cobrar if c.get('is_ativo')]
_cli_inat_fdep = [c for c in clientes_cobrar if not c.get('is_ativo')]

# ── Clientes ATIVOS: vão para o próprio vendedor ──────────────────────
for c in _cli_ativos:
    _nd = limpar_nome_display(c['vendedor'])

    if _nd not in clientes_por_vend_js:
        clientes_por_vend_js[_nd] = {"grave": [], "alerta": [], "atencao": []}

    clientes_por_vend_js[_nd][c['faixa']].append({
        "nome": c["cliente"],
        "cliente": c["cliente"],
        "restricao": c["restricao"],
        "vencimento": c["vencimento"],
        "pagamento": c.get("pagamento", ""),
        "dias": c["dias"],
        "pendente": c["pendente"],
        "pago": c.get("pago", 0.0),
        "parcela": c["parcela"],
        "titulo": c.get("titulo", ""),
        "avalista": c.get("avalista", ""),
        "contato": c.get("contato", ""),
        "telefones": c.get("telefones", []),
        "mensagem_whatsapp": c.get("mensagem_whatsapp", ""),
        "vendedor": _nd[:25],
        "novo": c.get("novo", False),
    })

    _ff = c["filial"]
    if _ff in clientes_js:
        clientes_js[_ff][c['faixa']].append({
            "nome": c["cliente"],
            "cliente": c["cliente"],
            "restricao": c["restricao"],
            "vencimento": c["vencimento"],
            "pagamento": c.get("pagamento", ""),
            "dias": c["dias"],
            "pendente": c["pendente"],
            "pago": c.get("pago", 0.0),
            "parcela": c["parcela"],
            "titulo": c.get("titulo", ""),
            "avalista": c.get("avalista", ""),
            "contato": c.get("contato", ""),
            "telefones": c.get("telefones", []),
            "mensagem_whatsapp": c.get("mensagem_whatsapp", ""),
            "vendedor": _nd[:25],
            "novo": c.get("novo", False),
        })

# ── Inativos e FDEP: distribui 60% gerente/40% vendedores por filial ──
# Agrupa por filial de destino
_inat_por_filial = {}   # {filial: [clientes]}
for c in _cli_inat_fdep:
    # Determina filial de destino
    if c.get('is_fdep'):
        # FDEP: distribui por peso proporcional (mesmo rateio do pendente)
        _dest_filial = None
        if tw > 0:
            _hash_n = int(_hashlib.md5(c['cliente'][:30].encode()).hexdigest(), 16)
            _filiais_ord2 = sorted(pesos.items(), key=lambda x: x[1], reverse=True)
            _acum2 = 0
            _lim2  = (_hash_n % 10000) / 10000.0
            for _ff2, _ww2 in _filiais_ord2:
                _acum2 += _ww2 / tw
                if _lim2 <= _acum2:
                    _dest_filial = _ff2; break
            if _dest_filial is None and _filiais_ord2:
                _dest_filial = _filiais_ord2[0][0]
    else:
        # Inativo: vai para a filial onde estava (filial no nome do cliente cobrar)
        _dest_filial = c['filial'] if c['filial'] in ORDEM_FILIAIS else None

    if _dest_filial:
        if _dest_filial not in _inat_por_filial:
            _inat_por_filial[_dest_filial] = []
        _inat_por_filial[_dest_filial].append(c)

# Para cada filial, distribui 60% gerente / 40% vendedores (sem duplicatas)
for _filial_dest, _clientes_inat in _inat_por_filial.items():
    # Evita duplicatas: cada CLIENTE vai para apenas 1 destinatário
    _clientes_unicos = {}  # {nome_cliente: c} — pega o de maior pendente
    for c in _clientes_inat:
        k = c['cliente'][:30]
        if k not in _clientes_unicos or c['pendente'] > _clientes_unicos[k]['pendente']:
            _clientes_unicos[k] = c
    _lista = list(_clientes_unicos.values())

    # Ordena por pendente desc (mais importante primeiro)
    _lista.sort(key=lambda x: x['pendente'], reverse=True)
    _total = len(_lista)
    _n_ger = round(_total * 0.60)   # 60% para gerente
    _n_vend = _total - _n_ger       # 40% para vendedores

    # Gerente recebe os primeiros 60%
    _para_gerente = _lista[:_n_ger]
    _para_vends   = _lista[_n_ger:]

    # Adiciona ao painel da filial (gerente vê tudo da filial)
    for c in _lista:
        _tag = " [FDEP]" if c.get("is_fdep") else " [Inativo]"

        clientes_js[_filial_dest][c["faixa"]].append({
            "nome": c.get("cliente", c.get("nome", "")),
            "cliente": c.get("cliente", ""),
            "restricao": c.get("restricao", ""),
            "vencimento": c.get("vencimento", ""),
            "pagamento": c.get("pagamento", ""),
            "dias": c.get("dias", 0),
            "pendente": c.get("pendente", 0),
            "pago": c.get("pago", 0.0),
            "parcela": c.get("parcela", ""),
            "titulo": c.get("titulo", ""),
            "avalista": c.get("avalista", ""),
            "contato": c.get("contato", ""),
            "telefones": c.get("telefones", []),
            "mensagem_whatsapp": c.get("mensagem_whatsapp", ""),
            "vendedor": limpar_nome_display(c["vendedor"])[:20] + _tag,
            "novo": c.get("novo", False),
        })

    # Distribui os 40% entre vendedores ativos da filial
    _vends_ativos = [
        r["nome_exibicao"]
        for _, r in df_vend[
            (df_vend["filial_vendedor"] == _filial_dest) & (~df_vend["is_gerente"])
        ].iterrows()
    ]

    if _vends_ativos and _para_vends:
        _n_vends_ativos = len(_vends_ativos)

        for _idx_c, c in enumerate(_para_vends):
            # Distribui round-robin pelos vendedores ativos
            _vend_dest = _vends_ativos[_idx_c % _n_vends_ativos]
            _tag = " [FDEP]" if c.get("is_fdep") else " [Inativo]"

            if _vend_dest not in clientes_por_vend_js:
                clientes_por_vend_js[_vend_dest] = {
                    "grave": [],
                    "alerta": [],
                    "atencao": []
                }

            clientes_por_vend_js[_vend_dest][c["faixa"]].append({
                "nome": c.get("cliente", c.get("nome", "")),
                "cliente": c.get("cliente", ""),
                "restricao": c.get("restricao", ""),
                "vencimento": c.get("vencimento", ""),
                "pagamento": c.get("pagamento", ""),
                "dias": c.get("dias", 0),
                "pendente": c.get("pendente", 0),
                "pago": c.get("pago", 0.0),
                "parcela": c.get("parcela", ""),
                "titulo": c.get("titulo", ""),
                "avalista": c.get("avalista", ""),
                "contato": c.get("contato", ""),
                "telefones": c.get("telefones", []),
                "mensagem_whatsapp": c.get("mensagem_whatsapp", ""),
                "vendedor": limpar_nome_display(c["vendedor"])[:20] + _tag,
                "novo": c.get("novo", False),
            })

print(f"📋 Clientes por filial (gerente):")
for f in ORDEM_FILIAIS:
    t = sum(len(clientes_js[f][x]) for x in ["grave", "alerta", "atencao"])
    if t:
        print(f"  {f}: {t} títulos")

print(f"📋 Clientes por vendedor: {len(clientes_por_vend_js)} vendedores com títulos")
# Ordena por valor pendente descendente
for f in clientes_js:
    for faixa in ["grave","alerta","atencao"]:
        clientes_js[f][faixa].sort(key=lambda x: x["pendente"], reverse=True)

# ── CREDIARISTAS: espelho integral da base da filial ─────────────────────────
# Regra nova:
#   - o crediarista acessa a MESMA carteira da filial/gerente
#   - não existe mais rateio 50% / 50%
#   - gerente e crediarista podem cobrar simultaneamente sobre a mesma base
#   - ao registrar cobrança, ambos enxergam a atualização porque a base é espelhada
clientes_crediarista_js = {}
recebimentos_crediarista_js = {}
for _fil_cred, _login_cred in CREDIARISTAS_FILIAIS.items():
    _src_cli = clientes_js.get(_fil_cred, {}) or {}
    clientes_crediarista_js[_login_cred] = {
        'grave': list(_src_cli.get('grave', []) or []),
        'alerta': list(_src_cli.get('alerta', []) or []),
        'atencao': list(_src_cli.get('atencao', []) or []),
    }

    _agg = {'grave': [], 'alerta': [], 'atencao': []}
    for _rk, _rv in recebimentos_det_js.items():
        if str(_rk).endswith('_' + _fil_cred):
            for _fx in ['grave', 'alerta', 'atencao']:
                _agg[_fx].extend(list((_rv or {}).get(_fx, []) or []))

    for _fx in ['grave', 'alerta', 'atencao']:
        _agg[_fx] = sorted(_agg[_fx], key=lambda x: float(x.get('pago', 0) or 0), reverse=True)

    recebimentos_crediarista_js[_login_cred] = _agg

_historico_comissao_cobranca10()

js_todos    = json.dumps(todos_js,            ensure_ascii=False)
js_filiais  = json.dumps(filiais_js_ordered,  ensure_ascii=False)
# clientes_por_vend_js já construído na serialização acima

# ── Recebimentos detalhados por faixa por vendedor (para relatório 💰) ──
# Mostra títulos pagos após data_corte_parse, por faixa de vencimento
# Só vendedores ativos; inativos/FDEP aparecem com tag no nome
js_recebimentos = json.dumps(recebimentos_det_js, ensure_ascii=False)
js_recebimentos_terceiro = json.dumps(recebimentos_terceiro_js, ensure_ascii=False)
js_clientes      = json.dumps(clientes_js,           ensure_ascii=False)
js_clientes_vend = json.dumps(clientes_por_vend_js,  ensure_ascii=False)
js_clientes_terceiro = json.dumps(clientes_terceiro_js, ensure_ascii=False)
js_clientes_crediarista = json.dumps(clientes_crediarista_js, ensure_ascii=False)
js_recebimentos_crediarista = json.dumps(recebimentos_crediarista_js, ensure_ascii=False)
js_crediaristas_map = json.dumps(CREDIARISTAS_FILIAIS, ensure_ascii=False)
js_destaque = json.dumps(destaque_semana or {}, ensure_ascii=False)
js_hist_dash = json.dumps(hist_dash, ensure_ascii=False)

total_dash_p  = round(total_final_p,  2)
total_dash_pg = round(total_final_pg, 2)



# =========================================
# 🔥 HTML COMPLETO v2 — 4 GRÁFICOS META
# =========================================
import re as _re, base64 as _b64

_laranjito = "https://moveisdolar.com.br/colaborador/Captura%20de%20tela%202026-04-13%20142009.jpg"
_logo      = "https://moveisdolar.com.br/colaborador/Captura%20de%20tela%202026-04-13%20142059.jpg"


template = r"""
<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dashboard - Lojas MDL</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;0,9..40,800;1,9..40,400&family=DM+Mono:wght@400;500&display=swap');
:root{
  --bg-base:#0d0f14;--bg-surface:#13161e;--bg-elevated:#1a1e2a;--bg-hover:#222636;
  --glass:rgba(255,255,255,.04);--glass-border:rgba(255,255,255,.09);--glass-hover:rgba(255,255,255,.07);
  --amber-200:#fcc772;--amber-300:#f9a832;--amber-400:#f58c10;--amber-500:#e06f05;
  --red-400:#f05252;--red-600:#c72a2a;--green-400:#31c48d;--blue-400:#60a5fa;
  --orange-400:#fb923c;--yellow-400:#fbbf24;
  --text-primary:#f0f2f8;--text-secondary:#8b93a9;--text-muted:#4e5669;--text-accent:#f9a832;
  --radius-sm:8px;--radius-md:14px;--radius-lg:20px;--radius-xl:28px;
  --shadow-md:0 8px 28px rgba(0,0,0,.45);--shadow-lg:0 20px 60px rgba(0,0,0,.55);
  --shadow-amber:0 8px 32px rgba(245,140,16,.20);
  --transition:.18s cubic-bezier(.4,0,.2,1);--transition-slow:.32s cubic-bezier(.4,0,.2,1);
  /* legacy aliases */
  --bg:#0d0f14;--bg2:#0d0f14;--card:rgba(255,255,255,.04);--stroke:rgba(255,255,255,.09);
  --text:#f0f2f8;--muted:#8b93a9;--blue:#60a5fa;--blue2:#93c5fd;
  --green:#31c48d;--green2:#6ee7b7;--red:#f05252;--red2:#fca5a5;
  --orange:#fb923c;--orange2:#fdba74;--yellow:#fbbf24;--yellow2:#fde68a;
  --shadow:0 8px 28px rgba(0,0,0,.45);--radius:20px;
  font-family:'DM Sans',system-ui,sans-serif;font-size:14px;line-height:1.5;
  color:var(--text-primary);background:var(--bg-base);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{min-height:100vh;background:radial-gradient(ellipse 80% 50% at 10% -10%,rgba(245,140,16,.08) 0%,transparent 60%),radial-gradient(ellipse 60% 40% at 90% 110%,rgba(96,165,250,.06) 0%,transparent 60%),var(--bg-base)}
::-webkit-scrollbar{width:6px;height:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:99px}
.app-shell{max-width:1560px;margin:0 auto;padding:20px 24px 100px}
.glass{background:var(--glass);backdrop-filter:blur(20px) saturate(1.4);-webkit-backdrop-filter:blur(20px) saturate(1.4);border:1px solid var(--glass-border);box-shadow:var(--shadow-md)}
.glass:hover{border-color:rgba(255,255,255,.14)}
.header{display:flex;align-items:center;justify-content:space-between;padding:18px 24px;border-radius:var(--radius-xl);margin-bottom:24px;gap:16px;flex-wrap:wrap;background:linear-gradient(135deg,rgba(245,140,16,.12) 0%,rgba(249,168,50,.06) 40%,transparent 70%),var(--glass);border:1px solid rgba(245,140,16,.2);box-shadow:var(--shadow-amber),var(--shadow-md);position:relative;overflow:hidden}
.header::before{content:'';position:absolute;left:-60px;top:-60px;width:220px;height:220px;border-radius:50%;background:radial-gradient(circle,rgba(245,140,16,.14) 0%,transparent 70%);pointer-events:none}
.brand{display:flex;align-items:center;gap:16px;position:relative;z-index:1}
.brand img{width:52px;height:52px;border-radius:var(--radius-md);object-fit:contain;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);box-shadow:0 0 0 3px rgba(245,140,16,.18)}
.brand h1{font-size:26px;font-weight:800;letter-spacing:-.03em;background:linear-gradient(135deg,var(--amber-200) 0%,var(--amber-400) 50%,var(--amber-300) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sub{font-size:12px;color:#dbe4ff;margin-top:3px}
.header-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;position:relative;z-index:1}
.btn{display:inline-flex;align-items:center;gap:7px;padding:10px 16px;border-radius:var(--radius-md);border:1px solid transparent;font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:var(--transition);text-decoration:none;white-space:nowrap;line-height:1;appearance:none}
.btn:hover{transform:translateY(-1px)}.btn:active{transform:translateY(0) scale(.98)}
.btn.primary{background:linear-gradient(135deg,var(--amber-400) 0%,var(--amber-500) 100%);color:#1a0d00;box-shadow:0 4px 16px rgba(245,140,16,.3);border-color:rgba(255,255,255,.15)}
.btn.primary:hover{box-shadow:0 6px 24px rgba(245,140,16,.45)}
.btn.soft{background:rgba(255,255,255,.06);color:var(--text-primary);border-color:var(--glass-border)}
.btn.soft:hover{background:rgba(255,255,255,.09)}
.btn.ghost{background:transparent;color:var(--text-secondary);border-color:transparent}
.btn.ghost:hover{color:var(--text-primary);background:var(--glass)}
.btn.danger{background:rgba(240,82,82,.12);color:var(--red-400);border-color:rgba(240,82,82,.2)}
.btn.danger:hover{background:rgba(240,82,82,.2)}
.btn.wa{background:linear-gradient(135deg,#25D366,#1a9e4a);color:#fff;font-weight:700;box-shadow:0 4px 14px rgba(37,211,102,.25)}
.badge{display:inline-flex;align-items:center;gap:6px;padding:8px 14px;border-radius:99px;font-size:12px;font-weight:700;letter-spacing:.02em;background:rgba(249,168,50,.1);color:var(--amber-300);border:1px solid rgba(249,168,50,.2)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;padding:6px;background:var(--bg-surface);border-radius:var(--radius-lg);border:1px solid var(--glass-border);margin-bottom:20px}
.tab{padding:10px 16px;border-radius:var(--radius-md);border:none;background:transparent;color:var(--text-secondary);font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;transition:var(--transition)}
.tab:hover{color:var(--text-primary);background:var(--glass)}
.tab.active{background:linear-gradient(135deg,var(--amber-400),var(--amber-500));color:#1a0d00;box-shadow:0 4px 16px rgba(245,140,16,.35)}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:20px}
.pill{padding:7px 14px;border-radius:99px;border:1px solid var(--glass-border);background:transparent;color:var(--text-secondary);font-family:inherit;font-size:12px;font-weight:600;cursor:pointer;transition:var(--transition)}
.pill:hover{color:var(--text-primary);border-color:rgba(255,255,255,.2)}
.pill.active{background:rgba(249,168,50,.12);color:var(--amber-300);border-color:rgba(249,168,50,.3)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
.kpi{padding:20px;border-radius:var(--radius-lg);position:relative;overflow:hidden;transition:var(--transition)}
.kpi:hover{transform:translateY(-2px)}
.kpi::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:var(--accent,var(--amber-400));border-radius:99px 99px 0 0}
.kpi .label{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:#dbe4ff;margin-bottom:6px}
.kpi .value{font-size:24px;font-weight:800;letter-spacing:-.03em;color:#ffffff;line-height:1}
.kpi .subline{font-size:12px;color:var(--text-secondary);margin-top:8px}
.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:16px;flex-wrap:wrap}
.section-head h2{font-size:20px;font-weight:800;letter-spacing:-.025em;color:var(--text-primary)}
.section-head .hint{font-size:12px;color:var(--text-secondary);margin-top:4px}
.grid-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.card{padding:20px;border-radius:var(--radius-lg);cursor:pointer;position:relative;overflow:hidden;transition:var(--transition-slow);border:1px solid var(--glass-border);background:var(--glass)}
.card:hover{transform:translateY(-4px) scale(1.01);border-color:rgba(255,255,255,.18);box-shadow:0 20px 60px rgba(0,0,0,.5),0 0 0 1px rgba(249,168,50,.12)}
.card::before{content:'';position:absolute;inset:0;background:linear-gradient(105deg,transparent 40%,rgba(255,255,255,.04) 50%,transparent 60%);background-size:200% 100%;background-position:200% 0;transition:background-position .6s ease;pointer-events:none}
.card:hover::before{background-position:-200% 0}
.card::after{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--card-accent,transparent),rgba(255,255,255,0));border-radius:2px 2px 0 0}
.card .title{font-size:14px;font-weight:700;color:var(--text-primary);line-height:1.3;min-height:auto;margin-bottom:14px}
.card-hit{--card-accent:var(--amber-400);box-shadow:0 0 0 1px rgba(249,168,50,.15),var(--shadow-md);animation:highlightPulse 2.2s ease-in-out infinite}
.card-low-red{--card-accent:var(--red-400);box-shadow:0 0 0 1px rgba(240,82,82,.12),var(--shadow-md)}
.card-low-orange{--card-accent:var(--orange-400);box-shadow:0 0 0 1px rgba(251,146,60,.12),var(--shadow-md)}
.card .numbers{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}
.stat-box{padding:10px 12px;border-radius:var(--radius-sm);background:rgba(0,0,0,.2);border:1px solid rgba(255,255,255,.05)}
.stat-box .mini{font-size:10px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em}
.stat-box .big{font-size:14px;font-weight:800;margin-top:4px;line-height:1;letter-spacing:-.02em;white-space:nowrap;overflow:visible}
.meta-row{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
.mini-chip{font-size:11px;font-weight:700;padding:5px 9px;border-radius:var(--radius-sm);background:rgba(255,255,255,.05);border:1px solid var(--glass-border);color:#eaf1ff;display:flex;align-items:center;gap:5px}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;display:inline-block}
.legend-inline{display:flex;gap:12px;flex-wrap:wrap;font-size:12px;color:var(--text-secondary);margin:10px 0 0}
.legend-inline span{display:inline-flex;align-items:center;gap:6px;font-weight:700}
.mascot-status{display:flex;align-items:center;gap:8px;margin-top:10px;padding:9px 11px;border-radius:var(--radius-md);background:rgba(255,255,255,.03);border:1px solid var(--glass-border)}
.mascot-status img{width:32px;height:32px;border-radius:var(--radius-sm);object-fit:cover;animation:mascotPulse 2s ease-in-out infinite}
.mascot-status strong{font-size:12px;color:var(--text-primary);font-weight:700}
.card-sales{margin-top:10px;background:rgba(249,168,50,.04);border:1px solid rgba(249,168,50,.12);border-radius:var(--radius-md);padding:10px}
.card-sales-title{font-size:10px;color:var(--amber-400);font-weight:700;text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px;display:flex;align-items:center;gap:6px}
.card-sales-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
.sales-mini{padding:7px;border-radius:var(--radius-sm);background:rgba(0,0,0,.25);border:1px solid rgba(255,255,255,.05);text-align:center}
.sales-mini .k{font-size:9px;color:var(--text-muted);font-weight:700;text-transform:uppercase;letter-spacing:.06em;line-height:1.1}
.sales-mini .v{font-size:11px;font-weight:800;color:var(--text-primary);margin-top:4px;line-height:1.1;white-space:nowrap;overflow:visible}
.sales-mini.good{border-color:rgba(49,196,141,.2)}.sales-mini.good .v{color:var(--green-400)}
.sales-mini.warn{border-color:rgba(251,146,60,.2)}.sales-mini.warn .v{color:var(--orange-400)}
.sales-mini.gold{background:linear-gradient(135deg,rgba(249,168,50,.1),rgba(249,168,50,.03));border-color:rgba(249,168,50,.25)}.sales-mini.gold .v{color:var(--amber-300)}
.sales-mini.low{border-color:rgba(240,82,82,.2)}.sales-mini.low .v{color:var(--red-400)}
.sales-mini.realizado{border-color:rgba(49,196,141,.2);animation:realPulse 1.9s ease-in-out infinite}
.sales-mini.meta{border-color:rgba(96,165,250,.15)}
.sales-mini .laranjito-mini{display:block;width:22px;height:22px;border-radius:6px;object-fit:cover;margin:0 auto 3px}
.sales-mini.wrap .v{white-space:normal;overflow-wrap:anywhere;word-break:break-word;line-height:1.05}
.sales-progress{margin-top:6px;height:6px;border-radius:99px;background:rgba(255,255,255,.06);overflow:hidden}
.sales-progress>span{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,var(--amber-500),var(--amber-300))}
.sales-progress-label{margin-top:4px;font-size:9px;color:var(--text-muted);font-weight:700;text-align:right}
.big-chart-card{padding:22px;border-radius:var(--radius-xl);margin-top:24px}
.groupbars{display:flex;align-items:flex-end;gap:12px;overflow:auto;padding:14px 6px 6px}
.group{min-width:100px}
.group .glabel{text-align:center;font-size:11px;color:var(--text-secondary);font-weight:700;margin-top:8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.group .bars{height:280px;display:flex;align-items:flex-end;justify-content:center;gap:6px;padding:0 4px;border-left:1px solid rgba(255,255,255,.06)}
.bar{width:20px;border-radius:14px 14px 8px 8px;position:relative;overflow:hidden;box-shadow:inset 0 2px 0 rgba(255,255,255,.35),0 8px 16px rgba(0,0,0,.35)}
.bar::before{content:'';position:absolute;inset:0;background:linear-gradient(180deg,rgba(255,255,255,.45),rgba(255,255,255,.1) 30%,rgba(255,255,255,0) 60%);pointer-events:none}
.axis{display:flex;justify-content:space-between;margin:10px 10px 0;color:var(--text-muted);font-size:11px;font-weight:600}
.detail-screen{margin-top:8px}
.detail-top{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}
.back-row{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:20px;flex-wrap:wrap}
.back-row h2{font-size:24px;font-weight:800;letter-spacing:-.03em}
.note{font-size:12px;color:var(--text-muted)}
.panel{padding:22px;border-radius:var(--radius-xl)}
.panel h3{font-size:16px;font-weight:800;letter-spacing:-.02em;margin-bottom:16px}
.panel h3 .note{font-size:11px;font-weight:500;color:var(--text-muted)}
.mega-progress{display:grid;grid-template-columns:220px 1fr;gap:16px;align-items:center}
.ring-wrap{text-align:center}
.piggy-bank{position:relative;width:190px;min-height:258px;margin:0 auto;display:flex;flex-direction:column;align-items:center;justify-content:flex-start}
.piggy-glow{position:absolute;top:12px;left:50%;transform:translateX(-50%);width:178px;height:178px;border-radius:50%;background:radial-gradient(circle at 50% 35%,rgba(249,168,50,.15),rgba(249,168,50,0) 68%)}
.piggy-shell{position:relative;width:178px;height:178px;border-radius:50%;overflow:hidden;background:conic-gradient(from -90deg,var(--amber-400) calc(var(--pct)*1%),rgba(30,35,50,.9) 0);box-shadow:inset 0 0 0 10px rgba(255,255,255,.08),0 20px 40px rgba(0,0,0,.5)}
.piggy-shell::before{content:'';position:absolute;inset:14px;border-radius:50%;background:linear-gradient(180deg,rgba(255,255,255,.08),rgba(255,255,255,.02));box-shadow:inset 0 2px 0 rgba(255,255,255,.12);z-index:1}
.piggy-slot{position:absolute;left:50%;top:13px;transform:translateX(-50%);width:68px;height:14px;border-radius:99px;background:rgba(0,0,0,.5);border:1px solid rgba(249,168,50,.2);z-index:5}
.piggy-fill{position:absolute;inset:0;z-index:3;pointer-events:none}
.piggy-falling{position:absolute;inset:0;z-index:4;pointer-events:none;overflow:hidden}
.piggy-glass{position:absolute;inset:14px;border-radius:50%;background:radial-gradient(circle at 32% 18%,rgba(255,255,255,.2),rgba(255,255,255,0) 30%);pointer-events:none;z-index:6}
.piggy-label{position:relative;margin-top:14px;text-align:center;z-index:7}
.piggy-label .pct{font-size:44px;font-weight:800;line-height:1;color:var(--text-primary);letter-spacing:-.05em}
.piggy-label .small{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted);margin-top:6px}
.mdl-coin{position:absolute;display:block;width:30px;height:30px;background-image:url('https://moveisdolar.com.br/colaborador/coin%20png.png');background-size:contain;background-position:center;background-repeat:no-repeat;filter:drop-shadow(0 4px 8px rgba(186,132,14,.3))}
.coin-fill{animation:coinBob 3.2s ease-in-out infinite alternate}
.coin-drop{left:74px;top:16px;opacity:0;animation:coinDropIn 2.8s cubic-bezier(.25,.65,.25,1) infinite}
@keyframes coinDropIn{0%{transform:translate(0,-12px) scale(.55) rotate(0deg);opacity:0}10%{opacity:1}35%{transform:translate(0,4px) scale(.78) rotate(140deg);opacity:1}100%{transform:translate(calc(var(--tx) - 74px),calc(var(--ty) - 16px)) scale(1) rotate(360deg);opacity:0}}
@keyframes coinBob{0%{transform:translateY(0)}100%{transform:translateY(-3px)}}
.metrics-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
.metric{padding:14px;border-radius:var(--radius-md);background:rgba(0,0,0,.2);border:1px solid var(--glass-border)}
.metric .k{font-size:11px;color:var(--text-muted);font-weight:600;text-transform:uppercase;letter-spacing:.08em}
.metric .v{font-size:20px;font-weight:800;margin-top:6px;letter-spacing:-.02em}
.meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}
.meta-card{padding:14px;border-radius:var(--radius-md);background:rgba(0,0,0,.2);border:1px solid var(--glass-border);text-align:center;cursor:pointer;transition:var(--transition)}
.meta-card:hover{border-color:rgba(249,168,50,.25);background:rgba(249,168,50,.04)}
.meta-card .meta-title{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)}
.meta-card .meta-main{font-size:30px;font-weight:800;margin-top:8px;letter-spacing:-.04em}
.meta-card .meta-sub{font-size:11px;color:var(--text-secondary);margin-top:6px}
.accordion{border-radius:var(--radius-lg);overflow:hidden;border:1px solid var(--glass-border);background:var(--glass);margin-top:14px}
.accordion+.accordion{margin-top:14px}
.acc-head{padding:16px 20px;display:flex;justify-content:space-between;align-items:center;cursor:pointer;font-weight:700;font-size:14px;color:var(--text-primary);user-select:none;transition:var(--transition)}
.acc-head:hover{background:rgba(255,255,255,.04)}
.acc-head span:last-child{width:20px;height:20px;border-radius:50%;background:rgba(255,255,255,.06);display:flex;align-items:center;justify-content:center;font-size:11px;transition:transform var(--transition)}
.accordion.open .acc-head span:last-child{transform:rotate(180deg)}
.acc-body{display:none;padding:0 16px 16px}
.accordion.open .acc-body{display:block}
.faixa-block{margin-top:12px}
.faixa-title{padding:10px 14px;border-radius:var(--radius-md);font-weight:700;font-size:13px;display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}
.faixa-title.grave{background:rgba(240,82,82,.12);color:var(--red-400);border:1px solid rgba(240,82,82,.2)}
.faixa-title.alerta{background:rgba(251,146,60,.12);color:var(--orange-400);border:1px solid rgba(251,146,60,.2)}
.faixa-title.atencao{background:rgba(251,191,36,.12);color:var(--yellow-400);border:1px solid rgba(251,191,36,.2)}
.tableish{display:grid;gap:8px;margin-top:10px}
.row-item{padding:12px;border-radius:var(--radius-md);background:rgba(255,255,255,.02);border:1px solid var(--glass-border);transition:var(--transition)}
.row-item:hover{background:rgba(255,255,255,.04);border-color:rgba(255,255,255,.12)}
.row-top{display:grid;grid-template-columns:1.3fr repeat(5,.7fr);gap:10px;align-items:start}
.row-top .name{font-weight:800;font-size:13px}
.small{font-size:12px;color:#d8e2ff}.muted{color:#bfc9e6}
.restr-ok{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:99px;background:rgba(49,196,141,.1);color:var(--green-400);border:1px solid rgba(49,196,141,.2);font-weight:700;font-size:11px}
.avalista-alert{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:99px;background:rgba(251,146,60,.1);color:var(--orange-400);border:1px solid rgba(251,146,60,.2);font-weight:700;font-size:11px;animation:warmPulse 1.8s ease-in-out infinite}
@keyframes warmPulse{0%,100%{opacity:1}50%{opacity:.7}}
.bonus-box{padding:16px;border-radius:var(--radius-xl);background:var(--glass);border:1px solid var(--glass-border)}
.bonus-box h4{margin:0 0 10px;font-size:15px;font-weight:800;color:var(--text-primary)}
.bonus-list{display:grid;gap:8px}
.bonus-item{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;border-radius:var(--radius-md);background:rgba(0,0,0,.18);border:1px solid var(--glass-border);transition:var(--transition)}
.bonus-item .left{display:flex;align-items:center;gap:8px;font-weight:800}
.bonus-item.active{border-color:rgba(249,168,50,.35);background:rgba(249,168,50,.07);animation:glowPulse 2s ease-in-out infinite}
@keyframes glowPulse{0%,100%{box-shadow:0 0 20px rgba(249,168,50,.1)}50%{box-shadow:0 0 32px rgba(249,168,50,.22)}}
.sales-panel{background:linear-gradient(135deg,rgba(249,168,50,.06),rgba(249,168,50,.02));border:1px solid rgba(249,168,50,.15)}
.sales-panel h3{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.sales-note{font-size:11px;color:var(--text-muted);font-weight:700}
.sales-stack{display:flex;flex-direction:column;gap:12px}
.sales-card{background:rgba(0,0,0,.2);border:1px solid rgba(249,168,50,.1);border-radius:var(--radius-md);padding:12px}
.sales-card h4{margin:0 0 8px;font-size:14px;font-weight:700;color:var(--amber-300)}
.sales-sub{font-size:10px;color:var(--amber-400);font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
.sales-list{display:flex;flex-direction:column;gap:8px;max-height:240px;overflow:auto;padding-right:4px}
.sales-row{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.06);border-radius:var(--radius-sm);padding:10px}
.sales-row-title{font-size:12px;font-weight:800;color:var(--text-primary);margin-bottom:8px}
.sales-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}
.sales-empty{padding:14px;border-radius:var(--radius-md);background:rgba(255,255,255,.02);border:1px dashed rgba(249,168,50,.15);color:var(--text-muted);font-weight:700;text-align:center}
.rent-badge{display:inline-flex;align-items:center;gap:8px;padding:7px 12px;border-radius:99px;background:rgba(49,196,141,.08);border:1px solid rgba(49,196,141,.18);color:var(--green-400);font-size:12px;font-weight:700}
.rent-badge strong{font-size:15px;color:#a7f3d0}
.commission-card{background:linear-gradient(135deg,rgba(249,168,50,.06),rgba(249,168,50,.02));border:1px solid rgba(249,168,50,.15);border-radius:var(--radius-xl);padding:20px}
.commission-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.commission-item{background:rgba(0,0,0,.2);border:1px solid var(--glass-border);border-radius:var(--radius-md);padding:12px;transition:var(--transition)}
.commission-item.unlocked{border-color:rgba(249,168,50,.2)}
.commission-item .k{font-size:10px;color:#dbe4ff;font-weight:700;text-transform:uppercase;letter-spacing:.08em}
.commission-item .v{font-size:18px;font-weight:800;color:var(--amber-300);margin-top:6px;letter-spacing:-.02em}
.commission-item.locked{opacity:.4;filter:blur(.5px);position:relative}
.commission-item.locked::after{content:'🔒 Bloqueado';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(13,15,20,.75);font-size:11px;font-weight:700;color:var(--text-muted);border-radius:var(--radius-md)}
.commission-item.total-final{background:linear-gradient(135deg,rgba(249,168,50,.1),rgba(249,168,50,.03));border-color:rgba(249,168,50,.3);box-shadow:0 0 20px rgba(249,168,50,.08)}
.commission-item.total-final .v{color:var(--amber-200);font-size:22px}
.commission-note{margin-top:10px;font-size:11px;color:var(--text-muted);font-weight:600}
.meta-hit-banner{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:var(--radius-md);background:rgba(249,168,50,.08);border:1px solid rgba(249,168,50,.2);margin-bottom:14px}
.meta-hit-banner img{width:34px;height:34px;border-radius:var(--radius-sm);object-fit:cover}
.total-locked{animation:lockPulse 1.6s ease-in-out infinite}
@keyframes lockPulse{0%,100%{opacity:.8}50%{opacity:1}}
.delta-pill{display:inline-flex;align-items:center;gap:5px;padding:5px 10px;border-radius:99px;font-size:12px;font-weight:700}
.delta-pill.up{background:rgba(49,196,141,.1);color:var(--green-400);border:1px solid rgba(49,196,141,.2)}
.delta-pill.down{background:rgba(240,82,82,.1);color:var(--red-400);border:1px solid rgba(240,82,82,.2)}
.delta-pill .arrow{font-size:14px;line-height:1}
.campaign-banner{padding:18px 20px;border-radius:var(--radius-lg);background:linear-gradient(135deg,rgba(249,168,50,.08),rgba(249,168,50,.03));border:1px solid rgba(249,168,50,.2);box-shadow:0 8px 32px rgba(249,168,50,.1);margin-bottom:16px;animation:campaignPulse 2.4s ease-in-out infinite}
@keyframes campaignPulse{0%,100%{box-shadow:0 8px 32px rgba(249,168,50,.1)}50%{box-shadow:0 8px 40px rgba(249,168,50,.22)}}
.campaign-card{background:linear-gradient(135deg,rgba(249,168,50,.07),rgba(249,168,50,.02));border:1px solid rgba(249,168,50,.15);border-radius:var(--radius-xl);padding:20px}
.campaign-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.campaign-item{background:rgba(0,0,0,.2);border:1px solid var(--glass-border);border-radius:var(--radius-md);padding:12px}
.campaign-item .k{font-size:10px;color:var(--text-muted);font-weight:700;text-transform:uppercase;letter-spacing:.08em}
.campaign-item .v{font-size:18px;font-weight:800;color:var(--amber-300);margin-top:6px}
.campaign-item.locked{opacity:.4}
.highlight-pulse{animation:highlightPulse 2.2s ease-in-out infinite}
@keyframes highlightPulse{0%,100%{box-shadow:0 0 0 0 rgba(249,168,50,.0)}50%{box-shadow:0 0 0 6px rgba(249,168,50,.08)}}
.msg-banner{padding:18px 20px;border-radius:var(--radius-lg);background:rgba(249,168,50,.05);border:1px solid rgba(249,168,50,.14);margin-bottom:16px}
.login-wrap{min-height:100vh;display:grid;place-items:center;padding:24px;position:relative;z-index:1}
.login-card{width:min(460px,100%);padding:32px;border-radius:var(--radius-xl)}
.login-card .logo-big{width:76px;height:76px;border-radius:20px;object-fit:contain;background:rgba(255,255,255,.05);margin:0 auto 16px;display:block;border:1px solid rgba(255,255,255,.1);box-shadow:0 0 0 4px rgba(249,168,50,.15),var(--shadow-amber)}
.login-card h2{margin:0;text-align:center;font-size:28px;font-weight:800;letter-spacing:-.03em;background:linear-gradient(135deg,var(--amber-200),var(--amber-400));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.login-form{display:grid;gap:12px;margin-top:22px}
.login-form input{padding:14px 16px;border-radius:var(--radius-md);border:1px solid var(--glass-border);background:rgba(0,0,0,.3);color:var(--text-primary);font-family:inherit;font-size:14px;font-weight:500;outline:none;transition:var(--transition)}
.login-form input:focus{border-color:rgba(249,168,50,.4);box-shadow:0 0 0 3px rgba(249,168,50,.08)}
.login-form input::placeholder{color:var(--text-muted)}
#loginMsg{text-align:center;color:var(--orange-400);font-size:13px;font-weight:600}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.65);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);display:none;place-items:center;z-index:50;padding:20px}
.modal.show{display:grid}
.modal-card{width:min(420px,100%);padding:24px;border-radius:var(--radius-xl)}
.modal-card h3{font-size:18px;font-weight:800;margin-bottom:6px;color:var(--text-primary)}
.modal-list{display:grid;gap:10px;margin-top:16px}
.toast{position:fixed;right:20px;bottom:20px;z-index:60;display:grid;gap:10px}
.toast-item{min-width:280px;padding:14px 16px;border-radius:var(--radius-lg);background:var(--bg-elevated);border:1px solid var(--glass-border);box-shadow:var(--shadow-lg);display:flex;gap:12px;align-items:center;animation:slideInToast .25s ease}
@keyframes slideInToast{from{transform:translateX(40px);opacity:0}to{transform:translateX(0);opacity:1}}
.toast-item img{width:40px;height:40px;border-radius:var(--radius-sm);object-fit:cover}
.form-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.form-grid.bonus{grid-template-columns:repeat(2,1fr)}
.input-card{padding:14px;border-radius:var(--radius-md);background:rgba(0,0,0,.2);border:1px solid var(--glass-border)}
.input-card label{display:block;font-size:11px;color:var(--text-muted);font-weight:700;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}
.input-card input,.input-card select,.input-card textarea{width:100%;padding:10px 12px;border-radius:var(--radius-sm);border:1px solid var(--glass-border);background:rgba(0,0,0,.3);color:var(--text-primary);font-family:inherit;font-size:13px;font-weight:500;outline:none;transition:var(--transition)}
.input-card input:focus,.input-card select:focus{border-color:rgba(249,168,50,.35);box-shadow:0 0 0 2px rgba(249,168,50,.07)}
.input-card select option{background:var(--bg-elevated)}
.logs-list{display:grid;gap:8px;margin-top:14px}
.log-row{padding:14px 16px;border-radius:var(--radius-md);background:rgba(255,255,255,.02);border:1px solid var(--glass-border);display:grid;grid-template-columns:1.4fr 1fr .7fr .8fr auto;gap:12px;align-items:center;transition:var(--transition)}
.log-row:hover{background:rgba(255,255,255,.04)}
.search-row{display:grid;grid-template-columns:1fr 180px 180px 220px;gap:10px;align-items:end}
.msg-card{padding:16px;border-radius:var(--radius-md);background:rgba(255,255,255,.03);border:1px solid var(--glass-border)}
.msg-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.msg-media img,.msg-media video,.msg-media audio{max-width:100%;border-radius:var(--radius-md);margin-top:10px}
.msg-media.compact{width:min(1766px,100%);max-width:100%;height:547px;display:flex;align-items:center;justify-content:center;overflow:hidden;border-radius:var(--radius-md);margin-top:10px;background:rgba(0,0,0,.3)}
.msg-media.compact img,.msg-media.compact video{width:100%;height:100%;object-fit:contain;border-radius:var(--radius-md);margin-top:0}
.msg-media.compact audio{width:min(860px,96%);margin-top:0}
#msgPreviewBody img,#msgPreviewBody video{max-width:100%;max-height:82vh;object-fit:contain;border-radius:var(--radius-md)}
#msgPreviewBody audio{width:min(980px,100%)}
.comm-table{width:100%;border-collapse:separate;border-spacing:0 6px;font-size:12px}
.comm-table th{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);padding:6px 8px}
.comm-table td{background:rgba(0,0,0,.2);border-top:1px solid var(--glass-border);border-bottom:1px solid var(--glass-border);padding:8px}
.comm-table td:first-child{border-left:1px solid var(--glass-border);border-radius:var(--radius-sm) 0 0 var(--radius-sm)}
.comm-table td:last-child{border-right:1px solid var(--glass-border);border-radius:0 var(--radius-sm) var(--radius-sm) 0}
.comm-table input{width:100%;border:none;background:transparent;text-align:center;font-weight:700;color:var(--text-primary);outline:none;font-size:12px}
.comm-table thead th input{background:rgba(0,0,0,.2);border:1px solid var(--glass-border);border-radius:var(--radius-sm);padding:5px 7px;font-size:10px;font-weight:700;color:var(--text-secondary);min-width:100px}
.comm-scroll{overflow-x:auto;padding-bottom:6px}
.comm-wrap{margin-top:18px}
.comm-subtitle{font-size:13px;font-weight:800;color:var(--amber-300);margin:0 0 8px}
.comm-box{background:rgba(0,0,0,.15);border:1px solid var(--glass-border);border-radius:var(--radius-md);padding:14px;margin-top:12px}
.unread-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:99px;background:rgba(240,82,82,.1);color:var(--red-400);font-size:10px;font-weight:700;border:1px solid rgba(240,82,82,.18)}
.read-chip{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:99px;background:rgba(49,196,141,.1);color:var(--green-400);font-size:10px;font-weight:700;border:1px solid rgba(49,196,141,.18)}
.entity-card .mascot-status{margin-top:10px}
.meta-layout{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.meta-preview-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;margin-top:16px}
.empty{padding:26px;text-align:center;border-radius:var(--radius-lg);border:1px dashed rgba(255,255,255,.1);color:var(--text-muted);font-weight:700;font-size:13px;background:rgba(255,255,255,.01)}
.hidden{display:none!important}
@keyframes mascotPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06)}}
@keyframes realPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.02)}}
@keyframes liquidGlow{0%{transform:translateY(0)}100%{transform:translateY(12px)}}
@media(max-width:1100px){.detail-top,.meta-layout,.search-row,.mega-progress{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}.meta-grid{grid-template-columns:repeat(2,1fr)}.sales-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.card-sales-grid{grid-template-columns:1fr}}
@media(max-width:760px){.app-shell{padding:14px 14px 80px}.brand h1{font-size:20px}.kpis{grid-template-columns:1fr}.grid-cards,.meta-preview-grid{grid-template-columns:1fr}.form-grid,.form-grid.bonus,.meta-grid,.metrics-grid,.commission-grid,.campaign-grid{grid-template-columns:1fr}.row-top,.log-row{grid-template-columns:1fr}.tabs{gap:4px}.tab{padding:9px 12px;font-size:12px}.group{min-width:88px}.group .bars{height:220px}.bar{width:16px}}

/* ===== AJUSTE VISUAL DOS CARDS KPI - CORES POR GRUPO E ÍCONES MAIORES ===== */
.kpi.card-cobranca{
  background:
    radial-gradient(circle at 12% 12%, rgba(96,165,250,.30), transparent 36%),
    linear-gradient(135deg, rgba(30,64,175,.36), rgba(15,23,42,.90) 64%) !important;
}
.kpi.card-financeiro{
  background:
    radial-gradient(circle at 12% 12%, rgba(74,222,128,.28), transparent 36%),
    linear-gradient(135deg, rgba(22,101,52,.36), rgba(15,23,42,.90) 64%) !important;
}
.kpi.card-venda-dia{
  background:
    radial-gradient(circle at 12% 12%, rgba(250,204,21,.34), transparent 36%),
    linear-gradient(135deg, rgba(161,98,7,.38), rgba(15,23,42,.90) 64%) !important;
}
.kpi .label{
  display:flex;
  align-items:center;
  gap:8px;
}
.kpi .kpi-emoji{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  font-size:25px;
  line-height:1;
  min-width:26px;
  filter:drop-shadow(0 0 8px rgba(255,255,255,.20));
}
.kpi .kpi-label-text{
  line-height:1.1;
}


/* ===== LARANJITO NOS CARDS DE ALERTA ===== */
@keyframes laranjitoPulse {
  0%,100% { transform: scale(1); filter: drop-shadow(0 0 7px rgba(255,147,0,.35)); }
  50% { transform: scale(1.13); filter: drop-shadow(0 0 18px rgba(255,147,0,.75)); }
}
.kpi.kpi-laranjito{
  position:relative;
  overflow:hidden;
  padding-right:104px !important;
}
.kpi .laranjito-card{
  position:absolute;
  right:14px;
  top:50%;
  transform:translateY(-50%);
  width:78px;
  height:78px;
  border-radius:22px;
  display:flex;
  align-items:center;
  justify-content:center;
  font-size:54px;
  animation:laranjitoPulse 1.4s ease-in-out infinite;
  background:radial-gradient(circle at 40% 35%, rgba(255,177,59,.22), rgba(255,122,0,.06) 60%, transparent 72%);
  pointer-events:none;
}
.kpi .laranjito-caption{
  position:absolute;
  right:13px;
  bottom:8px;
  font-size:10px;
  color:#fbbf24;
  opacity:.9;
  font-weight:800;
  letter-spacing:.04em;
}


/* ===== IMAGENS REAIS DO LARANJITO E ÍCONE DE OURO ===== */
.kpi .kpi-img-icon{
  width:30px;
  height:30px;
  object-fit:contain;
  display:inline-flex;
  flex:0 0 auto;
  filter:drop-shadow(0 0 8px rgba(255,255,255,.22));
}
.kpi .laranjito-card{
  position:absolute;
  right:12px;
  top:50%;
  transform:translateY(-50%);
  width:96px;
  height:96px;
  object-fit:contain;
  border-radius:0;
  animation:laranjitoPulse 1.4s ease-in-out infinite;
  background:transparent;
  pointer-events:none;
  z-index:2;
}
.kpi .laranjito-card::after{content:none!important;}
.kpi.kpi-laranjito{
  padding-right:120px !important;
}
.kpi .laranjito-caption{display:none!important;}

</style>
</head>
<body>
<div id="loginScreen" class="login-wrap">
  <div class="glass login-card">
    <img class="logo-big" src="__LOGO__" alt="logo">
    <h2>Dashboard – Lojas MDL</h2>
    <div class="sub" style="text-align:center">Entre com seu usuário de colaborador ou Master</div>
    <div class="login-form">
      <input id="loginUser" placeholder="Usuário">
      <input id="loginPass" type="password" placeholder="Senha">
      <button class="btn primary" onclick="fazerLogin()">🔐 Entrar</button>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:8px">
        <button class="btn soft" type="button" onclick="openPrimeiroAcesso()">🔑 Primeiro acesso</button>
        <button class="btn soft" type="button" onclick="openRecuperarSenha()">📩 Recuperar senha</button>
      </div>
      <div id="loginMsg" class="note" style="text-align:center;color:#d97706"></div>
    </div>
  </div>
</div>

<div id="app" class="hidden">
  <div class="app-shell">
    <div class="glass header">
      <div class="brand">
        <img src="__LOGO__" alt="logo">
        <div>
          <h1>Dashboard – Lojas MDL</h1>
          <div class="sub">Período Cobrança: __PERIODO__ · Vendedores: painel individual · Gerentes: painel de filial</div>
        </div>
      </div>
      <div class="header-actions">
        <button id="bellBtn" class="btn soft" onclick="openBell()">🔔 Avisos <span id="bellCount" class="badge" style="padding:4px 8px;margin-left:4px;background:#eef5ff">0</span></button>
        <div id="userBadge" class="badge">👑 Master</div>
        <button class="btn soft" onclick="logout()">Sair</button>
      </div>
    </div>

    <div id="kpis" class="kpis"></div>

    <div id="masterTabs" class="tabs hidden">
      <button class="tab active" data-tab="vendedores" onclick="setMainTab('vendedores')">👥 Por Colaborador</button>
      <button class="tab" data-tab="filiais" onclick="setMainTab('filiais')">🏬 Por Filial</button>
      <button class="tab" data-tab="metas" onclick="setMainTab('metas')">🎯 Metas</button>
      <button class="tab" data-tab="servicos" onclick="setMainTab('servicos')">🛠️ Serviços</button>
      <button class="tab" data-tab="cobrancas" onclick="setMainTab('cobrancas')">🧾 Cobranças</button>
      <button class="tab" data-tab="avisos" onclick="setMainTab('avisos')">📣 Avisos</button>
      <button class="tab" data-tab="senhas" onclick="setMainTab('senhas')">🔐 Senhas</button>
      <button class="tab" data-tab="historico" onclick="setMainTab('historico')">🗂️ Histórico</button>
    </div>

    <div id="mainFilters" class="filters hidden"></div>

    <div id="mainScreen">
      <div id="listSection"></div>
      <div id="metaSection" class="hidden"></div>
      <div id="servicesSection" class="hidden"></div>
      <div id="logSection" class="hidden"></div>
      <div id="avisosSection" class="hidden"></div>
      <div id="senhasSection" class="hidden"></div>
      <div id="histSection" class="hidden"></div>
    </div>

    <div id="detailScreen" class="detail-screen hidden"></div>
  </div>
</div>

<div id="toast" class="toast"></div>
<div id="phoneModal" class="modal"><div class="glass modal-card"><h3 style="margin:0">Escolher contato</h3><div class="sub">Selecione para abrir o WhatsApp</div><div id="phoneList" class="modal-list"></div><button class="btn soft" style="width:100%;margin-top:10px" onclick="closePhoneModal()">Fechar</button></div></div>
<div id="bellModal" class="modal"><div class="glass modal-card" style="width:min(760px,100%)"><h3 style="margin:0">🔔 Avisos e mensagens</h3><div class="sub">Atualizações enviadas pelo Master para você.</div><div id="bellList" class="modal-list" style="max-height:70vh;overflow:auto"></div><button class="btn soft" style="width:100%;margin-top:10px" onclick="closeBell()">Fechar</button></div></div>
<div id="firstAccessModal" class="modal"><div class="glass modal-card" style="width:min(560px,100%)"><h3 style="margin:0">🔑 Primeiro acesso / troca de senha</h3><div class="sub">Defina sua nova senha para entrar no dashboard.</div><div class="modal-list"><div class="input-card"><label>Usuário</label><input id="faLogin" placeholder="Ex: joaodasilva"></div><div class="input-card"><label>Senha atual</label><input id="faCurrentPass" type="password" placeholder="Senha atual"></div><div class="input-card"><label>Nova senha</label><input id="faNewPass" type="password" placeholder="Nova senha"></div><div class="input-card"><label>Confirmar nova senha</label><input id="faNewPass2" type="password" placeholder="Confirmar nova senha"></div><div id="faMsg" class="note"></div></div><div style="display:flex;gap:10px;margin-top:10px"><button class="btn primary" style="flex:1" onclick="salvarPrimeiroAcesso()">💾 Salvar nova senha</button><button class="btn soft" style="flex:1" onclick="closeFirstAccess()">Fechar</button></div></div></div>
<div id="recoverModal" class="modal"><div class="glass modal-card" style="width:min(560px,100%)"><h3 style="margin:0">📩 Recuperar senha</h3><div class="sub">O pedido será enviado para o Master no dashboard e também pode ser registrado em sac@moveisdolar.com.br.</div><div class="modal-list"><div class="input-card"><label>Usuário</label><input id="recLogin" placeholder="Seu usuário"></div><div class="input-card"><label>Nome / observação</label><input id="recObs" placeholder="Ex: sou da filial F4"></div><div id="recMsg" class="note"></div></div><div style="display:flex;gap:10px;margin-top:10px"><button class="btn primary" style="flex:1" onclick="enviarRecuperacaoSenha()">📨 Enviar solicitação</button><button class="btn soft" style="flex:1" onclick="closeRecover()">Fechar</button></div></div></div>

<script>
const CREDS=__JS_CREDS__;
const AUTH_BOOT=__JS_AUTH_STATE__;
const TODOS=__JS_TODOS__;
const FILIAIS=__JS_FILIAIS__;
const CLIENTES_FIL=__JS_CLIENTES__;
const CLIENTES_VEND=__JS_CLIENTES_VEND__;
const CLIENTES_TERCEIRO=__JS_CLIENTES_TERCEIRO__;
const CLIENTES_CREDIARISTA=__JS_CLIENTES_CREDIARISTA__||{};
const RECEBIMENTOS=__JS_RECEBIMENTOS__;
const RECEBIMENTOS_TERCEIRO=__JS_RECEBIMENTOS_TERCEIRO__;
const RECEBIMENTOS_CREDIARISTA=__JS_RECEBIMENTOS_CREDIARISTA__||{};
const CREDIARISTAS_MAP=__JS_CREDIARISTAS_MAP__||{};
const COBRANCA10_LOGIN='cobranca10';
const COBRANCA10_NOME='Cobrança10';
const METAS_VENDAS=__JS_METAS_VENDAS__||{metas:{}};
const MARGENS_BRUTAS=__JS_MARGENS_BRUTAS__||{filiais:{},vendedores:{}};
let SALES_EMPRESA=__JS_SALES_EMPRESA__||{};
let RENT_EMPRESA=__JS_RENT_EMPRESA__||{};
let SERVICOS_RELATORIO=__JS_SERVICOS_RELATORIO__||{empresa:{},servicos:{},filiais:{},vendedores:{},detalhes:[]};
let CONFIG_META={grave_pct:20,alerta_pct:15,atencao_pct:10,peso_grave:60,peso_alerta:30,peso_atencao:10,bonus_50:'',bonus_75:'',bonus_85:'',bonus_100:'',cob_cred_rateio_filial_pct:50,cob_cred_rateio_cred_pct:50,cobranca_global_rateio_pct:20,...(__CONFIG_META__||{})};
let CONFIG_META_IND=__CONFIG_META_IND__||{};
const LOGIN_MASTER=String(__LOGIN_MASTER__);
const SENHA_MASTER=String(__SENHA_MASTER__);
const LOGIN_DIRETOR=String(__LOGIN_DIRETOR__);
const SENHA_DIRETOR=String(__SENHA_DIRETOR__);
const ORDEM=__ORDEM__||[];
const TOTAL_P=Number(__TOTAL_P__||0);
const TOTAL_PG=Number(__TOTAL_PG__||0);
const DESTAQUE_SEMANA=__JS_DESTAQUE__||{};
const LOGO='__LOGO__';
const LARANJITO='__LARANJITO__';
const MDL_COIN_IMG='https://moveisdolar.com.br/colaborador/coin%20png.png';
const API_CFG='config_meta_api.php';
const API_COB='cobrancas_api.php';
const API_MSG='mensagens_api.php';
const API_CRED='credenciais_api.php';
const API_HIST='historico_api.php';
let usuarioAtual=null;
let mainTab='vendedores';
let filtroFilial='TODAS';
let COB_LOGS=[];
let phoneContext=null;
let MSGS=[];
let currentDetailRef=null;
let _logFiltered=[];
let AUTH_STATE=AUTH_BOOT||{users:{},director:{},password_reset_requests:[]};
let _pendingFirstAccess=null;
let HIST_DASH=__JS_HIST_DASH__||{dates:{}};
const SESSION_KEY='mdl_dashboard_session_v1';
function getAuthUser(login){const k=String(login||'').trim().toLowerCase(); if(k===LOGIN_DIRETOR.toLowerCase()) return AUTH_STATE?.director||null; return (AUTH_STATE?.users||{})[k]||null}
async function carregarCredenciaisOnline(){try{const r=await fetch(API_CRED+'?_='+Date.now()); const j=await r.json(); if(j.ok && j.data){AUTH_STATE=j.data;}}catch(e){console.log('Falha ao carregar credenciais online',e);}}
async function carregarHistoricoOnline(){try{const r=await fetch(API_HIST+'?_='+Date.now()); const j=await r.json(); if(j.ok && j.data){HIST_DASH=j.data;}}catch(e){console.log('Falha ao carregar histórico online',e);}}
function saveSession(){try{const data={usuarioAtual,exp:Date.now()+60*60*1000}; localStorage.setItem(SESSION_KEY, JSON.stringify(data));}catch(e){}}
function clearSession(){try{localStorage.removeItem(SESSION_KEY);}catch(e){}}
function restoreSession(){try{const raw=localStorage.getItem(SESSION_KEY); if(!raw) return false; const data=JSON.parse(raw); if(!data || !data.usuarioAtual || !data.exp || Date.now()>data.exp){localStorage.removeItem(SESSION_KEY); return false;} usuarioAtual=data.usuarioAtual; return true;}catch(e){return false;}}
function currentUserKey(){return usuarioAtual?.tipo==='master'?'MASTER':(usuarioAtual?.login || `${usuarioAtual?.nome||''}_${usuarioAtual?.filial||''}`)}

const loginScreen=document.getElementById('loginScreen');
const app=document.getElementById('app');
const userBadge=document.getElementById('userBadge');
const masterTabs=document.getElementById('masterTabs');
const mainFilters=document.getElementById('mainFilters');
const listSection=document.getElementById('listSection');
const metaSection=document.getElementById('metaSection');
const servicesSection=document.getElementById('servicesSection');
const logSection=document.getElementById('logSection');
const detailScreen=document.getElementById('detailScreen');
const avisosSection=document.getElementById('avisosSection');
const senhasSection=document.getElementById('senhasSection');
const histSection=document.getElementById('histSection');

function R(v){return Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'})}
function pct(v){return `${Math.round(Number(v||0))}%`}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]))}
function trunc(s,n=18){s=String(s||'');return s.length>n?s.slice(0,n-1)+'…':s}
function filialLabel(f){return String(f||'').replace(/^F/,'Filial F')}
function flattenVendedores(){const out=[];Object.entries(TODOS||{}).forEach(([f,arr])=>(arr||[]).forEach(v=>out.push({type:'vendedor',filial:f,...v})));return out}
function thirdChargeEntity(){const src=CLIENTES_TERCEIRO||{grave:[],alerta:[],atencao:[]}; const rsrc=RECEBIMENTOS_TERCEIRO||{grave:[],alerta:[],atencao:[]}; const pend=[...(src.grave||[]),...(src.alerta||[]),...(src.atencao||[])].reduce((a,b)=>a+Number(b.pendente||0),0); const rec=[...(rsrc.grave||[]),...(rsrc.alerta||[]),...(rsrc.atencao||[])].reduce((a,b)=>a+Number(b.pago||0),0); return {type:'terceiro',login:COBRANCA10_LOGIN,filial:'FTER',nome:COBRANCA10_NOME,is_terceiro:true,is_gerente:false,pendente:pend,pago:rec,total:pend+rec,perc_filial:100,grave_pend:(src.grave||[]).reduce((a,b)=>a+Number(b.pendente||0),0),alerta_pend:(src.alerta||[]).reduce((a,b)=>a+Number(b.pendente||0),0),atencao_pend:(src.atencao||[]).reduce((a,b)=>a+Number(b.pendente||0),0),grave_rec:(rsrc.grave||[]).reduce((a,b)=>a+Number(b.pago||0),0),alerta_rec:(rsrc.alerta||[]).reduce((a,b)=>a+Number(b.pago||0),0),atencao_rec:(rsrc.atencao||[]).reduce((a,b)=>a+Number(b.pago||0),0)}}
function crediaristaEntities(){return Object.entries(CREDIARISTAS_MAP||{}).map(([filial,login])=>{
  const filialKey=String(filial||'').toUpperCase();
  const loginKey=String(login||'').toLowerCase();
  const filData=FILIAIS?.[filialKey]||{};
  return {
    type:'crediarista',login:loginKey,filial:filialKey,nome:`CREDIARISTA${filialKey}`,
    is_crediarista:true,is_gerente:false,only_cobranca:true,
    // O crediarista usa exatamente os mesmos totais consolidados da filial/gerente.
    pendente:Number(filData.pendente||0),
    pago:Number(filData.pago||0),
    total:Number(filData.total||0),
    perc_filial:100,
    grave_pend:Number(filData.grave_pend||0),alerta_pend:Number(filData.alerta_pend||0),atencao_pend:Number(filData.atencao_pend||0),
    grave_rec:Number(filData.grave_rec||0),alerta_rec:Number(filData.alerta_rec||0),atencao_rec:Number(filData.atencao_rec||0),
    grave_alvo:Number(filData.grave_alvo||0),alerta_alvo:Number(filData.alerta_alvo||0),atencao_alvo:Number(filData.atencao_alvo||0),
    grave_perc:Number(filData.grave_perc||0),alerta_perc:Number(filData.alerta_perc||0),atencao_perc:Number(filData.atencao_perc||0),
    perc_meta:Number(filData.perc_meta||0),
    rentabilidade_pct:Number(filData.rentabilidade_pct||0),
    sem_ativo:Boolean(filData.sem_ativo||false),
  };
})}
function crediaristaLoginByFilial(filial){const want=String(filial||'').toUpperCase(); for(const [f,l] of Object.entries(CREDIARISTAS_MAP||{})){ if(String(f||'').toUpperCase()===want) return String(l||'').toLowerCase(); } return ''}
function crediaristaEntityByLogin(login){const key=String(login||'').toLowerCase(); return crediaristaEntities().find(x=>String(x.login||'').toLowerCase()===key || String(x.nome||'').toLowerCase()===key || String(x.filial||'').toLowerCase()===key)||null}
function flattenFiliais(){const out=[];ORDEM.forEach(f=>{if(FILIAIS[f]) out.push({type:'filial',filial:f,nome:filialLabel(f),...FILIAIS[f]})});return out}
function metaPureKey(ent){return ent.type==='vendedor'?`${ent.nome}_${ent.filial}`:ent.filial}
function metaCanonKey(ent){return ent.type==='vendedor'?`VEND::${metaPureKey(ent)}`:`FILIAL::${metaPureKey(ent)}`}
function normMetaKey(v){return String(v||'').normalize('NFD').replace(/[̀-ͯ]/g,'').replace(/\s+/g,' ').trim()}
function metaAliasesFromRaw(raw){
  const val=String(raw||'').trim();
  if(!val) return [];
  const parts=val.split('::');
  const hasKind=parts.length>1;
  const kind=hasKind?parts[0]:'';
  const pure=hasKind?parts.slice(1).join('::'):val;
  const alias=new Set([val,pure,String(val).toUpperCase(),String(pure).toUpperCase(),normMetaKey(val),normMetaKey(pure),normMetaKey(val).toUpperCase(),normMetaKey(pure).toUpperCase()]);
  if(kind==='VEND' || (!hasKind && pure.includes('_F'))){ alias.add(`VEND::${pure}`); alias.add(`vend:${pure}`); }
  if(kind==='FILIAL' || (!hasKind && /^F\d+/i.test(pure))){ alias.add(`FILIAL::${pure}`); alias.add(`fil:${pure}`); }
  return Array.from(alias).filter(Boolean);
}
function metaAliasesFromEntity(ent){
  const pure=metaPureKey(ent), canon=metaCanonKey(ent), old=ent.type==='vendedor'?`vend:${pure}`:`fil:${pure}`;
  return Array.from(new Set([...metaAliasesFromRaw(pure),...metaAliasesFromRaw(canon),old]));
}
function mergedMetaConfig(aliases){let cfg={...CONFIG_META}; (aliases||[]).forEach(k=>{ if(CONFIG_META_IND[k]) cfg={...cfg,...CONFIG_META_IND[k]}; }); return cfg}
function entityConfig(ent){return mergedMetaConfig(metaAliasesFromEntity(ent))}
function calcMeta(ent){const cfg=entityConfig(ent);const gPend=Number(ent.grave_pend||0), aPend=Number(ent.alerta_pend||0), tPend=Number(ent.atencao_pend||0);const gRec=Number(ent.grave_rec||0), aRec=Number(ent.alerta_rec||0), tRec=Number(ent.atencao_rec||0);
  const gAlvo=gPend*Number(cfg.grave_pct||0)/100, aAlvo=aPend*Number(cfg.alerta_pct||0)/100, tAlvo=tPend*Number(cfg.atencao_pct||0)/100;
  const gPerc=gAlvo>0?(gRec/gAlvo*100):(gRec>0?100:0), aPerc=aAlvo>0?(aRec/aAlvo*100):(aRec>0?100:0), tPerc=tAlvo>0?(tRec/tAlvo*100):(tRec>0?100:0);
  const sumW=Number(cfg.peso_grave||0)+Number(cfg.peso_alerta||0)+Number(cfg.peso_atencao||0)||1;
  const geral=((Math.min(gPerc,100)*Number(cfg.peso_grave||0))+(Math.min(aPerc,100)*Number(cfg.peso_alerta||0))+(Math.min(tPerc,100)*Number(cfg.peso_atencao||0)))/sumW;
  return {cfg,grave:{pend:gPend,rec:gRec,alvo:gAlvo,perc:gPerc},alerta:{pend:aPend,rec:aRec,alvo:aAlvo,perc:aPerc},atencao:{pend:tPend,rec:tRec,alvo:tAlvo,perc:tPerc},geral:geral};
}
function getBonus(cfg,perc){const p=Number(perc||0);if(p>=100 && cfg.bonus_100) return {thr:100,text:cfg.bonus_100};if(p>=85 && cfg.bonus_85) return {thr:85,text:cfg.bonus_85};if(p>=75 && cfg.bonus_75) return {thr:75,text:cfg.bonus_75};if(p>=50 && cfg.bonus_50) return {thr:50,text:cfg.bonus_50};return null}
function renderDeltaPill(delta,perc){const up=Number(delta||0)>=0;return `<span class="delta-pill ${up?'up':'down'}"><span class="arrow">${up?'⬆️':'⬇️'}</span><span>${pct(Math.abs(Number(perc||0)))}</span></span>`}
function renderPiggyBank(perc){
  const p=Math.max(0,Math.min(100,Number(perc||0)));
  const positions=[[30,110],[60,106],[90,112],[119,108],[45,86],[77,82],[108,86],[60,58],[93,60],[76,132],[106,132],[45,133]];
  const filled=Math.max(1,Math.round((p/100)*positions.length));
  const falling=Math.max(1,Math.min(3,Math.ceil(p/34)));
  const baseCoins=positions.slice(0,filled).map(([x,y],i)=>`<span class="mdl-coin coin-fill" style="left:${x}px;top:${y}px;animation-delay:${i*0.12}s"></span>`).join('');
  const dropTargets=positions.slice(Math.max(0,filled-falling), filled);
  const fallingCoins=dropTargets.map(([x,y],i)=>`<span class="mdl-coin coin-drop" style="--tx:${x}px;--ty:${y}px;animation-delay:${i*0.45}s"></span>`).join('');
  return `<div class="piggy-bank" style="--pct:${p}"><div class="piggy-glow"></div><div class="piggy-shell"><div class="piggy-slot"></div><div class="piggy-falling">${fallingCoins}</div><div class="piggy-fill">${baseCoins}</div><div class="piggy-glass"></div></div><div class="piggy-label"><div class="pct">${pct(p)}</div><div class="small">Meta geral</div></div></div>`;
}
function toast(msg, type='info'){const host=document.getElementById('toast'); const el=document.createElement('div'); el.className='toast-item'; el.innerHTML=`<img src="${LARANJITO}" alt="ok"><div><div style="font-weight:900">${type==='success'?'Tudo certo!':'Aviso'}</div><div class="small">${esc(msg)}</div></div>`; host.appendChild(el); setTimeout(()=>{el.remove();},4200)}
function mascotCongrats(ent){const meta=calcMeta(ent);const b=getBonus(meta.cfg,meta.geral);if(!b) return;toast(`Parabéns, ${ent.type==='vendedor'?ent.nome:filialLabel(ent.filial)}! Meta em ${pct(meta.geral)}. ${b.text||''}`,'success')}
function makeKpi(label,val,accent,sub='',extraClass='',mascote='',iconHtml=''){
  const raw=String(label||'').trim();
  const p=raw.split(' ');
  const emoji=p.length>1?p[0]:'';
  const txt=p.length>1?p.slice(1).join(' '):raw;
  const icon = iconHtml ? iconHtml : (emoji?`<span class="kpi-emoji">${emoji}</span>`:'');
  const masc = mascote ? `<img class="laranjito-card ${esc(mascote)}" src="${laranjitoSrc(mascote)}" alt="Laranjito ${esc(mascote)}" loading="lazy">` : '';
  return `<div class="glass kpi ${extraClass||''} ${mascote?'kpi-laranjito':''}" style="--accent:${accent}">
    <div class="label">${icon}<span class="kpi-label-text">${esc(txt)}</span></div>
    <div class="value">${val}</div>
    ${sub?`<div class="subline">${sub}</div>`:''}
    ${masc}
  </div>`;
}

const LARANJITO_IMG = {
  triste: 'mascote%20triste1.png',
  preocupado: 'mascote%20preocupado1.png',
  feliz: 'mascote%20feliz1.png'
};
const GOLD_BAR_ICON = 'data:image/png;base64,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';
function laranjitoSrc(status){
  return LARANJITO_IMG[status] || LARANJITO_IMG.triste;
}
function kpiImgIcon(src, alt=''){
  return `<img class="kpi-img-icon" src="${src}" alt="${esc(alt)}" loading="lazy">`;
}

function renderKPIs(){
  const grave=flattenFiliais().reduce((a,b)=>a+Number(b.grave_pend||0),0);
  const alerta=flattenFiliais().reduce((a,b)=>a+Number(b.alerta_pend||0),0);
  const rentPct=Number(RENT_EMPRESA?.margem_bruta_pct||0);
  const sales=SALES_EMPRESA||{};
  const salesDates=Object.keys(HIST_DASH?.sales_dates||{}).sort();
  const hojeIso=new Date().toISOString().slice(0,10);
  const prevDate=salesDates.filter(d=>String(d)<String(hojeIso)).slice(-1)[0]||'';
  const prevEmpresa=(prevDate?(HIST_DASH?.sales_dates?.[prevDate]?.empresa||{}):{});
  // 🔥 Serviços realizado deve vir do relatório real de serviços, não da meta SGI.
  // Antes usava sales.servico_realizado_total, que vem de servico_filial_ouro_fob
  // e pode divergir do relatorio_servicos_mes_atual.json.
  const servicoRelatorioTotal = Number(SERVICOS_RELATORIO?.empresa?.real_total || 0);
  const servicoRealizadoOficial = servicoRelatorioTotal > 0 ? servicoRelatorioTotal : Number(sales.servico_realizado_total||0);
  const servicoAtingidoOficial = Number(sales.servico_meta_total||0)>0
    ? (servicoRealizadoOficial / Number(sales.servico_meta_total||0) * 100)
    : Number(sales.servico_atingido_total||0);

  const prevServicoReal = Number(prevEmpresa.servico_realizado_realatorio_total || prevEmpresa.servico_realizado_total || 0);
  const vendaDiaria=Math.max(0, Number(sales.venda_realizado_total||0)-Number(prevEmpresa.venda_realizado_total||0)) + Math.max(0, servicoRealizadoOficial-prevServicoReal);
  const markupBase=(Number(sales.venda_realizado_total||0)+servicoRealizadoOficial);
  const markupCost=Number(RENT_EMPRESA?.custo_total||0);
  const markupTotal=markupCost>0?(markupBase/markupCost):0;
  function statusLaranjitoVendaDiaria(v){
    v=Number(v||0);
    if(v < 20000) return 'triste';
    if(v <= 25000) return 'preocupado';
    return 'feliz';
  }
  function statusLaranjitoMarkup(v){
    v=Number(v||0);
    if(!v || v < 2.00) return 'triste';
    if(v <= 2.14) return 'preocupado';
    return 'feliz';
  }
  const isViewer=!!usuarioAtual?.is_viewer;
  const isPrivileged=(usuarioAtual?.tipo==='master' || isViewer);

  // Cards extras por tipo de serviço vindos do relatorio_servicos_mes_atual.json
  function servicoIcone(nome){
    const n=normSalesText(nome||'');
    if(n.includes('FOB')) return '🚚';
    if(n.includes('COPA') || n.includes('CUPOM')) return '⚽';
    return '🛠️';
  }
  function servicoIconeHtml(nome){
    const n=normSalesText(nome||'');
    if(n.includes('OURO')) return kpiImgIcon(GOLD_BAR_ICON, 'Barra de ouro');
    return '';
  }
  const topServiceCards = Object.values((SERVICOS_RELATORIO && SERVICOS_RELATORIO.servicos) || {})
    .slice()
    .sort((a,b)=>Number(b.real_total||0)-Number(a.real_total||0))
    .slice(0,4)
    .map(s=>{
      const customIcon=servicoIconeHtml(s.servico);
      const labelIcon=customIcon ? '🟨' : servicoIcone(s.servico);
      return makeKpi(`${labelIcon} ${String(s.servico||'Serviço').slice(0,30)}`, R(s.real_total||0), 'var(--blue-400)', `${Number(s.quantidade||0).toLocaleString('pt-BR')} item(ns)`, '', '', customIcon);
    });

  const cards=[
    makeKpi('💰 Total pendente',R(TOTAL_P),'var(--red)','', 'card-cobranca'),
    makeKpi('🏦 Total recebido',R(TOTAL_PG),'var(--green)','', 'card-cobranca'),
    makeKpi('🚨 Grave',R(grave),'var(--red)','', 'card-cobranca'),
    makeKpi('🟠 Alerta',R(alerta),'var(--orange)','', 'card-cobranca'),
    makeKpi('📦 Mercantil realizado',R(sales.venda_realizado_total||0),'var(--amber-400)',`Meta ${R(sales.venda_meta_total||0)} · Atingido ${pct(sales.venda_atingido_total||0)}`),
    makeKpi('📈 Mercantil projetado',R(sales.venda_projetado||0),'var(--amber-500)',`Meta período ${R(sales.venda_meta_periodo||0)}`),
    makeKpi('🛠️ Serviços realizado',R(servicoRealizadoOficial),'var(--blue)',`Meta ${R(sales.servico_meta_total||0)} · Atingido ${pct(servicoAtingidoOficial)} · relatório serviços`),
    makeKpi('🧰 Serviços projetado',R(sales.servico_projetado||0),'var(--blue-400)',`Meta período ${R(sales.servico_meta_periodo||0)}`),
    ...topServiceCards,
    makeKpi('🚚 Caminhão realizado',R(sales.caminhao_realizado_total||0),'var(--yellow)',`Meta ${R(sales.caminhao_meta_total||0)} · Atingido ${pct(sales.caminhao_atingido_total||0)}`),
    makeKpi('🛣️ Caminhão projetado',R(sales.caminhao_projetado||0),'var(--yellow-400)',`Meta período ${R(sales.caminhao_meta_periodo||0)}`),
    (isPrivileged ? makeKpi('💵 Faturamento total',R((Number(sales.venda_realizado_total||0)+servicoRealizadoOficial)),'var(--green-400)','Mercantil + serviços realizado', 'card-financeiro') : ''),
    (isPrivileged ? makeKpi('🕒 Venda diária',R(vendaDiaria),'var(--cyan-400)','Mercantil + serviços do dia', 'card-venda-dia', statusLaranjitoVendaDiaria(vendaDiaria)) : ''),
    makeKpi('📊 Rentabilidade total', rentPct?`${rentPct.toFixed(2).replace('.',',')}%`:'Sem dado','var(--green-400)','Última linha do relatório de margem bruta por filial', 'card-financeiro'),
    makeKpi('🧮 Markup total', markupTotal?String(markupTotal.toFixed(2)).replace('.',','):'0,00','var(--amber-400)', isViewer ? 'Índice mercantil + serviços / custo oculto' : `(Mercantil + serviços) / custo total ${R(markupCost||0)}`, 'card-financeiro', statusLaranjitoMarkup(markupTotal))
  ];
  document.getElementById('kpis').innerHTML=cards.join('') + `<div class="glass" style="grid-column:1/-1;padding:10px 14px;display:flex;align-items:center;justify-content:flex-start;min-height:46px"><div style="font-size:12px;color:#a9b2c7">🕒 Última atualização do dashboard: <strong style="color:#e5e7eb">${esc(latestUpdatedLabel()||'--')}</strong></div></div>`;
}

async function fetchJsonNoCache(url){
  const r=await fetch(url+(url.includes('?')?'&':'?')+'_='+Date.now(),{cache:'no-store'});
  if(!r.ok) throw new Error('HTTP '+r.status);
  return await r.json();
}
const DASHBOARD_UPDATED_AT_LABEL='12/05/2026 17:28:27';

function formatUpdatedLabel(v){
  try{
    const s=String(v||'').trim();
    if(!s) return '';
    if(/^\d{2}\/\d{2}\/\d{4}[, ]+\d{2}:\d{2}:\d{2}$/.test(s)) return s.replace(',', '').replace(/\s+/g,' ').trim();
    const d=new Date(s);
    if(!isNaN(d.getTime())){
      return d.toLocaleString('pt-BR',{timeZone:'America/Sao_Paulo', hour12:false}).replace(',', '');
    }
    return s.replace(',', '').replace(/\s+/g,' ').trim();
  }catch(_e){
    return String(v||'').replace(',', '').trim();
  }
}
function dashboardUpdatedLabel(){
  return formatUpdatedLabel(window.__dashboardUpdatedAtLabel || DASHBOARD_UPDATED_AT_LABEL);
}
function latestUpdatedLabel(){
  const aRaw = window.__dashboardUpdatedAtLabel || DASHBOARD_UPDATED_AT_LABEL || '';
  const bRaw = window.__salesUpdatedAtLabel || '';
  const a = formatUpdatedLabel(aRaw);
  const b = formatUpdatedLabel(bRaw);
  if(!a && !b) return '';
  if(a && !b) return a;
  if(b && !a) return b;
  const da = new Date(aRaw);
  const db = new Date(bRaw);
  if(!isNaN(da.getTime()) && !isNaN(db.getTime())){
    return db > da ? b : a;
  }
  return b || a;
}

function calcSalesEmpresaFromMetas(payload){
  const metas=((payload||{}).metas)||{};
  function totalOf(key){
    const linhas=((metas[key]||{}).linhas)||[];
    const total=linhas.find(x=>x&&x._is_total) || {};
    return {
      real_total:Number(total['Realizado(R$) Total_float']||0),
      ating_total:Number(total['Atingido Total_float']||0),
      proj:Number(total['Projetado(R$)_float']||0),
      meta_total:Number(total['Meta(R$) Total_float']||0),
      meta_per:Number(total['Meta(R$) Período_float']||0),
    };
  }
  const venda=totalOf('venda_filial_meta');
  const serv=totalOf('servico_filial_ouro_fob');
  const cam=totalOf('venda_filial_subgrupo_20k');
  return {
    venda_realizado_total:venda.real_total,
    venda_atingido_total:venda.ating_total,
    venda_projetado:venda.proj,
    venda_meta_total:venda.meta_total,
    venda_meta_periodo:venda.meta_per,
    servico_realizado_total:serv.real_total,
    servico_atingido_total:serv.ating_total,
    servico_projetado:serv.proj,
    servico_meta_total:serv.meta_total,
    servico_meta_periodo:serv.meta_per,
    caminhao_realizado_total:cam.real_total,
    caminhao_atingido_total:cam.ating_total,
    caminhao_projetado:cam.proj,
    caminhao_meta_total:cam.meta_total,
    caminhao_meta_periodo:cam.meta_per,
  };
}
async function pollSalesLive(){
  try{
    const ver=await fetchJsonNoCache('sales_version.json');
    const stamp=String(ver?.updated_at_label||ver?.updated_at||'');
    if(stamp){ window.__salesUpdatedAtLabel = stamp; }

    // Sempre tenta atualizar os arquivos de vendas/serviços quando a página está aberta.
    // Assim os cards aparecem mesmo quando o usuário entrou depois da última execução.
    let metasWrap=null, margensWrap=null, servWrap=null;
    try{ metasWrap=await fetchJsonNoCache('metas_vendas_mes_atual.json'); }catch(_e){}
    try{ margensWrap=await fetchJsonNoCache('margens_brutas_mes_atual.json'); }catch(_e){}
    try{ servWrap=await fetchJsonNoCache('relatorio_servicos_mes_atual.json'); }catch(_e){}

    if(metasWrap) SALES_EMPRESA=calcSalesEmpresaFromMetas(metasWrap||{});
    if(margensWrap) RENT_EMPRESA=((margensWrap||{}).empresa)||{};
    if(servWrap) SERVICOS_RELATORIO=(servWrap||{});

    if(stamp) window.__lastSalesVersion=stamp;
    if(typeof renderKPIs==='function' && document.getElementById('kpis')) renderKPIs();
    if(typeof renderServicosTab==='function' && (!servicesSection.classList.contains('hidden') || usuarioAtual?.is_viewer)) renderServicosTab(!!usuarioAtual?.is_viewer);
    if(!detailScreen.classList.contains('hidden') && currentDetailRef){
      try{ openEntity(currentDetailRef); }catch(_e){}
    }
  }catch(e){console.log('pollSalesLive',e)}
}
async function pollDashboardLiveReload(){
  try{
    const ver=await fetchJsonNoCache('dashboard_version.json');
    const stamp=String(ver?.updated_at||ver?.updated_at_label||'');
    if(stamp){
      window.__dashboardUpdatedAtLabel = stamp;
      if(typeof renderKPIs==='function' && document.getElementById('kpis')) renderKPIs();
    }
    if(!stamp) return;
    if(window.__lastDashboardVersion===undefined){window.__lastDashboardVersion=stamp; return;}
    if(window.__lastDashboardVersion!==stamp){ location.reload(); return; }
  }catch(e){console.log('pollDashboardLiveReload',e)}
}


function _srvSortedEntries(obj, key='real_total'){
  return Object.values(obj||{}).slice().sort((a,b)=>Number(b?.[key]||0)-Number(a?.[key]||0));
}
function _srvMiniCard(title, value, subtitle=''){
  return `<div class="glass panel" style="padding:14px 16px"><div class="mini" style="margin-bottom:8px">${esc(title)}</div><div class="big" style="font-size:28px;color:#f8fafc">${value}</div>${subtitle?`<div class="hint" style="margin-top:6px">${subtitle}</div>`:''}</div>`;
}
function _srvRankRows(rows, kind){
  if(!rows.length) return `<div class="empty">Nenhum dado encontrado no relatório de serviços.</div>`;
  return rows.map((r,idx)=>{
    const label = kind==='servico' ? (r.servico||'-') : (kind==='filial' ? (r.label||r.filial||'-') : (r.label||r.nome||'-'));
    const qtd = Number(r.quantidade||0);
    const total = Number(r.real_total||0);
    const details = kind==='vendedor' ? `${esc(r.filial||'')}` : `${qtd.toLocaleString('pt-BR')} item(ns)`;
    return `<div class="log-row"><div><strong>${idx+1}. ${esc(label)}</strong><div class="small muted">${details}</div></div><div><strong>${R(total)}</strong><div class="small muted">Total</div></div></div>`;
  }).join('');
}
function renderServicosTab(isViewer=false){
  const data = SERVICOS_RELATORIO||{};
  const empresa = data.empresa||{};
  const tipos = _srvSortedEntries(data.servicos||{});
  const filiais = _srvSortedEntries(data.filiais||{});
  const vendedores = _srvSortedEntries(data.vendedores||{});

  const totalServ = Number(empresa.real_total||0);
  const totalQtd = Number(empresa.quantidade||0);
  const totalLinhas = Number(empresa.linhas||0);
  const tiposAtivos = tipos.length;

  const topTipo = tipos[0]||{};
  const topFil = filiais[0]||{};
  const topVend = vendedores[0]||{};

  const summary = `
    <div class="kpis" style="margin-bottom:14px">
      ${_srvMiniCard('🧰 Serviços no mês', R(totalServ), `${totalQtd.toLocaleString('pt-BR')} item(ns) · ${totalLinhas.toLocaleString('pt-BR')} linha(s)`)}
      ${_srvMiniCard('🏷️ Tipos de serviço', String(tiposAtivos), topTipo.servico?`Maior: ${esc(topTipo.servico)} · ${R(topTipo.real_total||0)}`:'')}
      ${_srvMiniCard('🏬 Melhor filial', topFil.label?esc(topFil.label):'—', topFil.real_total?`${R(topFil.real_total)} · ${Number(topFil.quantidade||0).toLocaleString('pt-BR')} item(ns)`:'')}
      ${_srvMiniCard('👤 Melhor vendedor', topVend.label?esc(topVend.label):'—', topVend.real_total?`${R(topVend.real_total)} · ${Number(topVend.quantidade||0).toLocaleString('pt-BR')} item(ns)`:'')}
    </div>`;

  const tipoCards = tipos.length ? `
    <div class="glass panel" style="margin-bottom:14px">
      <div class="section-head"><div><h2>🛠️ Serviços por tipo</h2><div class="hint">Totais consolidados por serviço do relatório mensal. Este é o valor oficial usado no card Serviços realizado.</div></div></div>
      <div class="grid-cards">${tipos.map(t=>`
        <div class="glass card" style="padding:14px 16px">
          <div class="title">${esc(t.servico||'-')}</div>
          <div class="numbers" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)">
            <div class="stat-box"><div class="mini">Quantidade</div><div class="big" style="font-size:18px">${Number(t.quantidade||0).toLocaleString('pt-BR')}</div></div>
            <div class="stat-box"><div class="mini">Total</div><div class="big" style="font-size:18px;color:var(--green)">${R(t.real_total||0)}</div></div>
          </div>
          <div class="legend-inline"><span><i class="dot" style="background:#f59e0b"></i>${Number(t.linhas||0).toLocaleString('pt-BR')} lançamento(s)</span></div>
        </div>`).join('')}</div>
    </div>` : `<div class="empty">Nenhum serviço encontrado no relatório.</div>`;

  const rankings = `
    <div class="grid-2">
      <div class="glass panel">
        <div class="section-head"><div><h2>🏬 Ranking por filial</h2><div class="hint">Top filiais em serviços do mês.</div></div></div>
        <div class="logs-list">${_srvRankRows(filiais.slice(0,20), 'filial')}</div>
      </div>
      <div class="glass panel">
        <div class="section-head"><div><h2>👤 Ranking por vendedor</h2><div class="hint">Top vendedores em serviços do mês.</div></div></div>
        <div class="logs-list">${_srvRankRows(vendedores.slice(0,20), 'vendedor')}</div>
      </div>
    </div>`;

  const host = servicesSection;
  if(!host) return;
  host.innerHTML = summary + tipoCards + rankings;

  if(isViewer){
    host.classList.remove('hidden');
  }
}

function setMainTab(tab){const isDiretor=usuarioAtual?.tipo==='master' && usuarioAtual?.roleLabel==='Diretor Comercial';if(isDiretor && ['cobrancas','senhas'].includes(tab)){tab='vendedores';}mainTab=tab;document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active',t.dataset.tab===tab));detailScreen.classList.add('hidden');document.getElementById('mainScreen').classList.remove('hidden');const hiddenMain=['metas','servicos','cobrancas','avisos','senhas','historico'].includes(tab);listSection.classList.toggle('hidden',hiddenMain);metaSection.classList.toggle('hidden',tab!=='metas');servicesSection.classList.toggle('hidden',tab!=='servicos');logSection.classList.toggle('hidden',tab!=='cobrancas');avisosSection.classList.toggle('hidden',tab!=='avisos');senhasSection.classList.toggle('hidden',tab!=='senhas');histSection.classList.toggle('hidden',tab!=='historico');mainFilters.classList.toggle('hidden',hiddenMain);if(tab==='vendedores'||tab==='filiais'){renderFilters();renderList()} if(tab==='metas') renderMetasTab(); if(tab==='servicos') renderServicosTab(false); if(tab==='cobrancas') renderLogsTab(); if(tab==='avisos') renderAvisosTab(); if(tab==='senhas') renderSenhasTab(); if(tab==='historico') renderHistoricoTab();}
function renderFilters(){if(mainTab!=='vendedores'&&mainTab!=='filiais'){mainFilters.innerHTML='';return} let html=`<button class="pill ${filtroFilial==='TODAS'?'active':''}" onclick="setFiltroFilial('TODAS')">Todas</button>`; ORDEM.forEach(f=>{html+=`<button class="pill ${filtroFilial===f?'active':''}" onclick="setFiltroFilial('${f}')">${f}</button>`}); mainFilters.innerHTML=html;}
function setFiltroFilial(f){filtroFilial=f;renderFilters();renderList()}
function currentEntities(){let arr=mainTab==='filiais'?flattenFiliais():flattenVendedores(); if(mainTab==='vendedores' && usuarioAtual?.tipo==='master'){const t=thirdChargeEntity(); const hasThird=Number(t.pendente||0)>0 || Number(t.pago||0)>0 || Number(t.grave_pend||0)>0 || Number(t.alerta_pend||0)>0 || Number(t.atencao_pend||0)>0; if(hasThird) arr=[t,...arr]; const creds=crediaristaEntities().filter(x=>Number(x.pendente||0)>0||Number(x.pago||0)>0); if(creds.length) arr=[...creds,...arr]} return arr.filter(x=>filtroFilial==='TODAS'||x.filial===filtroFilial || x.is_terceiro || x.is_crediarista)}
function renderEntityCard(ent){const m=calcMeta(ent); const isThird=!!(ent?.is_terceiro || ent?.type==='terceiro'); const isCred=!!(ent?.is_crediarista || ent?.type==='crediarista'); if(isThird || isCred){const credLogin=String(ent.login||crediaristaLoginByFilial(ent.filial)||'').toLowerCase(); const credFilial=String(ent.filial||'').toUpperCase(); const credNome=String(ent.nome||`CREDIARISTA${credFilial}`); const label=isThird?'Cobrança terceiro':'Crediarista'; const sub=isThird?'Clique para abrir a carteira terceirizada':'Clique para abrir a carteira do crediarista'; const actionAttr=isThird?`data-action="third-card" role="button" tabindex="0"`:`data-action="cred-card" data-login="${esc(credLogin)}" data-filial="${esc(credFilial)}" data-nome="${esc(credNome)}" role="button" tabindex="0"`; return `<div class="glass card ${m.geral>=50?'card-hit':(m.geral<30?'card-low-red':(m.geral<40?'card-low-orange':''))}" style="box-shadow:0 0 0 2px rgba(239,68,68,.12) inset" ${actionAttr}><div class="title">${esc(credNome)}</div><div class="numbers" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)"><div class="stat-box" style="min-width:0"><div class="mini">Pendente</div><div class="big" style="color:var(--red);font-size:15px;word-break:break-word">${R(ent.pendente||0)}</div></div><div class="stat-box" style="min-width:0"><div class="mini">Recebido</div><div class="big" style="color:var(--green);font-size:15px;word-break:break-word">${R(ent.pago||0)}</div></div></div><div class="meta-row"><div class="mini-chip">🔴 Grave ${pct(m.grave.perc)}</div><div class="mini-chip">🟠 Alerta ${pct(m.alerta.perc)}</div><div class="mini-chip">🟡 Atenção ${pct(m.atencao.perc)}</div><div class="mini-chip" style="font-size:12px">🔵 Meta geral ${pct(m.geral)}</div></div>${renderMascotStatus(m.geral,label)}<div class="legend-inline"><span><i class="dot" style="background:#2f67f6"></i>${sub}</span></div></div>`} const bonus=getBonus(m.cfg,m.geral);const sales=summarizeSalesCard(ent);const salesPct=sales?.n||0;const salesBorder=salesPct>=100?'box-shadow:0 0 0 2px rgba(242,201,76,.35) inset':salesPct>=80?'box-shadow:0 0 0 2px rgba(34,197,94,.18) inset':salesPct>=50?'box-shadow:0 0 0 2px rgba(249,115,22,.18) inset':'box-shadow:0 0 0 2px rgba(239,68,68,.12) inset';const cls=m.geral>=50?'card-hit':(m.geral<30?'card-low-red':(m.geral<40?'card-low-orange':''));const pulseNote=m.geral>=50?'<div class="legend-inline"><span><i class="dot" style="background:#2f67f6"></i>Meta atingida no mês</span></div>':'';return `<div class="glass card ${cls}" style="${salesBorder}" onclick='openEntity(${JSON.stringify({type:ent.type,filial:ent.filial,nome:ent.nome})})'><div class="title">${esc(ent.nome)} ${ent.type==='vendedor'?`(${ent.filial})`:''}</div><div class="numbers" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)"><div class="stat-box" style="min-width:0"><div class="mini">Pendente</div><div class="big" style="color:var(--red);font-size:15px;word-break:break-word">${R(ent.pendente||0)}</div></div><div class="stat-box" style="min-width:0"><div class="mini">Recebido</div><div class="big" style="color:var(--green);font-size:15px;word-break:break-word">${R(ent.pago||0)}</div></div></div><div class="meta-row"><div class="mini-chip">🔴 Grave ${pct(m.grave.perc)}</div><div class="mini-chip">🟠 Alerta ${pct(m.alerta.perc)}</div><div class="mini-chip">🟡 Atenção ${pct(m.atencao.perc)}</div><div class="mini-chip" style="font-size:12px">🔵 Meta geral ${pct(m.geral)}</div></div>${renderSalesCardSummary(ent)}${renderDualMascotStatus(ent)}${bonus?`<div class="legend-inline"><span><i class="dot" style="background:#2f67f6"></i>${esc(bonus.text)}</span></div>`:''}${pulseNote}</div>`}
function renderGroupBars(entities){if(!entities.length) return `<div class="empty">Nenhum dado para exibir.</div>`; const max=Math.max(1,...entities.map(e=>Math.max(Number(e.grave_pend||0),Number(e.alerta_pend||0),Number(e.atencao_pend||0),Number(e.pago||0)))); return `<div class="glass big-chart-card"><div class="section-head"><div><h2>📊 Panorama por ${mainTab==='filiais'?'filial':'vendedor'}</h2><div class="hint">Barras por faixa: Grave, Alerta, Atenção e Recebido</div></div><div class="legend-inline"><span><i class="dot" style="background:var(--red)"></i>Grave</span><span><i class="dot" style="background:var(--orange)"></i>Alerta</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção</span><span><i class="dot" style="background:var(--green)"></i>Recebido</span></div></div><div class="groupbars">${entities.map(e=>{const vals=[{c:'var(--red)',v:Number(e.grave_pend||0),t:'Grave'},{c:'var(--orange)',v:Number(e.alerta_pend||0),t:'Alerta'},{c:'var(--yellow)',v:Number(e.atencao_pend||0),t:'Atenção'},{c:'var(--green)',v:Number(e.pago||0),t:'Recebido'}]; return `<div class="group"><div class="bars">${vals.map(v=>`<div title="${v.t}: ${R(v.v)}" class="bar" style="height:${Math.max(12,(v.v/max)*240)}px;background:linear-gradient(180deg,${v.c},${v.c})"></div>`).join('')}<span class="wave one"></span><span class="wave two"></span><span class="bubble b1"></span><span class="bubble b2"></span><span class="bubble b3"></span></div><div class="glabel">${esc(trunc(e.nome,16))}</div></div>`}).join('')}</div><div class="axis"><span>Escala relativa automática</span><span>${entities.length} ${mainTab==='filiais'?'filiais':'colaboradores'}</span></div></div>`}

function renderNoChargeAlerts(){
  const hoje=(new Date()).toISOString().slice(0,10);
  const entries=flattenVendedores().map(v=>{
    const pending=((CLIENTES_VEND[v.nome]?.grave||[]).length+(CLIENTES_VEND[v.nome]?.alerta||[]).length+(CLIENTES_VEND[v.nome]?.atencao||[]).length);
    const done=(COB_LOGS||[]).filter(x=>String(x.usuario||'')===String(v.nome||'') && String(x.server_time||'').slice(0,10)===hoje).length;
    return {...v,pending,done};
  }).filter(x=>x.pending>0 && x.done===0);
  if(!entries.length) return '';
  return `<div class="glass panel" style="margin-bottom:16px;padding:14px 18px"><div class="section-head" style="margin:0"><div><h2 style="margin:0;font-size:18px">⏰ Sem cobranças hoje</h2><div class="hint">Aviso preventivo para o Master sobre quem ainda não cobrou hoje.</div></div></div><div class="legend-inline">${entries.slice(0,12).map(e=>`<span><i class="dot" style="background:#ef4444"></i>${esc(e.nome)} · ${e.pending} clientes</span>`).join('')}</div></div>`;
}

function renderHighlights(){const cobrarParts=[]; const vendasParts=[]; const filiais=flattenFiliais(); const vendedores=flattenVendedores(); const calcDelta=(e)=>{const delta=Number(e.var_pago_delta||0); const prev=Math.max(Math.abs(Number(e.pago||0)-delta),1); const perc=(Math.abs(delta)/prev)*100; return {delta,perc};}; const bestFil=filiais.slice().sort((a,b)=>Number(b.var_pago_delta||0)-Number(a.var_pago_delta||0))[0]; const bestVend=vendedores.slice().sort((a,b)=>Number(b.var_pago_delta||0)-Number(a.var_pago_delta||0))[0]; if(bestFil){const d=calcDelta(bestFil); cobrarParts.push(`<div class="glass panel highlight-pulse" style="margin-bottom:12px;padding:16px 18px"><div class="section-head" style="margin:0"><div><h2 style="margin:0;font-size:20px">🏆 Destaque da semana · Filial</h2><div class="hint">${esc(filialLabel(bestFil.filial))} recebeu ${R(d.delta)} a mais</div></div>${renderDeltaPill(d.delta,d.perc)}</div></div>`);} if(bestVend){const d=calcDelta(bestVend); cobrarParts.push(`<div class="glass panel highlight-pulse" style="margin-bottom:16px;padding:16px 18px"><div class="section-head" style="margin:0"><div><h2 style="margin:0;font-size:20px">🥇 Destaque da semana · Vendedor</h2><div class="hint">${esc(bestVend.nome)} recebeu ${R(d.delta)} a mais</div></div>${renderDeltaPill(d.delta,d.perc)}</div></div>`);} const achievers=currentEntities().filter(e=>calcMeta(e).geral>=50); if(achievers.length){cobrarParts.push(`<div class="glass panel" style="margin-bottom:16px;padding:14px 18px"><div class="section-head" style="margin:0"><div><h2 style="margin:0;font-size:18px">🔔 Metas atingidas</h2><div class="hint">${achievers.length} colaboradores/filiais com meta alcançada</div></div></div><div class="legend-inline">${achievers.slice(0,10).map(e=>`<span><i class="dot" style="background:#2f67f6"></i>${esc(e.nome)} ${pct(calcMeta(e).geral)}</span>`).join('')}</div></div>`);} cobrarParts.push(renderNoChargeAlerts());
const topVendaVend=bestLiveSalesEntity(vendedores,'venda_filial_vendedor_meta'); const topServVend=bestLiveSalesEntity(vendedores,'servico_filial_vendedor_ouro_fob'); const topVendaFil=bestLiveSalesEntity(filiais,'venda_filial_meta'); const topServFil=bestLiveSalesEntity(filiais,'servico_filial_ouro_fob');
vendasParts.push(`<div class="glass panel sales-panel" style="margin-bottom:16px;padding:16px 18px"><div class="section-head" style="margin:0 0 10px"><div><h2 style="margin:0;font-size:20px">💲 Mural de vendas do dia</h2><div class="hint">Comparativos atuais de venda e serviço do dia/semana.</div></div></div><div class="legend-inline">${topVendaVend?`<span><i class="dot" style="background:#f97316"></i>Venda vendedor: ${esc(topVendaVend.ent.nome)} ${R(topVendaVend.val||0)}</span>`:''}${topServVend?`<span><i class="dot" style="background:#f59e0b"></i>Serviço vendedor: ${esc(topServVend.ent.nome)} ${R(topServVend.val||0)}</span>`:''}${topVendaFil?`<span><i class="dot" style="background:#fb923c"></i>Venda filial: ${esc(filialLabel(topVendaFil.ent.filial))} ${R(topVendaFil.val||0)}</span>`:''}${topServFil?`<span><i class="dot" style="background:#fdba74"></i>Serviço filial: ${esc(filialLabel(topServFil.ent.filial))} ${R(topServFil.val||0)}</span>`:''}</div></div>`);
return `<div class="section-head" style="margin-bottom:8px"><div><h2>📌 Mural de cobrança</h2><div class="hint">Notificações e destaques do dia da cobrança.</div></div></div>${cobrarParts.join('')}<div class="section-head" style="margin:20px 0 8px"><div><h2>💲 Mural de vendas</h2><div class="hint">Comparativos de venda e serviço do dia/semana.</div></div></div>${vendasParts.join('')}`}

function bindSpecialCards(){document.querySelectorAll('[data-action="cred-card"]').forEach(el=>{el.style.cursor='pointer';el.onclick=(ev)=>{ev.preventDefault();ev.stopPropagation();const node=ev.currentTarget.closest('[data-action="cred-card"]')||ev.currentTarget;const ds=node.dataset||{};openCrediaristaPanel(ds.login||'',ds.filial||'',ds.nome||'');return false};el.onkeydown=(ev)=>{if(ev.key==='Enter' || ev.key===' '){ev.preventDefault();const node=ev.currentTarget.closest('[data-action="cred-card"]')||ev.currentTarget;const ds=node.dataset||{};openCrediaristaPanel(ds.login||'',ds.filial||'',ds.nome||'')}}});document.querySelectorAll('[data-action="third-card"]').forEach(el=>{el.style.cursor='pointer';el.onclick=(ev)=>{ev.preventDefault();ev.stopPropagation();openThirdChargePanel();return false};el.onkeydown=(ev)=>{if(ev.key==='Enter' || ev.key===' '){ev.preventDefault();openThirdChargePanel()}}})}
function renderList(){const entities=currentEntities();const title=mainTab==='filiais'?'🏬 Filiais':'👥 Colaboradores';const hint=`${entities.length} ${mainTab==='filiais'?'filiais':'colaboradores'} exibidos`; listSection.innerHTML=`${renderCampaignStrip()}${usuarioAtual?.tipo==='master'?renderHighlights():''}<div class="section-head"><div><h2>${title}</h2><div class="hint">Clique em qualquer card para abrir a tela individual completa.</div></div><div class="hint">${hint}</div></div><div class="grid-cards">${entities.map(renderEntityCard).join('')}</div>${renderGroupBars(entities)}`; bindSpecialCards()}
function findEntity(ref){const n=String(ref?.nome||'').toLowerCase(); const f=String(ref?.filial||'').toUpperCase(); const t=String(ref?.type||'').toLowerCase(); if(t==='terceiro' || ref?.is_terceiro || n===String(COBRANCA10_NOME).toLowerCase() || n===String(COBRANCA10_LOGIN).toLowerCase() || f==='FTER'){return thirdChargeEntity()} if(t==='crediarista' || ref?.is_crediarista || n.startsWith('crediarista') || String(ref?.login||'').toLowerCase().startsWith('crediaristaf')){return crediaristaEntityByLogin(ref?.login||ref?.nome||ref?.filial)} if(ref.type==='filial'){return flattenFiliais().find(x=>x.filial===ref.filial)} return flattenVendedores().find(x=>x.filial===ref.filial && x.nome===ref.nome)}
function renderTerceiroCommission(ent){const isCred=!!(ent?.is_crediarista||ent?.type==='crediarista'); const baseCfg=isCred?entityConfig({type:'vendedor',nome:ent.nome,filial:ent.filial}):entityConfig({type:'vendedor',nome:COBRANCA10_NOME,filial:'FTER'}); const cfg=commissionCfg(baseCfg); const policy=(isCred?(cfg.camp_cob_crediarista||[]):(cfg.camp_cobranca_terceiro||[])); const policyOk=Array.isArray(policy)&&policy.length?policy:(isCred?defaultCampCrediarista():defaultCampTerceiro()); const byFaixa={atencao:{pct:0,cobrado:0,recebido:0,comissao:0},alerta:{pct:0,cobrado:0,recebido:0,comissao:0},grave:{pct:0,cobrado:0,recebido:0,comissao:0}}; policyOk.forEach(r=>{const fx=String(r.faixa||'').toLowerCase(); if(byFaixa[fx]) byFaixa[fx].pct=Number(String(r.pct||0).replace(',','.'))||0}); const mesAtual=new Date().toISOString().slice(0,7); const userKeys=isCred?[String(ent.login||'').toLowerCase(),String(ent.nome||'').toLowerCase()]:[COBRANCA10_NOME.toLowerCase(),COBRANCA10_LOGIN]; const cobrados=(COB_LOGS||[]).filter(x=>userKeys.includes(String(x.usuario||'').toLowerCase()) && String(x.server_time||'').slice(0,7)===mesAtual); const keys=new Set(cobrados.map(x=>cobrancaRowKey(x))); const srcCli=isCred?(CLIENTES_CREDIARISTA?.[String(ent.login||'').toLowerCase()]||{grave:[],alerta:[],atencao:[]}):(CLIENTES_TERCEIRO||{grave:[],alerta:[],atencao:[]}); const srcRec=isCred?(RECEBIMENTOS_CREDIARISTA?.[String(ent.login||'').toLowerCase()]||{grave:[],alerta:[],atencao:[]}):(RECEBIMENTOS_TERCEIRO||{grave:[],alerta:[],atencao:[]}); ['atencao','alerta','grave'].forEach(fx=>{byFaixa[fx].cobrado=(srcCli?.[fx]||[]).filter(r=>keys.has(cobrancaRowKey(r))).length; (srcRec?.[fx]||[]).forEach(r=>{const pagMes=String(parseDateBR(r.pagamento)||new Date()).slice(0,7); if(keys.has(cobrancaRowKey(r)) && pagMes===mesAtual){byFaixa[fx].recebido+=Number(r.pago||0)}}); byFaixa[fx].comissao=byFaixa[fx].recebido*(byFaixa[fx].pct/100)}); const total=Object.values(byFaixa).reduce((a,b)=>a+b.comissao,0); const item=(t,v,s='')=>`<div class="commission-item unlocked ${s}"><div class="k">${t}</div><div class="v">${v}</div></div>`; return `<div class="glass panel commission-card"><h3>💵 ${isCred?'Comissão crediarista':'Comissão cobrança terceiro'} <span class="note">· mês atual / pagamento dia 10 do próximo mês</span></h3><div class="commission-grid">${item('Atenção %',String(byFaixa.atencao.pct.toFixed(2)).replace('.',',')+'%')}${item('Alerta %',String(byFaixa.alerta.pct.toFixed(2)).replace('.',',')+'%')}${item('Grave %',String(byFaixa.grave.pct.toFixed(2)).replace('.',',')+'%')}${item('Recebido atenção',R(byFaixa.atencao.recebido||0))}${item('Recebido alerta',R(byFaixa.alerta.recebido||0))}${item('Recebido grave',R(byFaixa.grave.recebido||0))}${item('Comissão atenção',R(byFaixa.atencao.comissao||0))}${item('Comissão alerta',R(byFaixa.alerta.comissao||0))}${item('Comissão grave',R(byFaixa.grave.comissao||0))}${item('Total previsto',R(total||0),'total-final')}</div><div class="commission-note">A comissão reinicia a cada mês e o pagamento é previsto para o dia 10 do mês seguinte.</div></div>`}
function openCrediaristaPanel(login, filial, nome){
  const filialNorm=String(filial||'').toUpperCase();
  const loginNorm=String(login||crediaristaLoginByFilial(filialNorm)||'').toLowerCase();
  const nomeNorm=String(nome||`CREDIARISTA${filialNorm}`);
  // Carteira: usa CLIENTES_CREDIARISTA (Python já espelhou a base da filial)
  const src=(CLIENTES_CREDIARISTA?.[loginNorm])||CLIENTES_FIL?.[filialNorm]||{grave:[],alerta:[],atencao:[]};
  const rsrc=(RECEBIMENTOS_CREDIARISTA?.[loginNorm])||{grave:[],alerta:[],atencao:[]};
  const pend=[...(src.grave||[]),...(src.alerta||[]),...(src.atencao||[])].reduce((a,b)=>a+Number(b.pendente||0),0);
  const rec=[...(rsrc.grave||[]),...(rsrc.alerta||[]),...(rsrc.atencao||[])].reduce((a,b)=>a+Number(b.pago||0),0);
  // Herda dados de meta da filial para que calcMeta() funcione corretamente
  const filData=FILIAIS?.[filialNorm]||{};
  const ent={
    type:'crediarista',login:loginNorm,filial:filialNorm,nome:nomeNorm,
    is_crediarista:true,only_cobranca:true,
    pendente:pend,pago:rec,total:pend+rec,perc_filial:100,
    // campos de meta herdados da filial espelhada
    grave_pend:  Number(filData.grave_pend  ||0),
    alerta_pend: Number(filData.alerta_pend ||0),
    atencao_pend:Number(filData.atencao_pend||0),
    grave_rec:   Number(filData.grave_rec   ||0),
    alerta_rec:  Number(filData.alerta_rec  ||0),
    atencao_rec: Number(filData.atencao_rec ||0),
    grave_alvo:  Number(filData.grave_alvo  ||0),
    alerta_alvo: Number(filData.alerta_alvo ||0),
    atencao_alvo:Number(filData.atencao_alvo||0),
    grave_perc:  Number(filData.grave_perc  ||0),
    alerta_perc: Number(filData.alerta_perc ||0),
    atencao_perc:Number(filData.atencao_perc||0),
    perc_meta:   Number(filData.perc_meta   ||0),
  };
  currentDetailRef={type:'crediarista',filial:filialNorm,nome:nomeNorm,login:loginNorm};
  mascotCongrats(ent);
  document.getElementById('mainScreen').classList.add('hidden');
  detailScreen.classList.remove('hidden');
  return renderCrediaristaDetail(ent);
}
function openThirdChargePanel(){const ent=thirdChargeEntity(); currentDetailRef={type:'terceiro',filial:'FTER',nome:ent.nome}; mascotCongrats(ent); document.getElementById('mainScreen').classList.add('hidden'); detailScreen.classList.remove('hidden'); renderTerceiroDetail(ent)}

// Clique blindado dos cards especiais: não depende de onclick inline.
document.addEventListener('click', function(ev){
  const cred = ev.target.closest('[data-action="cred-card"]');
  if(cred){
    ev.preventDefault();
    ev.stopPropagation();
    openCrediaristaPanel(cred.dataset.login||'', cred.dataset.filial||'', cred.dataset.nome||'');
    return false;
  }
  const third = ev.target.closest('[data-action="third-card"]');
  if(third){
    ev.preventDefault();
    ev.stopPropagation();
    openThirdChargePanel();
    return false;
  }
}, true);

window.openCrediaristaPanel=openCrediaristaPanel;
window.openThirdChargePanel=openThirdChargePanel;

function renderTerceiroDetail(ent){const src=getClientesEnt(ent); const totalTit=(src.grave?.length||0)+(src.alerta?.length||0)+(src.atencao?.length||0); detailScreen.innerHTML=`<div class="back-row"><button class="btn soft" onclick="backToMain()">⬅️ Voltar</button><div><h2>${esc(ent.nome)}</h2><div class="sub">${ent.is_crediarista?`Painel de cobrança espelhado da filial ${ent.filial} · mesma base do gerente/filial`:`Painel de cobrança terceirizada · percentual global sem duplicidade`}</div></div><div class="badge">${ent.is_crediarista?'🧾 Crediarista':'🤝 Cobrança terceiro'}</div></div><div class="detail-top"><div class="glass panel"><h3>🧾 Resumo da carteira</h3><div class="metrics-grid"><div class="metric"><div class="k">Títulos</div><div class="v">${totalTit}</div></div><div class="metric"><div class="k">Pendente</div><div class="v" style="color:var(--red)">${R(ent.pendente||0)}</div></div><div class="metric"><div class="k">Recebido</div><div class="v" style="color:var(--green)">${R(ent.pago||0)}</div></div><div class="metric"><div class="k">Cobrado hoje</div><div class="v">${getCobradosHoje(ent).length}</div></div></div><div class="legend-inline" style="margin-top:12px"><span><i class="dot" style="background:var(--red)"></i>Grave ${src.grave?.length||0}</span><span><i class="dot" style="background:var(--orange)"></i>Alerta ${src.alerta?.length||0}</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção ${src.atencao?.length||0}</span></div></div><div>${renderTerceiroCommission(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">💰 Recebimentos por faixa <span>clique para abrir</span></div><div class="acc-body">${renderRecebimentos(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">🧾 Relatório de cobranças <span>clique para abrir</span></div><div class="acc-body">${renderCobrancasEnt(ent)}</div></div>`}

// ── PAINEL CREDIARISTA ─────────────────────────────────────────────────────
// Mostra: resumo da carteira espelhada + meta de cobrança + recebimentos + cobranças
// NÃO mostra: painel de vendas, comissão mercantil, campanhas de venda
function renderCrediaristaDetail(ent){
  const src=getClientesEnt(ent);
  const totalTit=(src.grave?.length||0)+(src.alerta?.length||0)+(src.atencao?.length||0);
  const meta=calcMeta(ent);
  detailScreen.innerHTML=`
    ${renderInboxBanner()}
    <div class="back-row">
      <button class="btn soft" onclick="backToMain()">⬅️ Voltar</button>
      <div>
        <h2>${esc(ent.nome)}</h2>
        <div class="sub">Painel de cobrança espelhado da filial ${esc(ent.filial)} · mesma base do gerente/filial em tempo real</div>
      </div>
      <div class="badge">🧾 Crediarista</div>
    </div>
    <div class="detail-top">
      <div class="glass panel">
        <h3>🎯 Meta de cobrança <span class="note">· espelhada da filial</span></h3>
        <div class="mega-progress">
          <div class="ring-wrap">${renderPiggyBank(meta.geral)}</div>
          <div>
            <div class="metrics-grid">
              <div class="metric"><div class="k">Títulos na carteira</div><div class="v">${totalTit}</div></div>
              <div class="metric"><div class="k">Pendente total</div><div class="v" style="color:var(--red)">${R(ent.pendente||0)}</div></div>
              <div class="metric"><div class="k">Recebido</div><div class="v" style="color:var(--green)">${R(ent.pago||0)}</div></div>
              <div class="metric"><div class="k">Cobrado hoje</div><div class="v">${getCobradosHoje(ent).length}</div></div>
            </div>
            <div class="legend-inline" style="margin-top:12px">
              <span><i class="dot" style="background:var(--red)"></i>Grave ${src.grave?.length||0} títulos</span>
              <span><i class="dot" style="background:var(--orange)"></i>Alerta ${src.alerta?.length||0} títulos</span>
              <span><i class="dot" style="background:var(--yellow)"></i>Atenção ${src.atencao?.length||0} títulos</span>
            </div>
          </div>
        </div>
        <div class="meta-grid">
          ${renderMetaBox('Grave','var(--red)',meta.grave)}
          ${renderMetaBox('Alerta','var(--orange)',meta.alerta)}
          ${renderMetaBox('Atenção','var(--yellow)',meta.atencao)}
          ${renderMetaBox('Meta geral','var(--blue)',{perc:meta.geral,alvo:meta.grave.alvo+meta.alerta.alvo+meta.atencao.alvo,rec:meta.grave.rec+meta.alerta.rec+meta.atencao.rec})}
        </div>
        <div style="margin-top:14px">${renderMascotStatus(meta.geral,'Cobrança')}</div>
      </div>
      <div>${renderTerceiroCommission(ent)}</div>
    </div>
    <div class="accordion">
      <div class="acc-head" onclick="toggleAcc(this)">💰 Recebimentos por faixa <span>clique para abrir</span></div>
      <div class="acc-body">${renderRecebimentos(ent)}</div>
    </div>
    <div class="accordion">
      <div class="acc-head" onclick="toggleAcc(this)">🧾 Relatório de cobranças <span>clique para abrir</span></div>
      <div class="acc-body">${renderCobrancasEnt(ent)}</div>
    </div>
  `;
}

function openEntity(ref){if(ref && (ref.type==='crediarista' || ref.is_crediarista)){return openCrediaristaPanel(ref.login||'', ref.filial||'', ref.nome||'')} const ent=findEntity(ref); if(!ent) return; currentDetailRef={type:ent.type,filial:ent.filial,nome:ent.nome,login:ent.login||''}; mascotCongrats(ent); document.getElementById('mainScreen').classList.add('hidden'); detailScreen.classList.remove('hidden'); if(ent.is_terceiro || ent.type==='terceiro'){return renderTerceiroDetail(ent)} if(ent.is_crediarista || ent.type==='crediarista'){return openCrediaristaPanel(ent.login||'', ent.filial||'', ent.nome||'')} const meta=calcMeta(ent); const bonus=getBonus(meta.cfg,meta.geral); const deltaVal=Number(ent.var_pago_delta||0); const prevBase=Math.max(Math.abs(Number(ent.pago||0)-deltaVal),1); const pctFallback=(Math.abs(deltaVal)/prevBase)*100; const compPerc=(ent.var_pago_perc==null || Math.abs(Number(ent.var_pago_perc||0))<0.01)?pctFallback:Math.abs(Number(ent.var_pago_perc||0)); detailScreen.innerHTML=`${usuarioAtual && usuarioAtual.tipo!=='master' ? renderInboxBanner() : ''}<div class="back-row"><button class="btn soft" onclick="backToMain()">⬅️ Voltar</button><div><h2>${ent.type==='filial'?filialLabel(ent.filial):esc(ent.nome)}</h2><div class="sub">${ent.type==='filial'?'Painel individual da filial':'Painel individual do vendedor'} · ${ent.filial}</div></div><div class="badge">${ent.type==='filial'?'🏬 Filial':'👤 Vendedor'}</div></div><div class="detail-top"><div class="glass panel"><h3>🎯 Meta do mês <span class="note">· Não acumulativo</span></h3><div class="mega-progress"><div class="ring-wrap">${renderPiggyBank(meta.geral)}</div><div><div class="metrics-grid"><div class="metric"><div class="k">Pendente</div><div class="v" style="color:var(--red)">${R(ent.pendente||0)}</div></div><div class="metric"><div class="k">Recebido</div><div class="v" style="color:var(--green)">${R(ent.pago||0)}</div></div><div class="metric"><div class="k">% da filial</div><div class="v">${pct(ent.perc_filial||100)}</div></div><div class="metric"><div class="k">Configuração usada</div><div class="v">${Number(meta.cfg.grave_pct||0)}/${Number(meta.cfg.alerta_pct||0)}/${Number(meta.cfg.atencao_pct||0)}</div></div><div class="metric"><div class="k">Comparado a ontem</div><div class="v" style="font-size:16px">${renderDeltaPill(ent.var_pago_delta,compPerc)} <span>${R(Math.abs(Number(ent.var_pago_delta||0)))}</span></div></div></div><div class="legend-inline" style="margin-top:12px"><span><i class="dot" style="background:var(--red)"></i>Grave alvo ${R(meta.grave.alvo)} · recebido ${R(meta.grave.rec)}</span><span><i class="dot" style="background:var(--orange)"></i>Alerta alvo ${R(meta.alerta.alvo)} · recebido ${R(meta.alerta.rec)}</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção alvo ${R(meta.atencao.alvo)} · recebido ${R(meta.atencao.rec)}</span></div></div></div><div class="meta-grid">${renderMetaBox('Grave','var(--red)',meta.grave)}${renderMetaBox('Alerta','var(--orange)',meta.alerta)}${renderMetaBox('Atenção','var(--yellow)',meta.atencao)}${renderMetaBox('Meta geral','var(--blue)',{perc:meta.geral,alvo:meta.grave.alvo+meta.alerta.alvo+meta.atencao.alvo,rec:meta.grave.rec+meta.alerta.rec+meta.atencao.rec})}</div><div style="height:18px"></div><h3>🌊 Gráfico Geral Contas a Receber</h3>${renderSingleBars(ent,meta,true)}<div style="height:16px"></div><div class="glass panel"><h3>🏆 Bônus e premiações <span class="note">· Não acumulativo</span></h3>${renderBonusBox(meta.cfg,meta.geral)}</div></div><div>${renderSalesPanel(ent)}<div style="height:16px"></div>${renderCommissionSummary(ent)}<div style="height:16px"></div>${renderCampaignSummary(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">💰 Recebimentos por faixa <span>clique para ${'abrir'}</span></div><div class="acc-body">${renderRecebimentos(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">🧾 Relatório de cobranças <span>clique para ${'abrir'}</span></div><div class="acc-body">${renderCobrancasEnt(ent)}</div></div>`}
function renderCommissionSummary(ent){
  const c=calcCommissionSummary(ent);
  const totalLiberado = c.elegivelMercantil && c.elegivelServicos;
  const totalExibido = totalLiberado ? c.totalPrevisto : 0;
  const moneyCell=(title,val,locked=false,extra='')=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''} ${extra}"><div class="k">${title}</div><div class="v">${R(val||0)}</div></div>`;
  const pctCell=(title,val,locked=false)=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''}"><div class="k">${title}</div><div class="v">${String(Number(val||0).toFixed(2)).replace('.',',')}%</div></div>`;
  const rentNote = c.rentUnlocked
    ? `Rentabilidade atual ${String(Number(c.rentAtual||0).toFixed(2)).replace('.',',')}% · faixa aplicada ${c.rentFaixaTxt}.`
    : `Rentabilidade atual ${String(Number(c.rentAtual||0).toFixed(2)).replace('.',',')}% · bloqueada até bater 50% da meta de cobrança.`;
  return `<div class="glass panel commission-card"><h3>💵 Comissionamento previsto <span class="note">· calculado pela política salva</span></h3>${c.metaAtingida?`<div class="meta-hit-banner"><img src="${LARANJITO}" alt=""><span>Meta liberada! O Laranjito está comemorando sua liberação de comissão/bonus.</span></div>`:''}<div class="commission-grid">${`<div class="commission-item unlocked"><div class="k">Faixa aplicada</div><div class="v" style="font-size:16px">${esc(c.faixaTxt)}</div></div>`}${pctCell('% comissão mercantil',c.comPerc,!c.elegivelMercantil)}${pctCell('% serviços',c.servPct,!c.elegivelServicos)}${pctCell('% caminhão',c.camPct,!c.elegivelServicos)}${moneyCell('Comissão vendas',c.vendasComissao,!c.elegivelMercantil)}${moneyCell('Comissão serviços',c.servicosComissao,!c.elegivelServicos)}${moneyCell('Comissão caminhão',c.caminhaoComissao,!c.elegivelServicos)}${moneyCell('Bônus por meta',c.bonusMeta,!c.bonusLiberado)}${moneyCell('Rentab 48%',c.rent48,!(c.rentUnlocked && c.rentAtual>=48))}${moneyCell('Rentab 52,15%',c.rent52,!(c.rentUnlocked && c.rentAtual>=52.15))}${moneyCell('Rentab 55,50%',c.rent55,!(c.rentUnlocked && c.rentAtual>=55.50))}${moneyCell('Total previsto',totalExibido,!totalLiberado,'total-final '+(!totalLiberado?'total-locked':''))}</div><div class="commission-note">Base mercantil bruta: ${R(c.vendaRealBruto||0)} · Caminhão abatido: ${R(c.camReal||0)} · Mercantil líquido para comissão: ${R(c.vendaReal||0)} · Serviço: ${R(c.servReal||0)}. Mínimo vendas ${pct(c.minVenda)} · mínimo serviços/caminhão ${pct(c.minServico)} · rentabilidades liberam ao bater 50% da meta de cobrança. ${rentNote}</div></div>`
}

function backToMain(){currentDetailRef=null; detailScreen.classList.add('hidden');document.getElementById('mainScreen').classList.remove('hidden')}
function renderMetaBox(title,color,obj){return `<div class="meta-card"><div class="meta-title">${title}</div><div class="meta-main" style="color:${color}">${pct(obj.perc||0)}</div><div class="meta-sub">Alvo: ${R(obj.alvo||0)}</div><div class="meta-sub">Recebido: ${R(obj.rec||0)}</div></div>`}
function normSalesText(s){return String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^A-Z0-9 ]/gi,' ').replace(/\s+/g,' ').trim().toUpperCase()}
function salesCell(row, keys){for(const k of keys){if(row && row[k]!=null && String(row[k]).trim()!=='') return String(row[k]).trim()} return ''}
function filialAliases(f){const raw=String(f||'').toUpperCase(); if(raw.includes('90')) return ['FILIAL 90/99','FILIAL 90','90/99','DEPOSITO MOVEIS','DEPOSITO']; const n=parseInt((raw.match(/\d+/)||[''])[0]||'0',10); if(!n) return [raw]; const two=String(n).padStart(2,'0'); return [`FILIAL ${two}`,`FILIAL ${n}`,`(${two})`,`(${n})`,`F${n}`]}

function servicosKeyNome(nome){
  return normSalesText(nome).replace(/\s+/g,' ').trim();
}
function servicosEntidade(ent){
  const out=[];
  const data=SERVICOS_RELATORIO||{};
  if(!ent) return out;
  if(ent.type==='filial'){
    const item=(data.filiais||{})[ent.filial]||{};
    Object.entries(item.servicos||{}).forEach(([servico,valor])=>{
      out.push({servico, real_total:Number(valor||0), quantidade:0});
    });
  }else{
    const vend=(data.vendedores||{});
    const key1=`${servicosKeyNome(ent.nome)}_${ent.filial}`;
    let item=vend[key1];
    if(!item){
      item=Object.values(vend).find(v=>{
        return String(v?.filial||'').toUpperCase()===String(ent.filial||'').toUpperCase()
          && servicosKeyNome(v?.nome||'')===servicosKeyNome(ent.nome||'');
      });
    }
    Object.entries((item&&item.servicos)||{}).forEach(([servico,valor])=>{
      out.push({servico, real_total:Number(valor||0), quantidade:0});
    });
  }
  return out.sort((a,b)=>Number(b.real_total||0)-Number(a.real_total||0));
}
function renderServicosEntidade(ent){
  const rows=servicosEntidade(ent).filter(x=>Number(x.real_total||0)>0);
  if(!rows.length){
    return `<div class="glass panel"><h3>🛠️ Serviços por tipo</h3><div class="empty">Nenhum serviço localizado para ${ent?.type==='filial'?'esta filial':'este vendedor'} no relatório mensal.</div></div>`;
  }
  const total=rows.reduce((a,b)=>a+Number(b.real_total||0),0);
  return `<div class="glass panel"><div class="section-head" style="margin:0 0 10px"><div><h3 style="margin:0">🛠️ Serviços por tipo</h3><div class="hint">Relatório real de serviços do mês atual · total oficial ${R(total)}</div></div></div><div class="metrics-grid">${rows.slice(0,8).map(r=>`<div class="metric"><div class="k">${esc(String(r.servico||'Serviço').slice(0,34))}</div><div class="v" style="color:var(--blue-400);font-size:18px">${R(r.real_total||0)}</div></div>`).join('')}</div></div>`;
}

function servicosEntidadeTotal(ent){
  return servicosEntidade(ent).reduce((acc,r)=>acc+Number(r.real_total||0),0);
}
function serviceOfficialOverride(ent,key,row){
  if(!String(key||'').includes('servico')) return null;
  const total=servicosEntidadeTotal(ent);
  if(!(total>0)) return null;
  const metaTotalStr=salesCell(row,['Meta (R$) Total','Meta(R$) Total']);
  const metaPeriodoStr=salesCell(row,['Meta (R$) Período','Meta(R$) Período']);
  const metaTotal=salesNum(metaTotalStr);
  const metaPeriodo=salesNum(metaPeriodoStr);
  return {
    total: total,
    realizado: R(total),
    atingidoTotal: metaTotal>0 ? pct(total/metaTotal*100) : '0%',
    atingidoPeriodo: metaPeriodo>0 ? pct(total/metaPeriodo*100) : '0%',
    nota: 'relatório serviços'
  };
}

function rowMatchesFilial(ent,row){const joined=normSalesText([salesCell(row,['Filial','Filial_2','Vendedor','Vendedor_2','Nome','Nome_2']),salesCell(row,['Subgrupo'])].join(' ')); return filialAliases(ent.filial).some(a=>joined.includes(normSalesText(a)))}
function vendedorNomeAlvo(row,key){if(key==='venda_filial_vendedor_meta' || key==='servico_filial_vendedor_ouro_fob') return salesCell(row,['Vendedor_2','Nome_2','Nome','Vendedor']); return salesCell(row,['Vendedor','Vendedor_2','Nome','Nome_2'])}
function fuzzyContainsAllTokens(target, query){const t=normSalesText(target); const q=normSalesText(query); const toks=q.split(' ').filter(x=>x && x.length>1); return toks.length ? toks.every(tok=>t.includes(tok)) : false}
function rowMatchesVendedor(ent,row,key=''){const vendedorCampo=vendedorNomeAlvo(row,key); const filialCampo=salesCell(row,['Filial','Filial_2','Vendedor']); const byNome = fuzzyContainsAllTokens(vendedorCampo, ent.nome) || fuzzyContainsAllTokens(ent.nome, vendedorCampo); const byFilial = !filialCampo || filialAliases(ent.filial).some(a=>normSalesText(filialCampo).includes(normSalesText(a))) || rowMatchesFilial(ent,row); return byNome && byFilial}
function getSalesRows(ent, key){const base=METAS_VENDAS?.metas?.[key]; if(!base || !base.ok) return []; const rows=Array.isArray(base.linhas)?base.linhas:[]; return rows.filter(r=>ent.type==='filial'?rowMatchesFilial(ent,r):rowMatchesVendedor(ent,r,key))}
function salesTitleForRow(ent,row,key=''){return salesCell(row, ent.type==='filial'?['Subgrupo','Filial','Vendedor_2','Vendedor']:['Subgrupo','Vendedor_2','Vendedor','Filial']) || (ent.type==='filial'?filialLabel(ent.filial):ent.nome)}
function salesPercentClass(v){const n=parseFloat(String(v||'').replace('%','').replace(',','.'))||0; if(n>=100) return 'gold'; if(n>=80) return 'good'; if(n>=50) return 'warn'; return 'low'}
function salesNum(v){return parseFloat(String(v||'').replace('%','').replace(/\./g,'').replace(',','.'))||0}
function renderSalesProgress(v){const n=Math.max(0,Math.min(160,salesNum(v))); return `<div class="sales-progress"><span style="width:${Math.min(n,100)}%"></span></div><div class="sales-progress-label">${String(v||'0%')}</div>`}
function renderSalesMini(k,v,kind='',showMascot=false,wrap=false){const cls=[kind, wrap?'wrap':'']; if(kind==='atingido'||kind==='projetado') cls.push(salesPercentClass(v)); return `<div class="sales-mini ${cls.join(' ')}">${showMascot?`<img src="${LARANJITO}" class="laranjito-mini" alt="">`:''}<div class="k">${k}</div><div class="v">${v||'-'}</div>${(kind==='atingido')?renderSalesProgress(v):''}</div>`}
function renderSalesRows(ent, key, label){
  let rows=getSalesRows(ent,key);
  if(!rows.length) return `<div class="sales-card"><h4>${label}</h4><div class="sales-empty">Sem dados desta meta para ${ent.type==='filial'?'esta filial':'este vendedor'}.</div></div>`;

  // Para SERVIÇOS, o realizado oficial vem do relatório real de serviços por tipo.
  // A meta do SGI permanece como alvo, mas os campos "Realizado" e "% atingido" passam a bater
  // exatamente com o painel "Serviços por tipo" da mesma filial/vendedor.
  if(String(key||'').includes('servico') && servicosEntidadeTotal(ent)>0){
    rows=[rows[0]];
  }

  return `<div class="sales-card"><h4>${label}</h4><div class="sales-list">${rows.map(r=>{
    const srv=serviceOfficialOverride(ent,key,r);
    const ating=srv ? srv.atingidoTotal : salesCell(r,['Atingido Total']);
    const atingPeriodo=srv ? srv.atingidoPeriodo : salesCell(r,['Atingido Período']);
    const realizadoTotal=srv ? srv.realizado : esc(salesCell(r,['Realizado (R$) Total','Realizado(R$) Total']));
    const realizadoPeriodo=srv ? srv.realizado : esc(salesCell(r,['Realizado (R$) Período','Realizado(R$) Período']));
    const proj=salesCell(r,['Projetado (R$)','Projetado(R$)']);
    const showMascot=(parseFloat(String(ating).replace('%','').replace(',','.'))||0)>=100;
    const title=srv ? `${salesTitleForRow(ent,r,key)} · relatório serviços` : salesTitleForRow(ent,r,key);
    return `<div class="sales-row"><div class="sales-row-title">${esc(title)}</div><div class="sales-metrics">${renderSalesMini('Meta total',esc(salesCell(r,['Meta (R$) Total','Meta(R$) Total'])),'meta')}${renderSalesMini('Realizado total',realizadoTotal,'realizado')}${renderSalesMini('Atingido total',esc(ating),'atingido',showMascot)}${renderSalesMini('Meta período',esc(salesCell(r,['Meta (R$) Período','Meta(R$) Período'])),'meta')}${renderSalesMini('Realizado período',realizadoPeriodo,'realizado')}${renderSalesMini('Atingido período',esc(atingPeriodo),'atingido')}${renderSalesMini('Projetado',esc(proj),'projetado',showMascot)}${renderSalesMini(ent.type==='filial'?'Filial':'Vendedor',esc(salesCell(r, ent.type==='filial'?['Filial']:['Vendedor_2','Vendedor'])),'realizado',false,true)}</div></div>`;
  }).join('')}</div></div>`;
}
function summarizeSalesCard(ent){const keys=ent.type==='filial'?['venda_filial_meta']:['venda_filial_vendedor_meta']; let best=null; keys.forEach(k=>{getSalesRows(ent,k).forEach(r=>{const ating=salesCell(r,['Atingido Total']); const n=parseFloat(String(ating).replace('%','').replace(',','.'))||0; if(!best || n>best.n){best={row:r,key:k,n};}})}); return best}
function renderSalesCardSummary(ent){const s=summarizeSalesCard(ent); if(!s) return ''; const row=s.row; const showMascot=s.n>=100; return `<div class="card-sales"><div class="card-sales-title">💲 Vendas e metas</div><div class="card-sales-grid">${renderSalesMini('Realizado total',esc(salesCell(row,['Realizado (R$) Total','Realizado(R$) Total'])),'realizado')}${renderSalesMini('Atingido total',esc(salesCell(row,['Atingido Total'])),'atingido',showMascot)}${renderSalesMini('Projetado',esc(salesCell(row,['Projetado (R$)','Projetado(R$)'])),'projetado',showMascot)}</div></div>`}
const MASCOTE_FELIZ='https://moveisdolar.com.br/colaborador/mascote%20feliz1.png';
const MASCOTE_PREOC='https://moveisdolar.com.br/colaborador/mascote%20preocupado1.png';
const MASCOTE_TRISTE='https://moveisdolar.com.br/colaborador/mascote%20triste1.png';
function mascotByPerc(p){const n=Number(p||0); if(n>=80) return {src:MASCOTE_FELIZ,txt:'Laranjito feliz: meta em ótimo ritmo!'}; if(n>=60) return {src:MASCOTE_PREOC,txt:'Laranjito preocupado: atenção para a meta.'}; return {src:MASCOTE_TRISTE,txt:'Laranjito triste: precisa reagir já!'} }
function renderMascotStatus(p,label=''){const m=mascotByPerc(p); return `<div class="mascot-status"><img src="${m.src}" alt=""><div><strong>${label?label+': ':''}${m.txt}</strong></div></div>`}
function renderDualMascotStatus(ent){const metaCob=calcMeta(ent).geral||0; if(ent?.is_terceiro || ent?.type==='terceiro'){return `<div>${renderMascotStatus(metaCob,'Cobrança terceiro')}</div>`} const vendaRow=(getSalesRows(ent, ent.type==='filial'?'venda_filial_meta':'venda_filial_vendedor_meta')[0])||null; const vendaPerc=salesNum(salesCell(vendaRow,['Atingido Total'])); return `<div>${renderMascotStatus(metaCob,'Cobrança')}${renderMascotStatus(vendaPerc,'Vendas/serviços')}</div>`}
function salesCfgHeader(ent){const c=calcMeta(ent).cfg||{}; return ent.type==='filial' ? `mín. vendas ${Number(c.gerente_vendas_min_pct||0)}% · mín. serviços ${Number(c.gerente_servicos_min_pct||0)}%` : `mín. vendas ${Number(c.vendas_min_pct||0)}% · mín. serviços ${Number(c.servicos_min_pct||0)}%`}
function rentabilidadeAtualPct(ent){return Number(ent?.rentabilidade_pct||0)}
function renderRentabilidadeBadge(ent){const r=rentabilidadeAtualPct(ent); const txt=r?`${r.toFixed(2).replace('.',',')}%`:'Sem dado'; return `<div class="rent-badge"><span>📊 Rentabilidade atual</span><strong>${txt}</strong></div>`}
function renderSalesPanel(ent){const blocks = ent.type==='filial' ? [['venda_filial_meta','📈 Venda · Meta Filial'],['servico_filial_ouro_fob','🛠️ Serviço · Ouro / FOB'],['venda_filial_subgrupo_20k','🚚 Venda · Caminhão 20K / Subgrupo']] : [['venda_filial_vendedor_meta','📈 Venda · Meta Vendedor'],['servico_filial_vendedor_ouro_fob','🛠️ Serviço · Ouro / FOB Vendedor'],['venda_vendedor_subgrupo_20k','🚚 Venda · Caminhão 20K / Subgrupo']]; return `<div class="glass panel sales-panel"><div class="section-head" style="margin:0 0 10px;align-items:flex-start"><div><h3 style="margin:0">💲 Vendas e metas <span class="sales-note">· SGI / mês atual</span></h3><div style="margin-top:8px">${renderRentabilidadeBadge(ent)}</div></div><div class="sales-note" style="text-align:right;max-width:280px">${salesCfgHeader(ent)}</div></div>${renderDualMascotStatus(ent)}<div class="sales-stack">${blocks.map(([k,t])=>renderSalesRows(ent,k,t)).join('')}</div><div style="height:14px"></div>${renderServicosEntidade(ent)}</div>`}

function salesMetricFromRow(row,key){if(!row) return 0; if(key==='venda_realizado') return salesNum(salesCell(row,['Realizado (R$) Total','Realizado(R$) Total'])); if(key==='servico_realizado') return salesNum(salesCell(row,['Realizado (R$) Total','Realizado(R$) Total'])); if(key==='venda_atingido') return salesNum(salesCell(row,['Atingido Total'])); if(key==='servico_atingido') return salesNum(salesCell(row,['Atingido Total'])); return 0}
function bestLiveSalesEntity(entities,key){let best=null; entities.forEach(ent=>{const rows=getSalesRows(ent,key); rows.forEach(r=>{const val=salesMetricFromRow(r,key.includes('servico')?'servico_realizado':'venda_realizado'); if(!best || val>best.val) best={ent,row:r,val};})}); return best}
function defaultVendPolicy(){return [
{faixa1:'0',faixa2:'50999.99',comissao:'0.70',bonus90:'100',bonus100:'250',bonus120:'320',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'51000',faixa2:'70999.99',comissao:'0.74',bonus90:'130',bonus100:'270',bonus120:'350',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'71000',faixa2:'90999.99',comissao:'0.76',bonus90:'160',bonus100:'290',bonus120:'380',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'91000',faixa2:'100999.99',comissao:'0.78',bonus90:'190',bonus100:'330',bonus120:'390',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'101000',faixa2:'120999.99',comissao:'0.80',bonus90:'220',bonus100:'360',bonus120:'420',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'121000',faixa2:'140999.99',comissao:'0.82',bonus90:'250',bonus100:'380',bonus120:'430',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'141000',faixa2:'160999.99',comissao:'0.84',bonus90:'270',bonus100:'400',bonus120:'450',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'161000',faixa2:'180999.99',comissao:'0.86',bonus90:'290',bonus100:'410',bonus120:'470',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'181000',faixa2:'200999.99',comissao:'0.88',bonus90:'300',bonus100:'420',bonus120:'500',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'},
{faixa1:'201000',faixa2:'ACIMA',comissao:'0.90',bonus90:'320',bonus100:'430',bonus120:'550',rent48:'200',rent52:'300',rent55:'400',servico_pct:'12',caminhao_pct:'20'}
]}
function defaultGerPolicy(){return [
{faixa1:'0',faixa2:'80999.99',bonusLoja:'300',comissao:'0.50',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'81000',faixa2:'110999.99',bonusLoja:'400',comissao:'0.50',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'111000',faixa2:'140999.99',bonusLoja:'500',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'141000',faixa2:'170999.99',bonusLoja:'600',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'171000',faixa2:'200999.99',bonusLoja:'700',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'201000',faixa2:'230999.99',bonusLoja:'750',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'231000',faixa2:'260999.99',bonusLoja:'800',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'261000',faixa2:'290999.99',bonusLoja:'900',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'291000',faixa2:'320999.99',bonusLoja:'950',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'},
{faixa1:'321000',faixa2:'ACIMA',bonusLoja:'1000',comissao:'0.45',rent48:'100',rent52:'150',rent55:'300',servico_pct:'6',caminhao_pct:'10'}
]}
function commissionCfg(cfg){return {
vendedor_policy:Array.isArray(cfg?.vendedor_policy)&&cfg.vendedor_policy.length?cfg.vendedor_policy:defaultVendPolicy(),
gerente_policy:Array.isArray(cfg?.gerente_policy)&&cfg.gerente_policy.length?cfg.gerente_policy:defaultGerPolicy(),
vendedor_policy_headers:Array.isArray(cfg?.vendedor_policy_headers)&&cfg.vendedor_policy_headers.length?cfg.vendedor_policy_headers:['De','Até','% Comissão','Bônus 90%','Bônus 100%','Bônus 120%','Rentab 48%','Rentab 52,15%','Rentab 55,50%','% Serviços','% Caminhão'],
gerente_policy_headers:Array.isArray(cfg?.gerente_policy_headers)&&cfg.gerente_policy_headers.length?cfg.gerente_policy_headers:['De','Até','Classificação Loja Bônus','% Comissão','Rentab 48%','Rentab 52,15%','Rentab 55,50%','% Serviços','% Caminhão'],
camp_meta_diaria_vend:Array.isArray(cfg?.camp_meta_diaria_vend)&&cfg.camp_meta_diaria_vend.length?cfg.camp_meta_diaria_vend:defaultCampMetaDiariaVend(),
camp_meta_diaria_ger:Array.isArray(cfg?.camp_meta_diaria_ger)&&cfg.camp_meta_diaria_ger.length?cfg.camp_meta_diaria_ger:defaultCampMetaDiariaGer(),
camp_dindin_vend:Array.isArray(cfg?.camp_dindin_vend)&&cfg.camp_dindin_vend.length?cfg.camp_dindin_vend:defaultCampDindinVend(),
camp_dindin_ger:Array.isArray(cfg?.camp_dindin_ger)&&cfg.camp_dindin_ger.length?cfg.camp_dindin_ger:defaultCampDindinGer(),
camp_admin:Array.isArray(cfg?.camp_admin)&&cfg.camp_admin.length?cfg.camp_admin:defaultCampAdmin(),
camp_cobranca_terceiro:Array.isArray(cfg?.camp_cobranca_terceiro)&&cfg.camp_cobranca_terceiro.length?cfg.camp_cobranca_terceiro:defaultCampTerceiro(),
camp_cob_crediarista:Array.isArray(cfg?.camp_cob_crediarista)&&cfg.camp_cob_crediarista.length?cfg.camp_cob_crediarista:defaultCampCrediarista()
}}
function renderPolicyTable(id, rows, cols, headers){return `<div class="comm-scroll"><table class="comm-table"><thead><tr>${cols.map((c,i)=>`<th><input data-comm-head="${id}" data-index="${i}" value="${esc(headers?.[i]??c.label)}"></th>`).join('')}</tr></thead><tbody>${rows.map((r,i)=>`<tr>${cols.map(c=>`<td><input data-comm="${id}" data-row="${i}" data-key="${c.key}" value="${esc(r[c.key]??'')}"></td>`).join('')}</tr>`).join('')}</tbody></table></div>`}

function defaultCampMetaDiariaVend(){return [{dias_uteis:'26',bonus_final:'500'}]}
function defaultCampMetaDiariaGer(){return [{dias_uteis:'26',bonus_final:'1000'}]}
function defaultCampDindinVend(){return [{atingido:'105',extra_pct:'0.50'},{atingido:'110',extra_pct:'1.00'}]}
function defaultCampDindinGer(){return [{atingido:'105',extra_pct:'0.50'},{atingido:'110',extra_pct:'1.00'}]}
function defaultCampAdmin(){return [{atingido:'100',extra_pct:'0.15',colaboradores:'5'},{atingido:'105',extra_pct:'0.20',colaboradores:'5'},{atingido:'110',extra_pct:'0.22',colaboradores:'5'}]}
function defaultCampCrediarista(){return [{faixa:'atencao',pct:'1.00'},{faixa:'alerta',pct:'2.00'},{faixa:'grave',pct:'3.00'}]}
function renderCommissionPanel(cfg){const pc=commissionCfg(cfg);
const vendCols=[{key:'faixa1',label:'De'},{key:'faixa2',label:'Até'},{key:'comissao',label:'% Comissão'},{key:'bonus90',label:'Bônus 90%'},{key:'bonus100',label:'Bônus 100%'},{key:'bonus120',label:'Bônus 120%'},{key:'rent48',label:'Rentab 48%'},{key:'rent52',label:'Rentab 52,15%'},{key:'rent55',label:'Rentab 55,50%'},{key:'servico_pct',label:'% Serviços'},{key:'caminhao_pct',label:'% Caminhão'}];
const gerCols=[{key:'faixa1',label:'De'},{key:'faixa2',label:'Até'},{key:'bonusLoja',label:'Classificação Loja'},{key:'comissao',label:'% Comissão'},{key:'rent48',label:'Rentab 48%'},{key:'rent52',label:'Rentab 52,15%'},{key:'rent55',label:'Rentab 55,50%'},{key:'servico_pct',label:'% Serviços'},{key:'caminhao_pct',label:'% Caminhão'}];
const cmdCols=[{key:'dias_uteis',label:'Dias úteis'},{key:'bonus_final',label:'Bônus final'}];
const cdiCols=[{key:'atingido',label:'Atingiu %'},{key:'extra_pct',label:'Extra % sobre mercantil'}];
const admCols=[{key:'atingido',label:'Atingiu % total geral'},{key:'extra_pct',label:'Extra % sobre mercantil lojas'},{key:'colaboradores',label:'Nº colaboradores'}];
const credCols=[{key:'faixa',label:'Faixa'},{key:'pct',label:'% Comissão'}];
const box=document.getElementById('commissionPanel'); if(!box) return;
box.innerHTML=`<div class="comm-wrap">
<div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">💰 Política de comissão</h2><div class="hint">Tabela global/individual para vendedores e gerente/filial.</div></div></div>
<div class="comm-box"><div class="comm-subtitle">🧑‍💼 Política do vendedor</div>${renderPolicyTable('vend',pc.vendedor_policy,vendCols,pc.vendedor_policy_headers)}</div>
<div class="comm-box"><div class="comm-subtitle">🏬 Política do gerente / filial</div>${renderPolicyTable('ger',pc.gerente_policy,gerCols,pc.gerente_policy_headers)}</div>
<div class="comm-box"><div class="comm-subtitle">🎯 CAMPANHA META DIÁRIA · vendedor</div><div class="hint">Meta geral de vendas dividida pelos dias úteis. Cada dia batido pontua 1 ponto no mês.</div>${renderPolicyTable('cmdv',pc.camp_meta_diaria_vend,cmdCols,['Dias úteis','Bônus final'])}</div>
<div class="comm-box"><div class="comm-subtitle">🎯 CAMPANHA META DIÁRIA · gerente / filial</div><div class="hint">A loja/filial que mais bater a meta diária soma pontos e recebe o bônus configurado.</div>${renderPolicyTable('cmdg',pc.camp_meta_diaria_ger,cmdCols,['Dias úteis','Bônus final'])}</div>
<div class="comm-box"><div class="comm-subtitle">💸 CAMPANHA DINDIN NO BOLSO · vendedor</div><div class="hint">Válida só no mercantil. Desbloqueia apenas se recebimentos estiverem acima de 75%.</div>${renderPolicyTable('cdiv',pc.camp_dindin_vend,cdiCols,['Atingiu %','Extra % mercantil'])}</div>
<div class="comm-box"><div class="comm-subtitle">💸 CAMPANHA DINDIN NO BOLSO · gerente / filial</div><div class="hint">Mesmo conceito para filial/gerente, somente sobre mercantil líquido.</div>${renderPolicyTable('cdig',pc.camp_dindin_ger,cdiCols,['Atingiu %','Extra % mercantil'])}</div>
<div class="comm-box"><div class="comm-subtitle">🏢 CAMPANHA DINDIN NO BOLSO · administrativo</div><div class="hint">Tabela apenas para consulta manual. O cálculo do administrativo será feito manualmente depois.</div>${renderPolicyTable('cadm',pc.camp_admin,admCols,['Atingiu % total','Extra % lojas','Nº colaboradores'])}</div>
<div class="comm-box"><div class="comm-subtitle">🤝 COMISSÃO COBRANÇA TERCEIRO · Cobrança10</div><div class="hint">Comissão por faixa somente para clientes realmente cobrados e recebidos no mês.</div>${renderPolicyTable('cter',pc.camp_cobranca_terceiro,credCols,['Faixa','% Comissão'])}</div>
<div class="comm-box"><div class="comm-subtitle">🧾 COMISSÃO CREDIARISTAS · filiais</div><div class="hint">Configuração padrão para os usuários crediaristas por faixa.</div>${renderPolicyTable('ccred',pc.camp_cob_crediarista,credCols,['Faixa','% Comissão'])}</div>
</div>`}
function readCommissionPanel(){const vendRows=[], gerRows=[]; const vendHeaders=[], gerHeaders=[]; const cmdv=[], cmdg=[], cdiv=[], cdig=[], cadm=[], cter=[], ccred=[];
document.querySelectorAll('[data-comm="vend"]').forEach(el=>{const i=Number(el.dataset.row||0); vendRows[i]=vendRows[i]||{}; vendRows[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="ger"]').forEach(el=>{const i=Number(el.dataset.row||0); gerRows[i]=gerRows[i]||{}; gerRows[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="cmdv"]').forEach(el=>{const i=Number(el.dataset.row||0); cmdv[i]=cmdv[i]||{}; cmdv[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="cmdg"]').forEach(el=>{const i=Number(el.dataset.row||0); cmdg[i]=cmdg[i]||{}; cmdg[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="cdiv"]').forEach(el=>{const i=Number(el.dataset.row||0); cdiv[i]=cdiv[i]||{}; cdiv[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="cdig"]').forEach(el=>{const i=Number(el.dataset.row||0); cdig[i]=cdig[i]||{}; cdig[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="cadm"]').forEach(el=>{const i=Number(el.dataset.row||0); cadm[i]=cadm[i]||{}; cadm[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="cter"]').forEach(el=>{const i=Number(el.dataset.row||0); cter[i]=cter[i]||{}; cter[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm="ccred"]').forEach(el=>{const i=Number(el.dataset.row||0); ccred[i]=ccred[i]||{}; ccred[i][el.dataset.key]=el.value});
document.querySelectorAll('[data-comm-head="vend"]').forEach(el=>{vendHeaders[Number(el.dataset.index||0)] = el.value});
document.querySelectorAll('[data-comm-head="ger"]').forEach(el=>{gerHeaders[Number(el.dataset.index||0)] = el.value});
return {
  vendedor_policy:vendRows.filter(Boolean),
  gerente_policy:gerRows.filter(Boolean),
  vendedor_policy_headers:vendHeaders.filter(v=>v!=null),
  gerente_policy_headers:gerHeaders.filter(v=>v!=null),
  camp_meta_diaria_vend:cmdv.filter(Boolean),
  camp_meta_diaria_ger:cmdg.filter(Boolean),
  camp_dindin_vend:cdiv.filter(Boolean),
  camp_dindin_ger:cdig.filter(Boolean),
  camp_admin:cadm.filter(Boolean),
  camp_cobranca_terceiro:cter.filter(Boolean),
  camp_cob_crediarista:ccred.filter(Boolean)
}}

function moneyNum(s){return parseFloat(String(s||'').replace(/\./g,'').replace(',','.'))||0}
function faixaMatchRealizado(rows, realizado){const n=Number(realizado||0); for(const r of (rows||[])){const de=parseFloat(String(r.faixa1||'0').replace(',','.'))||0; const ateRaw=String(r.faixa2||'').toUpperCase(); if(ateRaw.includes('ACIMA')){ if(n>=de) return r; } else { const ate=parseFloat(String(r.faixa2||'0').replace(',','.'))||0; if(n>=de && n<=ate) return r; }} return (rows||[])[(rows||[]).length-1]||null}
function calcCommissionSummary(ent){
  const cfg=entityConfig(ent);
  const cc=commissionCfg(cfg);
  const vendaRow=(getSalesRows(ent, ent.type==='filial'?'venda_filial_meta':'venda_filial_vendedor_meta')[0])||null;
  const servRow=(getSalesRows(ent, ent.type==='filial'?'servico_filial_ouro_fob':'servico_filial_vendedor_ouro_fob')[0])||null;
  const camRow=(ent.type==='vendedor'?(getSalesRows(ent,'venda_vendedor_subgrupo_20k')[0]||null):(getSalesRows(ent,'venda_filial_subgrupo_20k')[0]||null));
  const vendaRealBruto=moneyNum(salesCell(vendaRow,['Realizado (R$) Total','Realizado(R$) Total']));
  const vendaPerc=salesNum(salesCell(vendaRow,['Atingido Total']));
  const servReal=moneyNum(salesCell(servRow,['Realizado (R$) Total','Realizado(R$) Total']));
  const camReal=moneyNum(salesCell(camRow,['Realizado (R$) Total','Realizado(R$) Total']));
  const vendaReal=Math.max(0,vendaRealBruto-camReal);
  const policy=ent.type==='filial'?cc.gerente_policy:cc.vendedor_policy;
  const faixa=faixaMatchRealizado(policy,vendaReal) || {};
  const comPerc=Number(faixa.comissao||0);
  const servPct=Number(faixa.servico_pct||0);
  const camPct=Number(faixa.caminhao_pct||0);
  const vendasComissao=(vendaReal*comPerc/100);
  let bonusMeta=0;
  let bonusLiberado=false;
  const minVenda = ent.type==='filial' ? Number(cfg.gerente_vendas_min_pct||90) : Number(cfg.vendas_min_pct||80);
  const minServico = ent.type==='filial' ? Number(cfg.gerente_servicos_min_pct||90) : Number(cfg.servicos_min_pct||80);
  const rentMin50 = 50;
  const geralMeta = calcMeta(ent).geral||0;
  if(ent.type==='filial'){
    if(vendaPerc>=minVenda){ bonusMeta=Number(faixa.bonusLoja||0); bonusLiberado=bonusMeta>0; }
  } else {
    if(vendaPerc>=120){ bonusMeta=Number(faixa.bonus120||0); bonusLiberado=bonusMeta>0; }
    else if(vendaPerc>=100){ bonusMeta=Number(faixa.bonus100||0); bonusLiberado=bonusMeta>0; }
    else if(vendaPerc>=90){ bonusMeta=Number(faixa.bonus90||0); bonusLiberado=bonusMeta>0; }
  }
  const elegivelMercantil=vendaPerc>=minVenda;
  const elegivelServicos=vendaPerc>=minServico;
  const servicosComissao=elegivelServicos?(servReal*servPct/100):0;
  const caminhaoComissao=elegivelServicos?(camReal*camPct/100):0;

  const rentAtual = Number(ent?.rentabilidade_pct||0);
  const rentUnlocked = geralMeta>=rentMin50;
  const rentThresholds = [
    {label:'48%', key:'rent48', min:48.0, valor:Number(faixa.rent48||0)},
    {label:'52,15%', key:'rent52', min:52.15, valor:Number(faixa.rent52||0)},
    {label:'55,50%', key:'rent55', min:55.50, valor:Number(faixa.rent55||0)}
  ];
  let rentPremio=0, rentFaixaTxt='Sem dado', rentAppliedKey='';
  if(rentUnlocked){
    rentThresholds.forEach(rt=>{
      if(rentAtual>=rt.min){
        rentPremio=rt.valor||0;
        rentFaixaTxt=rt.label;
        rentAppliedKey=rt.key;
      }
    });
  }
  const rent48=(rentUnlocked && rentAtual>=48.0)?Number(faixa.rent48||0):0;
  const rent52=(rentUnlocked && rentAtual>=52.15)?Number(faixa.rent52||0):0;
  const rent55=(rentUnlocked && rentAtual>=55.50)?Number(faixa.rent55||0):0;
  const metaAtingida=vendaPerc>=minVenda || geralMeta>=rentMin50;

  return {
    vendaRealBruto,vendaReal,vendaPerc,servReal,camReal,comPerc,servPct,camPct,
    vendasComissao,servicosComissao,caminhaoComissao,bonusMeta,bonusLiberado,
    elegivelMercantil,elegivelServicos,rentUnlocked,rent48,rent52,rent55,
    rentAtual,rentPremio,rentFaixaTxt,rentAppliedKey,
    totalPrevisto:(vendasComissao+servicosComissao+caminhaoComissao+bonusMeta+rentPremio),
    faixaTxt:`${faixa.faixa1||'-'} até ${faixa.faixa2||'-'}`,
    metaAtingida,minVenda,minServico,geralMeta
  }
}

function rowFirst(arr){return Array.isArray(arr)&&arr.length?arr[0]:{}}
function campaignMetaDailyData(ent){
  const cfg = commissionCfg(entityConfig(ent));
  const vendaKey = ent.type === 'filial' ? 'venda_filial_meta' : 'venda_filial_vendedor_meta';
  const vendaRow = (getSalesRows(ent, vendaKey)[0]) || null;

  const metaDiaRow = ent.type === 'filial'
    ? rowFirst(cfg.camp_meta_diaria_ger)
    : rowFirst(cfg.camp_meta_diaria_vend);

  const diasUteis = Math.max(1, Number(metaDiaRow.dias_uteis || 26));

  // CORRETO: meta diária usa META TOTAL, não Meta Período.
  const metaTotal = moneyNum(salesCell(vendaRow, [
    'Meta (R$) Total',
    'Meta(R$) Total'
  ]));

  // CORRETO: pontos usam REALIZADO TOTAL acumulado do mês.
  const realizadoTotal = moneyNum(salesCell(vendaRow, [
    'Realizado (R$) Total',
    'Realizado(R$) Total'
  ]));

  const metaDiaria = metaTotal > 0 ? (metaTotal / diasUteis) : 0;

  // REGRA DEFINITIVA: ponto é diário real, salvo no histórico.
  // Não pode pegar realizado acumulado e dividir pela meta diária.
  const mesAtual = new Date().toISOString().slice(0, 7);
  const mdMes = HIST_DASH?.daily_meta?.months?.[mesAtual] || {filiais:{}, vendedores:{}};
  let histObj = null;
  if (ent.type === 'filial') {
    histObj = mdMes?.filiais?.[ent.filial] || null;
  } else {
    const alvoNome = normSalesText(ent.nome);
    const alvoFilial = String(ent.filial || '').toUpperCase();
    const candidatos = Object.entries(mdMes?.vendedores || {});
    for (const [k, v] of candidatos) {
      const nomeOk = normSalesText(v?.nome || k).includes(alvoNome) || alvoNome.includes(normSalesText(v?.nome || k));
      const filialOk = String(v?.filial || '').toUpperCase() === alvoFilial || String(k || '').toUpperCase().includes(alvoFilial);
      if (nomeOk && filialOk) { histObj = v; break; }
    }
  }
  const pontosMetaDiaria = Math.min(diasUteis, Number(histObj?.pontos || 0));
  const hojeKey = new Date().toISOString().slice(0, 10);
  const realizadoDia = Number(histObj?.dias?.[hojeKey]?.realizado_dia || 0);
  const pontoHoje = Number(histObj?.dias?.[hojeKey]?.ponto || 0);

  return {
    cfg,
    vendaRow,
    metaDiaRow,
    diasUteis,
    metaTotal,
    realizadoTotal,
    metaDiaria,
    realizadoDia,
    pontoHoje,
    pontosMetaDiaria
  };
}

function campanhaRankingEntities(ent){
  if (ent.type === 'filial') {
    return Object.entries(FILIAIS || {}).map(([k, v]) => ({
      type: 'filial',
      filial: k,
      nome: v.nome || k,
      ...(v || {})
    }));
  }

  return Object.entries(TODOS || {}).flatMap(([filial, arr]) =>
    (arr || []).map(v => ({
      type: 'vendedor',
      filial,
      nome: v.nome,
      ...(v || {})
    }))
  );
}

function isLiderMetaDiaria(ent){
  const atual = campaignMetaDailyData(ent);

  if (!atual.metaDiaria || atual.metaDiaria <= 0) return false;

  const ranking = campanhaRankingEntities(ent)
    .map(e => {
      const d = campaignMetaDailyData(e);
      return {
        ent: e,
        pontos: Number(d.pontosMetaDiaria || 0),
        realizadoTotal: Number(d.realizadoTotal || 0),
        metaDiaria: Number(d.metaDiaria || 0)
      };
    })
    .filter(x => x.metaDiaria > 0)
    .sort((a, b) => {
      if (b.pontos !== a.pontos) return b.pontos - a.pontos;
      return b.realizadoTotal - a.realizadoTotal;
    });

  if (!ranking.length) return false;

  const lider = ranking[0].ent;

  if (ent.type === 'filial') {
    return String(lider.filial || '').toUpperCase() === String(ent.filial || '').toUpperCase();
  }

  return (
    String(lider.nome || '').toUpperCase() === String(ent.nome || '').toUpperCase() &&
    String(lider.filial || '').toUpperCase() === String(ent.filial || '').toUpperCase()
  );
}

function calcCampaignSummary(ent){
  const base = campaignMetaDailyData(ent);
  const cfg = base.cfg;
  const sale = calcCommissionSummary(ent);
  const meta = calcMeta(ent);

  const dindinRows = ent.type === 'filial'
    ? cfg.camp_dindin_ger
    : cfg.camp_dindin_vend;

  let dindinExtraPct = 0;

  (dindinRows || []).forEach(r => {
    if (sale.vendaPerc >= Number(r.atingido || 0) && meta.geral >= 75) {
      dindinExtraPct = Math.max(dindinExtraPct, Number(r.extra_pct || 0));
    }
  });

  const dindinExtra = sale.vendaReal * (dindinExtraPct / 100);

  return {
    metaDiaria: base.metaDiaria,
    pontosMetaDiaria: base.pontosMetaDiaria,
    diasUteis: base.diasUteis,
    metaTotal: base.metaTotal,
    realizadoTotal: base.realizadoTotal,
    realizadoDia: base.realizadoDia,
    pontoHoje: base.pontoHoje,
    bonusMetaDiaria: String(base.metaDiaRow.bonus_final || '0'),
    dindinExtraPct,
    dindinExtra,
    dindinLiberado: dindinExtraPct > 0,
    liderMetaDiaria: isLiderMetaDiaria(ent)
  };
}

function renderCampaignSummary(ent){
  const c = calcCampaignSummary(ent);

  // REGRA NOVA: se não estiver em 1º lugar, oculta a campanha Meta Diária.
  if (!c.liderMetaDiaria) return '';

  const item = (k, v, locked = false) =>
    `<div class="campaign-item ${locked ? 'locked' : ''}">
      <div class="k">${k}</div>
      <div class="v">${v}</div>
    </div>`;

  return `<div class="glass panel campaign-card">
    <h3>🎯 Campanhas ativas <span class="note">· acompanhamento do mês</span></h3>

    <div class="campaign-grid">
      ${item('Meta diária', R(c.metaDiaria || 0), false)}
      ${item('Pontos no mês', `${c.pontosMetaDiaria || 0} / ${c.diasUteis || 26}`, false)}
      ${item('Bônus meta diária', String(c.bonusMetaDiaria || '0'), false)}
      ${item('Dindin no bolso %', String((c.dindinExtraPct || 0).toFixed(2)).replace('.', ',') + '%', !c.dindinLiberado)}
      ${item('Dindin no bolso valor', R(c.dindinExtra || 0), !c.dindinLiberado)}
    </div>

    <div class="commission-note">
      Campanha Meta Diária aparece somente para o 1º colocado.
      Cálculo: Meta Total ${R(c.metaTotal || 0)} ÷ ${c.diasUteis || 26} dias úteis =
      ${R(c.metaDiaria || 0)} por dia. Pontos: só soma quando a venda DO DIA bate a meta diária.
      Hoje: ${R(c.realizadoDia || 0)} ${c.pontoHoje ? '✅ ponto ganho' : '⏳ sem ponto'} .
    </div>
  </div>`;
}

function renderCommissionSummary(ent){const c=calcCommissionSummary(ent); const totalLiberado = c.elegivelMercantil && c.elegivelServicos; const totalExibido = totalLiberado ? c.totalPrevisto : 0; const moneyCell=(title,val,locked=false,extra='')=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''} ${extra}"><div class="k">${title}</div><div class="v">${R(val||0)}</div></div>`; const pctCell=(title,val,locked=false)=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''}"><div class="k">${title}</div><div class="v">${String(Number(val||0).toFixed(2)).replace('.',',')}%</div></div>`; return `<div class="glass panel commission-card"><h3>💵 Comissionamento previsto <span class="note">· calculado pela política salva</span></h3>${c.metaAtingida?`<div class="meta-hit-banner"><img src="${LARANJITO}" alt=""><span>Meta liberada! O Laranjito está comemorando sua liberação de comissão/bonus.</span></div>`:''}<div class="commission-grid">${`<div class="commission-item unlocked"><div class="k">Faixa aplicada</div><div class="v" style="font-size:16px">${esc(c.faixaTxt)}</div></div>`}${pctCell('% comissão mercantil',c.comPerc,!c.elegivelMercantil)}${pctCell('% serviços',c.servPct,!c.elegivelServicos)}${pctCell('% caminhão',c.camPct,!c.elegivelServicos)}${moneyCell('Comissão vendas',c.vendasComissao,!c.elegivelMercantil)}${moneyCell('Comissão serviços',c.servicosComissao,!c.elegivelServicos)}${moneyCell('Comissão caminhão',c.caminhaoComissao,!c.elegivelServicos)}${moneyCell('Bônus por meta',c.bonusMeta,!c.bonusLiberado)}${moneyCell('Rentab 48%',c.rent48,!c.rentUnlocked)}${moneyCell('Rentab 52,15%',c.rent52,!c.rentUnlocked)}${moneyCell('Rentab 55,50%',c.rent55,!c.rentUnlocked)}${moneyCell('Total previsto',totalExibido,!totalLiberado,'total-final '+(!totalLiberado?'total-locked':''))}</div><div class="commission-note">Base mercantil bruta: ${R(c.vendaRealBruto||0)} · Caminhão abatido: ${R(c.camReal||0)} · Mercantil líquido para comissão: ${R(c.vendaReal||0)} · Serviço: ${R(c.servReal||0)}. Mínimo vendas ${pct(c.minVenda)} · mínimo serviços/caminhão ${pct(c.minServico)} · rentabilidades liberam ao bater 50% da meta de cobrança.</div></div>`}
function backToMain(){currentDetailRef=null; detailScreen.classList.add('hidden');document.getElementById('mainScreen').classList.remove('hidden')}
function renderMetaBox(title,color,obj){return `<div class="meta-card"><div class="meta-title">${title}</div><div class="meta-main" style="color:${color}">${pct(obj.perc||0)}</div><div class="meta-sub">Alvo: ${R(obj.alvo||0)}</div><div class="meta-sub">Recebido: ${R(obj.rec||0)}</div></div>`}
function renderBonusBox(cfg,geral){const achieved=(geral>=100&&cfg.bonus_100)?100:(geral>=85&&cfg.bonus_85)?85:(geral>=75&&cfg.bonus_75)?75:(geral>=50&&cfg.bonus_50)?50:0; const items=[[50,cfg.bonus_50||'-'],[75,cfg.bonus_75||'-'],[85,cfg.bonus_85||'-'],[100,cfg.bonus_100||'-']];return `<div class="bonus-box"><h4>Faixas configuradas</h4><div class="bonus-list">${items.map(([p,t])=>`<div class="bonus-item ${achieved===p?'active':''}" style="${achieved===p?'box-shadow:0 0 0 2px rgba(59,130,246,.18),0 0 26px rgba(59,130,246,.2);animation:liquid 1.6s ease-in-out infinite alternate':''}"><div class="left"><span>🎯</span><span>${p}%</span></div><div style="display:flex;align-items:center;gap:10px">${achieved===p?`<img src="${LARANJITO}" alt="laranjito" style="width:34px;height:34px;border-radius:10px;object-fit:cover">`:''}<span>${esc(t)}</span></div></div>`).join('')}</div></div>`}
function renderSingleBars(ent,meta,big=false){const vals=[['Grave',meta.grave.pend,'var(--red)'],['Alerta',meta.alerta.pend,'var(--orange)'],['Atenção',meta.atencao.pend,'var(--yellow)'],['Recebido',Number(ent.pago||0),'var(--green)']]; const max=Math.max(1,...vals.map(v=>v[1])); return `<div class="glass big-chart-card" style="margin-top:0"><div class="legend-inline"><span><i class="dot" style="background:var(--red)"></i>Grave</span><span><i class="dot" style="background:var(--orange)"></i>Alerta</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção</span><span><i class="dot" style="background:var(--green)"></i>Recebido</span></div><div class="groupbars" style="justify-content:center"><div class="group" style="min-width:100%"><div class="bars" style="height:${big?320:260}px;justify-content:space-around;border-left:none">${vals.map(v=>`<div style="text-align:center"><div class="bar" style="width:${big?72:54}px;height:${Math.max(18,(v[1]/max)*(big?250:200))}px;background:linear-gradient(180deg,rgba(255,255,255,.18),transparent),linear-gradient(180deg,${v[2]},${v[2]})"><span class="wave one"></span><span class="wave two"></span><span class="bubble b1"></span><span class="bubble b2"></span><span class="bubble b3"></span></div><div class="glabel" style="margin-top:10px">${v[0]}<br><strong>${R(v[1])}</strong></div></div>`).join('')}</div></div></div></div>`}
function recebKeyVend(ent){return `${ent.nome}_${ent.filial}`}
function getRecebimentos(ent){if(ent.type==='terceiro' || ent.is_terceiro) return RECEBIMENTOS_TERCEIRO||{grave:[],alerta:[],atencao:[]}; if(ent.type==='crediarista' || ent.is_crediarista){ const filialKey=String(ent.filial||'').toUpperCase(); const base={grave:[],alerta:[],atencao:[]}; Object.entries(RECEBIMENTOS||{}).forEach(([k,v])=>{if(k.endsWith('_'+filialKey)){['grave','alerta','atencao'].forEach(fx=>base[fx].push(...(v[fx]||[])))}}); ['grave','alerta','atencao'].forEach(fx=>base[fx].sort((a,b)=>Number(b.pago||0)-Number(a.pago||0))); return base} if(ent.type==='vendedor') return RECEBIMENTOS[recebKeyVend(ent)]||{grave:[],alerta:[],atencao:[]}; const base={grave:[],alerta:[],atencao:[]}; Object.entries(RECEBIMENTOS||{}).forEach(([k,v])=>{if(k.endsWith('_'+ent.filial)){['grave','alerta','atencao'].forEach(fx=>base[fx].push(...(v[fx]||[])))}}); ['grave','alerta','atencao'].forEach(fx=>base[fx].sort((a,b)=>Number(b.pago||0)-Number(a.pago||0))); return base}
function renderRecebimentos(ent){const src=getRecebimentos(ent); let out=''; ['grave','alerta','atencao'].forEach(fx=>{const arr=src[fx]||[]; const label=fx==='grave'?'Grave':fx==='alerta'?'Alerta':'Atenção'; if(!arr.length){out+=`<div class="faixa-block"><div class="faixa-title ${fx}">${label}<span>Sem recebimentos</span></div></div>`; return} out+=`<div class="faixa-block"><div class="faixa-title ${fx}">${label}<span>${arr.length} títulos · ${R(arr.reduce((a,b)=>a+Number(b.pago||0),0))}</span></div><div class="tableish">${arr.slice(0,80).map(r=>`<div class="row-item"><div class="row-top"><div><div class="name">${esc(r.cliente||r.nome||'')}</div><div class="small muted">Título ${esc(r.titulo||'')} · Parcela ${esc(r.parcela||'')}</div></div><div><strong>${esc(r.pagamento||'')}</strong><div class="small muted">Pagamento</div></div><div><strong>${esc(r.vencimento||'')}</strong><div class="small muted">Vencimento</div></div><div><strong>${r.dias||0}d</strong><div class="small muted">Dias</div></div><div><strong>${R(r.pago||0)}</strong><div class="small muted">Recebido</div></div><div><strong>${esc(r.vendedor||'')}</strong><div class="small muted">Origem</div></div></div></div>`).join('')}</div></div>`}); return out}
function cobrancaRowKey(r){return [String(r.cliente||r.nome||'').trim().toUpperCase(),String(r.titulo||'').trim(),String(r.parcela||'').trim(),String(r.vencimento||'').trim()].join('|')}
function dedupeCobrancaBuckets(src){const out={grave:[],alerta:[],atencao:[]}; const seen=new Set(); ['grave','alerta','atencao'].forEach(fx=>{(src?.[fx]||[]).forEach(r=>{const k=cobrancaRowKey(r); if(!seen.has(k)){seen.add(k); out[fx].push(r);}})}); return out}
function vendorAssignedKeysByFilial(filial){const keys=new Set(); const arr=(TODOS?.[filial]||[]); arr.forEach(v=>{const buckets=CLIENTES_VEND?.[v.nome]||{grave:[],alerta:[],atencao:[]}; ['grave','alerta','atencao'].forEach(fx=>(buckets[fx]||[]).forEach(r=>keys.add(cobrancaRowKey(r))))}); return keys}
function getClientesEnt(ent){
  if(ent.type==='terceiro' || ent.is_terceiro) return dedupeCobrancaBuckets(CLIENTES_TERCEIRO||{grave:[],alerta:[],atencao:[]});
  if(ent.type==='crediarista' || ent.is_crediarista){ const filialKey=String(ent.filial||'').toUpperCase(); const loginKey=String(ent.login||crediaristaLoginByFilial(filialKey)||'').toLowerCase(); return dedupeCobrancaBuckets(CLIENTES_FIL?.[filialKey]||CLIENTES_CREDIARISTA?.[loginKey]||{grave:[],alerta:[],atencao:[]}); }
  if(ent.type==='vendedor') return dedupeCobrancaBuckets(CLIENTES_VEND[ent.nome]||{grave:[],alerta:[],atencao:[]});
  const src=CLIENTES_FIL[ent.filial]||{grave:[],alerta:[],atencao:[]};
  const taken=vendorAssignedKeysByFilial(ent.filial);
  const filtered={grave:[],alerta:[],atencao:[]};
  ['grave','alerta','atencao'].forEach(fx=>{(src[fx]||[]).forEach(r=>{const k=cobrancaRowKey(r); if(!taken.has(k)) filtered[fx].push(r);})});
  return dedupeCobrancaBuckets(filtered);
}
function isTodayStr(s){const d=new Date(s||''); const t=new Date(); return !isNaN(d) && d.getFullYear()===t.getFullYear() && d.getMonth()===t.getMonth() && d.getDate()===t.getDate()}
function getCobradosHoje(ent){
  if(ent.type==='terceiro' || ent.is_terceiro)
    return (COB_LOGS||[]).filter(x=>isTodayStr(x.server_time||x.data||'') && (String(x.usuario||'').toLowerCase()===COBRANCA10_LOGIN || String(x.usuario||'').toLowerCase()===COBRANCA10_NOME.toLowerCase()));
  if(ent.type==='crediarista' || ent.is_crediarista){
    const credLogin=String(ent.login||'').toLowerCase();
    const credNome=String(ent.nome||'').toLowerCase();
    const credFilial=String(ent.filial||'').toUpperCase();
    return (COB_LOGS||[]).filter(x=>isTodayStr(x.server_time||x.data||'') && (
      String(x.usuario||'').toLowerCase()===credLogin ||
      String(x.usuario||'').toLowerCase()===credNome ||
      (String(x.filial||'').toUpperCase()===credFilial && String(x.destino_tipo||'').toLowerCase()==='crediarista')
    ));
  }
  return (COB_LOGS||[]).filter(x=>isTodayStr(x.server_time||x.data||'') && String(x.filial||'')===String(ent.filial||'') && (ent.type==='filial' || String(x.destino_nome||'')===String(ent.nome||'')));
}
function normalizarListaTelefones(contatos){let base=[]; if(Array.isArray(contatos)) base=contatos; else if(typeof contatos==='string') base=contatos.split(/[;,/|]+/); const out=[]; const seen=new Set(); base.forEach(item=>{const num=String(item||'').replace(/\D/g,''); if(num.length>=10){const finalNum=num.startsWith('55')?num:'55'+num; if(!seen.has(finalNum)){seen.add(finalNum); out.push(finalNum);}}}); return out}
function matchCob(r){return COB_LOGS.some(x=>String(x.cliente||'')===String(r.cliente||r.nome||'') && String(x.titulo||'')===String(r.titulo||'') && String(x.parcela||'')===String(r.parcela||''))}
function renderCobrancasEnt(ent){const src=getClientesEnt(ent); const cobradosHoje=getCobradosHoje(ent); const allHoje=[...(src.grave||[]),...(src.alerta||[]),...(src.atencao||[])].filter(r=>r.novo); const renderRows=(arr,showFaixa)=>!arr.length?'<div class="empty">Nada nesta aba.</div>':arr.slice(0,150).map(r=>`<div class="row-item"><div class="row-top"><div><div class="name">${esc(r.cliente||r.nome||'')} ${r.novo?'<span class="mini-chip" style="margin-left:6px;background:#eef7ff;color:#1e3a8a;border-color:#93c5fd">Novo hoje</span>':''} ${matchCob(r)?'<span class="mini-chip" style="margin-left:6px">Cobrado</span>':''}</div><div class="small muted">✍️ Avalista: ${esc((r.avalista && String(r.avalista).toLowerCase()!=='nan')?r.avalista:'Sem Aval')}</div>${(r.avalista && String(r.avalista).toLowerCase()!=='nan')?'<div class="small avalista-alert">⚠️ Atenção, lembre de cobrar o AVALISTA</div>':''}<div class="small muted">🔒 Restrição crédito: ${/sem restr/i.test(String(r.restricao||''))?`<span class="restr-ok">${esc(r.restricao||'Sem Restrição')}</span>`:esc(r.restricao||'Sem informação')}</div><div class="small muted">👤 ${esc(r.vendedor||'')}</div><div class="small muted">☎️ ${esc(Array.isArray(r.telefones)?r.telefones.join(', '):(r.contato||''))}</div></div><div><strong>${esc(r.titulo||'')}</strong><div class="small muted">Título</div></div><div><strong>${r.dias||0}d</strong><div class="small muted">Dias</div></div><div><strong>${esc(r.vencimento||'')}</strong><div class="small muted">Vencimento</div></div><div><strong>${R(r.pendente||0)}</strong><div class="small muted">Pendente</div></div><div>${showFaixa?`<div class="small muted">${esc(r.faixa_label||'')}</div>`:''}<button class="btn wa" onclick='abrirWhats(${JSON.stringify(r)}, ${JSON.stringify({type:ent.type,filial:ent.filial,nome:ent.nome})})'>💬 WhatsApp</button></div></div></div>`).join(''); const faixas=['grave','alerta','atencao']; const tabs=`<div class="tabs" style="justify-content:flex-start;margin:0 0 12px"><button class="tab active" data-cobtab="geral" onclick="switchCobTab(this,'geral')">Todos</button><button class="tab" data-cobtab="novos" onclick="switchCobTab(this,'novos')">Novos Hoje</button><button class="tab" data-cobtab="cobrados" onclick="switchCobTab(this,'cobrados')">Cobrados Hoje</button></div>`; let geral=''; faixas.forEach(fx=>{const arr=(src[fx]||[]).map(r=>({...r,faixa_label:fx})); const label=fx==='grave'?'Grave':fx==='alerta'?'Alerta':'Atenção'; geral+=`<div class="faixa-block"><div class="faixa-title ${fx}">${label}<span>${arr.length} títulos · ${R(arr.reduce((a,b)=>a+Number(b.pendente||0),0))}</span></div><div class="tableish">${renderRows(arr,false)}</div></div>`}); const srcAll=[...(src.grave||[]),...(src.alerta||[]),...(src.atencao||[])]; const cobradosRows=(cobradosHoje||[]).map(x=>{const m=srcAll.find(r=>cobrancaRowKey(r)===cobrancaRowKey(x))||{}; return {cliente:x.cliente,titulo:x.titulo,parcela:x.parcela,vencimento:x.vencimento,pendente:x.pendente,vendedor:x.usuario||m.vendedor||'',dias:'',telefones:Array.isArray(m.telefones)&&m.telefones.length?m.telefones:[x.telefone],contato:m.contato||x.telefone,avalista:m.avalista||'',restricao:m.restricao||'',faixa_label:m.faixa||'',novo:false,pagamento:m.pagamento||'',lancamento:m.lancamento||''};}); return `${tabs}<div class="cob-pane" data-cobpane="geral">${geral}</div><div class="cob-pane hidden" data-cobpane="novos">${renderRows(allHoje.map(r=>({...r,faixa_label:r.faixa||''})),true)}</div><div class="cob-pane hidden" data-cobpane="cobrados">${renderRows(cobradosRows,true)}</div>`}
function switchCobTab(btn,name){const box=btn.closest('.acc-body'); box.querySelectorAll('[data-cobtab]').forEach(b=>b.classList.toggle('active',b===btn)); box.querySelectorAll('[data-cobpane]').forEach(p=>p.classList.toggle('hidden',p.dataset.cobpane!==name));}
function abrirWhats(reg,entRef){const nums=normalizarListaTelefones((reg.telefones&&reg.telefones.length)?reg.telefones:reg.contato); if(!nums.length){toast('Cliente sem telefone válido.'); return} phoneContext={reg,entRef}; if(nums.length===1){enviarWhats(nums[0]); return} const phoneList=document.getElementById('phoneList'); phoneList.innerHTML=nums.map(n=>`<button class="btn soft" style="width:100%" onclick="enviarWhats('${n}')">${n}</button>`).join(''); document.getElementById('phoneModal').classList.add('show')}
function closePhoneModal(){document.getElementById('phoneModal').classList.remove('show'); phoneContext=null}
function enviarWhats(numero){if(!phoneContext) return; const {reg,entRef}=phoneContext; const msg=reg.mensagem_whatsapp||`Olá, ${String(reg.cliente||reg.nome||'').split(' ')[0]} tudo bem?`; window.open(`https://wa.me/${numero}?text=${encodeURIComponent(msg)}`,'_blank'); registrarCobrancaOnline(reg,entRef,numero); closePhoneModal()}
async function registrarCobrancaOnline(r,entRef,numero){
  // Para crediarista usa o login como usuario para que getCobradosHoje() funcione corretamente
  const usuarioLog = (entRef.type==='crediarista'||entRef.is_crediarista)
    ? (String(entRef.login||entRef.nome||usuarioAtual?.login||'').toLowerCase() || usuarioAtual?.login || 'master')
    : (usuarioAtual?.nome||usuarioAtual?.login||'master');
  const payload={
    cliente:r.cliente||r.nome||'',titulo:r.titulo||'',parcela:r.parcela||'',
    vencimento:r.vencimento||'',pendente:Number(r.pendente||0),telefone:numero,
    usuario:usuarioLog,filial:entRef.filial||'',
    destino_tipo:entRef.type||'',destino_nome:entRef.nome||'',acao:'whatsapp'
  };
  try{
    const resp=await fetch(API_COB,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await resp.json();
    if(j.ok){
      await carregarCobrancasOnline();
      toast('Cobrança registrada online com sucesso.','success');
      if(!detailScreen.classList.contains('hidden')){
        if(entRef.type==='crediarista'||entRef.is_crediarista){
          openCrediaristaPanel(entRef.login||'',entRef.filial||'',entRef.nome||'');
        } else {
          openEntity(entRef);
        }
      }
    } else toast('Não consegui gravar a cobrança online.');
  }catch(e){toast('Falha ao salvar cobrança online.');}
}
async function carregarCobrancasOnline(){try{const r=await fetch(API_COB+'?_='+Date.now()); const txt=await r.text(); let j={ok:false}; try{j=JSON.parse(txt);}catch(e){} COB_LOGS=(j.ok&&Array.isArray(j.data))?j.data:[]; if(!j.ok && txt) console.log('cobrancas_api retorno:', txt);}catch(e){console.log(e); COB_LOGS=[]}}
async function removerCobranca(id,cliente='',titulo='',parcela=''){if(!confirm('Remover esta cobrança do histórico?')) return; try{const r=await fetch(API_COB,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',id,cliente,titulo,parcela})}); const txt=await r.text(); let j={ok:false}; try{j=JSON.parse(txt);}catch(e){} if(j.ok){toast('Cobrança removida.','success'); await carregarCobrancasOnline(); renderLogsTab(); renderList(); if(currentDetailRef) openEntity(currentDetailRef);}else{console.log('Falha remover cobrança:', txt); toast('Não consegui remover.')}}catch(e){console.log(e); toast('Falha ao remover cobrança.')}}
function toggleAcc(el){el.parentElement.classList.toggle('open')}
async function carregarConfigOnline(){try{const r=await fetch(API_CFG+'?_='+Date.now()); const j=await r.json(); if(j.ok && j.data){CONFIG_META={...CONFIG_META,...(j.data.global||{})}; const ind=(j.data.individual && typeof j.data.individual==='object' && !Array.isArray(j.data.individual))?j.data.individual:{}; CONFIG_META_IND=ind;}}catch(e){console.log('Falha ao carregar config meta',e);}}
function optionTargets(){let opts=''; flattenFiliais().forEach(f=>{opts+=`<option value="FILIAL::${f.filial}">🏬 ${filialLabel(f.filial)}</option>`}); opts+=`<option value="VEND::${COBRANCA10_NOME}_FTER">🤝 ${COBRANCA10_NOME} (Cobranças Terceiro)</option>`; crediaristaEntities().forEach(c=>{opts+=`<option value="VEND::${c.nome}_${c.filial}">🧾 ${c.nome} (${c.filial})</option>`}); flattenVendedores().forEach(v=>{opts+=`<option value="VEND::${v.nome}_${v.filial}">👤 ${v.nome} (${v.filial})</option>`}); return opts}
function fillMetaForm(mode,val){const cfg=mode==='global'?{...CONFIG_META}:mergedMetaConfig(metaAliasesFromRaw(val)); ['grave_pct','alerta_pct','atencao_pct','peso_grave','peso_alerta','peso_atencao','bonus_50','bonus_75','bonus_85','bonus_100','vendas_min_pct','servicos_min_pct','gerente_vendas_min_pct','gerente_servicos_min_pct','cobranca_global_rateio_pct'].forEach(k=>{const el=document.getElementById('cfg_'+k); if(el) el.value=cfg[k]??''}); renderCommissionPanel(cfg)}
function canonicalMetaLabelFromKey(k){
  const v=String(k||'').trim();
  if(!v) return '';
  if(v.startsWith('VEND::')) return v;
  if(v.startsWith('FILIAL::')) return v;
  if(v.startsWith('vend:')) return 'VEND::'+v.slice(5);
  if(v.startsWith('fil:')) return 'FILIAL::'+v.slice(4);
  if(/^F\d+/i.test(v)) return 'FILIAL::'+v.toUpperCase();
  if(v.includes('_F')) return 'VEND::'+v;
  return '';
}
function renderSavedMetaList(){
  const labels=[]; const seen=new Set();
  Object.keys(CONFIG_META_IND||{}).forEach(k=>{const canon=canonicalMetaLabelFromKey(k); if(canon && !seen.has(canon)){seen.add(canon); labels.push(canon);}});
  labels.sort();
  const lst=document.getElementById('metaSavedList');
  if(lst) lst.innerHTML=labels.length?('Individuais salvos: '+labels.map(k=>`<span class="mini-chip">${esc(k)}</span>`).join(' ')):'Nenhuma configuração individual salva.';
}
function renderMetasTab(){const cards=[...flattenVendedores(),...flattenFiliais()]; const currentMode=window._metaMode||'global'; const currentTarget=window._metaSelectedTarget||''; metaSection.innerHTML=`<div class="section-head"><div><h2>🎯 Configuração de metas e bônus</h2><div class="hint">Altere globalmente ou por vendedor/filial. Ao salvar, já fica online.</div></div></div><div class="meta-layout"><div class="glass panel"><div class="tabs" style="justify-content:flex-start;margin-top:0"><button id="btnModeGlobal" class="tab" onclick="setMetaMode('global')">🌐 Padrão global</button><button id="btnModeInd" class="tab" onclick="setMetaMode('individual')">👤 Por vendedor/filial</button></div><div id="metaSelectWrap" class="hidden" style="margin:8px 0 14px"><div class="input-card"><label>Selecionar alvo</label><select id="metaTarget" onchange="loadMetaSelected()"><option value="">Selecione...</option>${optionTargets()}</select></div></div><div class="section-head" style="margin-top:10px"><div><h2 style="font-size:18px">% de meta por faixa</h2></div></div><div class="form-grid"><div class="input-card"><label>Grave</label><input id="cfg_grave_pct" type="number" step="0.01"></div><div class="input-card"><label>Alerta</label><input id="cfg_alerta_pct" type="number" step="0.01"></div><div class="input-card"><label>Atenção</label><input id="cfg_atencao_pct" type="number" step="0.01"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">Pesos da meta geral</h2></div></div><div class="form-grid"><div class="input-card"><label>Peso Grave</label><input id="cfg_peso_grave" type="number" step="0.01"></div><div class="input-card"><label>Peso Alerta</label><input id="cfg_peso_alerta" type="number" step="0.01"></div><div class="input-card"><label>Peso Atenção</label><input id="cfg_peso_atencao" type="number" step="0.01"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">Bônus / mensagem da faixa <span class="note">· Não acumulativo</span></h2></div></div><div class="form-grid bonus"><div class="input-card"><label>50%</label><input id="cfg_bonus_50" placeholder="Ex: Parabéns, você ganhou R$ 100,00"></div><div class="input-card"><label>75%</label><input id="cfg_bonus_75"></div><div class="input-card"><label>85%</label><input id="cfg_bonus_85"></div><div class="input-card"><label>100%</label><input id="cfg_bonus_100"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">💲 Meta mínima Vendas e Serviços</h2><div class="hint">Configuração inicial para comissão de vendedor e gerente/filial.</div></div></div><div class="form-grid bonus"><div class="input-card"><label>Vendedor · mínimo vendas (%)</label><input id="cfg_vendas_min_pct" type="number" step="0.01" placeholder="80"></div><div class="input-card"><label>Vendedor · mínimo serviços (%)</label><input id="cfg_servicos_min_pct" type="number" step="0.01" placeholder="80"></div><div class="input-card"><label>Gerente/Filial · mínimo vendas (%)</label><input id="cfg_gerente_vendas_min_pct" type="number" step="0.01" placeholder="90"></div><div class="input-card"><label>Gerente/Filial · mínimo serviços (%)</label><input id="cfg_gerente_servicos_min_pct" type="number" step="0.01" placeholder="90"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">🤝 Rateio cobrança global</h2><div class="hint">Percentual do total único da cobrança geral distribuído para os usuários do tipo cobrança global (ex.: Cobrança10).</div></div></div><div class="form-grid bonus"><div class="input-card"><label>Usuários de cobrança global (%)</label><input id="cfg_cobranca_global_rateio_pct" type="number" step="0.01" placeholder="20"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">🧾 Crediarista espelhado</h2><div class="hint">Os usuários crediaristas acessam a mesma base completa da filial/gerente. Não existe mais rateio separado.</div></div></div><div id="commissionPanel"></div><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px"><button class="btn primary" onclick="salvarMeta()">💾 Salvar configuração</button><button class="btn ghost" onclick="removerMetaIndividual()">🗑️ Remover individual</button></div><div id="metaSaveMsg" class="note" style="margin-top:10px"></div><div id="metaSavedList" class="note" style="margin-top:10px"></div></div></div>`; const sel=document.getElementById('metaTarget'); if(sel && currentTarget) sel.value=currentTarget; setMetaMode(currentMode); renderSavedMetaList();}
function setMetaMode(mode){window._metaMode=mode; const bg=document.getElementById('btnModeGlobal'); const bi=document.getElementById('btnModeInd'); if(bg) bg.classList.toggle('active',mode==='global'); if(bi) bi.classList.toggle('active',mode==='individual'); const wrap=document.getElementById('metaSelectWrap'); if(wrap) wrap.classList.toggle('hidden',mode!=='individual'); if(mode==='global'){fillMetaForm('global')} else {const raw=(document.getElementById('metaTarget')?.value)||window._metaSelectedTarget||''; if(raw){window._metaSelectedTarget=raw; fillMetaForm('individual',raw)} else {fillMetaForm('global')}}}
function loadMetaSelected(){const val=document.getElementById('metaTarget').value; window._metaSelectedTarget=val; if(!val){fillMetaForm('global'); return;} fillMetaForm('individual',val)}
function collectMetaForm(){const out={}; ['grave_pct','alerta_pct','atencao_pct','peso_grave','peso_alerta','peso_atencao','vendas_min_pct','servicos_min_pct','gerente_vendas_min_pct','gerente_servicos_min_pct','cobranca_global_rateio_pct'].forEach(k=>out[k]=Number(document.getElementById('cfg_'+k).value||0)); ['bonus_50','bonus_75','bonus_85','bonus_100'].forEach(k=>out[k]=document.getElementById('cfg_'+k).value||''); return {...out,...readCommissionPanel()}}
async function salvarMeta(){
  const msgEl=document.getElementById('metaSaveMsg');
  const cfg=collectMetaForm();
  if(window._metaMode==='global'){
    CONFIG_META={...CONFIG_META,...cfg};
  } else {
    const raw=(document.getElementById('metaTarget')?.value)||window._metaSelectedTarget||'';
    if(!raw){if(msgEl) msgEl.textContent='Selecione um vendedor ou filial.'; return;}
    window._metaSelectedTarget=raw;
    const aliases=metaAliasesFromRaw(raw);
    const payloadCfg={...cfg,__saved_at:new Date().toISOString(),__target:raw};
    aliases.forEach(k=>CONFIG_META_IND[k]={...payloadCfg});
  }
  try{
    const payload={global:CONFIG_META,individual:CONFIG_META_IND};
    const resp=await fetch(API_CFG,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await resp.json();
    if(msgEl) msgEl.textContent=j.ok?'✅ Salvo online com sucesso.':'⚠️ Não consegui salvar online.';
    if(j.ok){
      await carregarConfigOnline();
      renderMetasTab();
      renderList();
      const restoreMsg=document.getElementById('metaSaveMsg');
      if(restoreMsg) restoreMsg.textContent='✅ Salvo online com sucesso.';
    }
  }catch(e){console.log('Erro ao salvar meta',e); if(msgEl) msgEl.textContent='⚠️ Não consegui salvar online.';}
}
async function removerMetaIndividual(){
  const msgEl=document.getElementById('metaSaveMsg');
  const raw=(document.getElementById('metaTarget')?.value)||window._metaSelectedTarget||'';
  if(window._metaMode!=='individual' || !raw){if(msgEl) msgEl.textContent='Selecione um alvo individual para remover.'; return;}
  metaAliasesFromRaw(raw).forEach(k=>delete CONFIG_META_IND[k]);
  try{
    const resp=await fetch(API_CFG,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({global:CONFIG_META,individual:CONFIG_META_IND})});
    const j=await resp.json();
    if(msgEl) msgEl.textContent=j.ok?'✅ Configuração individual removida.':'⚠️ Não consegui remover online.';
    if(j.ok){await carregarConfigOnline(); renderMetasTab(); const restoreMsg=document.getElementById('metaSaveMsg'); if(restoreMsg) restoreMsg.textContent='✅ Configuração individual removida.';}
  }catch(e){console.log('Erro ao remover meta individual',e); if(msgEl) msgEl.textContent='⚠️ Não consegui remover online.';}
}
function renderLogsTab(){const filOpts=['<option value="">Todas as filiais</option>',...ORDEM.map(f=>`<option value="${f}">${f}</option>`)].join(''); const vendOpts=['<option value="">Todos os usuários</option>',...Array.from(new Set(COB_LOGS.map(x=>x.usuario).filter(Boolean))).sort().map(v=>`<option value="${esc(v)}">${esc(v)}</option>`)].join(''); logSection.innerHTML=`<div class="section-head"><div><h2>🧾 Histórico de cobranças</h2><div class="hint">Filtre por data, usuário ou filial. Também é possível remover lançamentos indevidos.</div></div></div><div class="glass panel"><div class="search-row"><div class="input-card"><label>Buscar cliente/título</label><input id="logQ" placeholder="Nome, título, parcela"></div><div class="input-card"><label>Data inicial</label><input id="logDe" type="date"></div><div class="input-card"><label>Data final</label><input id="logAte" type="date"></div><div class="input-card"><label>Filial</label><select id="logFil">${filOpts}</select></div></div><div class="search-row" style="margin-top:10px"><div class="input-card"><label>Usuário</label><select id="logVend">${vendOpts}</select></div><div style="display:flex;align-items:end;gap:10px"><button class="btn primary" onclick="applyLogFilter()">Filtrar</button><button class="btn soft" onclick="clearLogFilter()">Limpar</button></div></div><div id="logsList" class="logs-list"></div></div>`; applyLogFilter()}
function parseDateBR(s){if(!s) return null; const v=String(s).trim(); let m=v.match(/^(\d{2})\/(\d{2})\/(\d{4})$/); if(m){const d=new Date(Number(m[3]), Number(m[2])-1, Number(m[1])); return isNaN(d)?null:d} const d=new Date(v); return isNaN(d)?null:d}
function parseDate(s){if(!s) return null; const d=new Date(s); return isNaN(d)?null:d}
function applyLogFilter(){const q=(document.getElementById('logQ')?.value||'').toLowerCase(); const de=parseDate(document.getElementById('logDe')?.value); const ate=parseDate(document.getElementById('logAte')?.value); const fil=document.getElementById('logFil')?.value||''; const vend=document.getElementById('logVend')?.value||''; let arr=[...COB_LOGS].reverse(); arr=arr.filter(x=>{const txt=`${x.cliente||''} ${x.titulo||''} ${x.parcela||''}`.toLowerCase(); const dt=parseDate(x.server_time||x.data||''); if(q && !txt.includes(q)) return false; if(fil && String(x.filial||'')!==fil) return false; if(vend && String(x.usuario||'')!==vend) return false; if(de && (!dt || dt<de)) return false; if(ate){const end=new Date(ate); end.setHours(23,59,59,999); if(!dt || dt>end) return false;} return true}); _logFiltered=arr; const host=document.getElementById('logsList'); if(!host) return; host.innerHTML=arr.length?arr.map((x,i)=>`<div class="log-row"><div><div style="font-weight:900">${esc(x.cliente||'')}</div><div class="small muted">${esc(x.titulo||'')} · Parcela ${esc(x.parcela||'')}</div></div><div><strong>${R(x.pendente||0)}</strong><div class="small muted">${esc(x.filial||'')} · ${esc(x.usuario||'')}</div></div><div><strong>${esc(x.telefone||'')}</strong><div class="small muted">Telefone</div></div><div><strong>${esc((x.server_time||'').replace('T',' ').slice(0,16))}</strong><div class="small muted">Data</div></div><div><button class="btn danger" onclick="removerCobrancaIdx(${i})">Remover</button></div></div>`).join(''):'<div class="empty">Nenhuma cobrança encontrada para esse filtro.</div>'}
function removerCobrancaIdx(i){const x=_logFiltered[i]; if(!x) return; removerCobranca(x.id||'', x.cliente||'', x.titulo||'', x.parcela||'');}
function clearLogFilter(){['logQ','logDe','logAte'].forEach(id=>{const e=document.getElementById(id); if(e) e.value=''}); ['logFil','logVend'].forEach(id=>{const e=document.getElementById(id); if(e) e.value=''}); applyLogFilter()}

function msgMatchesUser(m){
  if(!usuarioAtual) return false;
  const targetType=String(m.target_type||'all');
  const targetId=String(m.target_id||'');
  if(usuarioAtual.tipo==='master') return true;
  if(targetType==='all') return true;
  if(targetType==='filial' && String(usuarioAtual.filial||'')===targetId) return true;
  if(targetType==='user'){
    const keys=[String(usuarioAtual.login||''), String(usuarioAtual.nome||''), `${usuarioAtual.nome||''}_${usuarioAtual.filial||''}`];
    return keys.includes(targetId);
  }
  return false;
}
function isCampaign(m){
  if((m.message_kind||'')==='campaign') return true;
  if((m.kind||'')==='campaign') return true;
  return false;
}
function isExpiredCampaign(m){
  if(!isCampaign(m) || !m.expires_at) return false;
  const d=new Date(m.expires_at);
  if(isNaN(d)) return false;
  const end=new Date(d); end.setHours(23,59,59,999);
  return end < new Date();
}
function isReadMsg(m){
  const readBy=Array.isArray(m.read_by)?m.read_by:[];
  return readBy.includes(currentUserKey());
}
async function carregarMsgsOnline(){try{const r=await fetch(API_MSG+'?_='+Date.now()); const txt=await r.text(); let j={ok:false}; try{j=JSON.parse(txt);}catch(e){} MSGS=(j.ok&&Array.isArray(j.data))?j.data:[]; if(!j.ok && txt) console.log('mensagens_api retorno:', txt);}catch(e){console.log(e); MSGS=[]} refreshBell()}
function refreshBell(){const count=(MSGS||[]).filter(m=>msgMatchesUser(m) && !m.hidden_on_master && !isExpiredCampaign(m) && !isReadMsg(m) && !isCampaign(m)).length; const bell=document.getElementById('bellCount'); if(bell) bell.textContent=count;}
function renderMsgCard(m, showRemove=false, showClear=false, compact=false){
  let media = '';
  if(m.media_url){
    if(String(m.media_type||'').startsWith('image')) media = compact ? `<div class="msg-media compact"><img src="${m.media_url}" alt=""></div>` : `<div class="msg-media"><img src="${m.media_url}" alt=""></div>`;
    else if(String(m.media_type||'').startsWith('video')) media = compact ? `<div class="msg-media compact"><video src="${m.media_url}" controls></video></div>` : `<div class="msg-media"><video src="${m.media_url}" controls></video></div>`;
    else if(String(m.media_type||'').startsWith('audio')) media = compact ? `<div class="msg-media compact"><audio src="${m.media_url}" controls></audio></div>` : `<div class="msg-media"><audio src="${m.media_url}" controls></audio></div>`;
    else media = `<div class="msg-media"><a href="${m.media_url}" target="_blank" class="btn soft">Abrir anexo</a></div>`;
  }
  const masterRead = (usuarioAtual?.tipo==='master') ? ((Array.isArray(m.read_by)&&m.read_by.length>0)?`<span class="read-chip">Lido por ${m.read_by.length}</span>`:'<span class="unread-chip">Não lido</span>') : null;
  const status = masterRead || (isReadMsg(m) ? '<span class="read-chip">Lido</span>' : '<span class="unread-chip">Não lido</span>');
  const markBtn = (!isReadMsg(m) && !isCampaign(m) && usuarioAtual?.tipo!=='master') ? `<button class="btn soft" onclick="marcarMsgLida('${m.id||''}')">✔️ Marcar como lido</button>` : '';
  const removeBtn = showRemove ? `<button class="btn danger" onclick="removerMensagem('${m.id||''}')">Remover</button>` : '';
  const clearBtn = showClear ? `<button class="btn soft" onclick="limparMensagemTela('${m.id||''}')">Limpar</button>` : '';
  const detailBtn = compact && m.media_url ? `<button class="btn soft" onclick="openMsgPreview('${m.id||''}')">🔎 Detalhes</button>` : '';
  const typeTag = isCampaign(m) ? '<span class="mini-chip" style="background:#fff7ed;border-color:#fdba74;color:#c2410c">Campanha</span>' : '<span class="mini-chip">Aviso</span>';
  return `<div class="msg-card ${isCampaign(m)?'campaign-banner':''}"><div class="msg-head"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><strong>${esc(m.title||'Aviso')}</strong>${typeTag}${status}</div><span class="small muted">${esc((m.server_time||'').replace('T',' ').slice(0,16))}</span></div><div class="small muted">Para: ${esc(m.target_label||m.target_type||'Todos')}${m.expires_at?` · Até ${esc(m.expires_at)}`:''}</div><div style="margin-top:8px;white-space:pre-wrap">${esc(m.body||'')}</div>${media}<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px">${detailBtn}${markBtn}${clearBtn}${removeBtn}</div></div>`;
}
function openBell(){
  const arr=(MSGS||[]).filter(m=>msgMatchesUser(m) && !isExpiredCampaign(m)).reverse();
  document.getElementById('bellList').innerHTML=arr.length?arr.map(m=>renderMsgCard(m,false,false,true)).join(''):'<div class="empty">Nenhum aviso para você no momento.</div>';
  document.getElementById('bellModal').classList.add('show')
}
function closeBell(){document.getElementById('bellModal').classList.remove('show')}
function renderCampaignStrip(){
  const arr=(MSGS||[]).filter(m=>msgMatchesUser(m) && isCampaign(m) && !isExpiredCampaign(m)).reverse();
  if(!arr.length) return '';
  return `<div class="campaign-banner highlight-pulse" style="background:linear-gradient(180deg,#f7f1df,#f2ead7);border:1px solid #e4d8b2"><div class="section-head" style="margin:0 0 8px"><div><h2 style="margin:0;font-size:22px">📣 Campanha ativa</h2><div class="hint">Mensagem destacada do Master</div></div><button class="btn soft" onclick="openBell()">Ver detalhes</button></div>${arr.map(m=>renderMsgCard(m,false,false,true)).join('')}</div>`;
}
function renderInboxBanner(){
  const arr=(MSGS||[]).filter(m=>msgMatchesUser(m) && !isExpiredCampaign(m));
  const campaigns=arr.filter(m=>isCampaign(m));
  const unread=arr.filter(m=>!isCampaign(m) && !isReadMsg(m)).reverse().slice(0,10);
  const pieces=[];
  if(campaigns.length) pieces.push(renderCampaignStrip());
  if(!unread.length){
    if(!pieces.length) return `<div class="glass panel msg-banner"><h3 style="margin:0 0 6px">🔔 Avisos do Master</h3><div class="small muted">Nenhum aviso novo no momento.</div></div>`;
    return pieces.join('');
  }
  pieces.push(`<div class="glass panel msg-banner highlight-pulse"><div class="section-head" style="margin:0 0 10px"><div><h2 style="font-size:20px;margin:0">🔔 Avisos do Master</h2><div class="hint">Atualizados online em tempo real.</div></div><button class="btn soft" onclick="openBell()">Ver todos</button></div>${unread.map(m=>renderMsgCard(m,false,false,true)).join('')}</div>`);
  return pieces.join('');
}
async function marcarMsgLida(id){
  const fd=new FormData(); fd.append('action','mark_read'); fd.append('id',id); fd.append('user_key',currentUserKey());
  try{
    const r=await fetch(API_MSG,{method:'POST',body:fd}); const j=await r.json();
    if(j.ok){await carregarMsgsOnline(); if(!detailScreen.classList.contains('hidden')){const titleEl=detailScreen.querySelector('.back-row h2'); const subEl=detailScreen.querySelector('.back-row .sub'); if(titleEl && subEl){}} openBell(); if(usuarioAtual?.tipo!=='master'){const ent=usuarioAtual.is_terceiro?findEntity({type:'terceiro',filial:'FTER',nome:COBRANCA10_NOME}):(usuarioAtual.is_crediarista?findEntity({type:'crediarista',filial:usuarioAtual.filial,login:usuarioAtual.login,nome:usuarioAtual.nome}):(usuarioAtual.is_gerente?findEntity({type:'filial',filial:usuarioAtual.filial}):findEntity({type:'vendedor',filial:usuarioAtual.filial,nome:usuarioAtual.nome}))); if(usuarioAtual?.is_terceiro){openThirdChargePanel()} else if(usuarioAtual?.is_crediarista){openCrediaristaPanel(usuarioAtual.login,usuarioAtual.filial,usuarioAtual.nome)} else if(ent) openEntity({type:ent.type,filial:ent.filial,nome:ent.nome});} }
    else {toast('Não consegui marcar como lido.')}
  }catch(e){toast('Não consegui marcar como lido.')}
}
function targetOptionsMsg(){
  let o='<option value="all|ALL">Todos</option>';
  ORDEM.forEach(f=>o+=`<option value="filial|${f}">Filial ${f}</option>`);

  const added = new Set();

  const addUserOpt = (value, label)=>{
    const v = String(value||'').trim();
    const l = String(label||'').trim();
    if(!v || !l) return;
    const key = `${v}__${l}`.toLowerCase();
    if(added.has(key)) return;
    added.add(key);
    o += `<option value="user|${esc(v)}">${esc(l)}</option>`;
  };

  // vendedores normais
  flattenVendedores().forEach(v=>{
    addUserOpt(`${v.nome}_${v.filial}`, `${v.nome} (${v.filial})`);
  });

  // usuários especiais das credenciais online
  const users = Object.values((AUTH_STATE && AUTH_STATE.users) || {});
  users.forEach(u=>{
    const login = String((u && u.login) || '').trim();
    const nome = String((u && u.nome) || '').trim();
    const filial = String((u && u.filial) || '').trim();

    if(u && u.is_viewer){
      addUserOpt(login || 'painel', nome || 'Painel');
      return;
    }
    if(login === 'master' || login === 'diretorcomercial') return;

    if((u && u.is_crediarista) || (u && u.is_terceiro) || (u && u.only_cobranca)){
      addUserOpt(login || nome, filial ? `${nome} (${filial})` : nome);
      return;
    }

    if(login && nome){
      addUserOpt(login, filial ? `${nome} (${filial})` : nome);
    }
  });

  if(AUTH_STATE && AUTH_STATE.director){
    addUserOpt('diretorcomercial', (AUTH_STATE.director && AUTH_STATE.director.nome) || 'Diretor Comercial');
  }
  addUserOpt('master', 'Master');

  return o;
}
function renderSenhaCard(u, isDirector=false){const key=isDirector?'diretorcomercial':u.login; const pend=(AUTH_STATE?.password_reset_requests||[]).filter(r=>String(r.login||'').toLowerCase()===String(key).toLowerCase() && String(r.status||'pendente')==='pendente').length; return `<div class="glass card" style="cursor:default"><div class="title" style="min-height:auto">${esc(isDirector?'Diretor Comercial':u.nome)} ${!isDirector?`(${u.filial||''})`:''}</div><div class="legend-inline"><span><i class="dot" style="background:${u.must_change_password?'#f59e0b':'#22c55e'}"></i>${u.must_change_password?'Precisa trocar senha':'Senha ativa'}</span>${pend?`<span><i class="dot" style="background:#ef4444"></i>${pend} solicitação(ões)</span>`:''}</div><div class="form-grid bonus" style="grid-template-columns:1.1fr .9fr;margin-top:12px"><div class="input-card"><label>Nova senha para ${esc(key)}</label><input id="pwd_${key}" placeholder="Digite a nova senha"></div><div class="input-card"><label>Ações</label><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" type="button" onclick="adminSalvarSenha('${key}')">💾 Salvar senha</button><button class="btn soft" type="button" onclick="adminMarcarTroca('${key}')">🔁 Exigir troca</button></div></div></div>${pend?`<div class="note" style="margin-top:10px">Solicitação pendente de recuperação. <button class="btn soft" style="margin-left:8px" onclick="adminResolverReset('${key}')">Resolver solicitação</button></div>`:''}<div id="pwd_msg_${key}" class="note" style="margin-top:8px"></div></div>`}

function _histDates(){return Object.keys(HIST_DASH?.dates||{}).sort().reverse()}
function _histMonths(){return Object.keys(HIST_DASH?.months_closed||{}).sort().reverse()}
function _histCurrentDate(){const el=document.getElementById('histDate'); const dates=_histDates(); return (el?.value||dates[0]||'')}
function _histCurrentMonth(){const el=document.getElementById('histMonth'); const months=_histMonths(); return (el?.value||months[0]||'')}
function _histEntityOptions(dateVal, scope){const d=HIST_DASH?.dates?.[dateVal]||{}; let opts='<option value="">Todos</option>'; if(scope==='vendedores'){Object.entries(d.vendedores||{}).sort((a,b)=>String(a[1].nome||'').localeCompare(String(b[1].nome||''),'pt-BR')).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome)} (${v.filial})</option>`})} else if(scope==='filiais'){Object.entries(d.filiais||{}).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome||k)}</option>`})} return opts}
function _histSalesDates(){return Object.keys(HIST_DASH?.sales_dates||{}).sort().reverse()}
function _histSalesMonths(){return Object.keys(HIST_DASH?.sales_months||{}).sort().reverse()}
function _histSalesCurrentDate(){return document.getElementById('histSalesDate')?.value || _histSalesDates()[0] || ''}
function _histSalesCurrentMonth(){return document.getElementById('histSalesMonth')?.value || _histSalesMonths()[0] || ''}
function _histSalesEntityOptions(dateVal, scope){const d=HIST_DASH?.sales_dates?.[dateVal]||{}; let opts='<option value="">Todos</option>'; if(scope==='vendedores'){Object.entries(d.vendedores||{}).sort((a,b)=>String(a[1].nome||'').localeCompare(String(b[1].nome||''),'pt-BR')).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome)} (${v.filial||''})</option>`})} else if(scope==='filiais'){Object.entries(d.filiais||{}).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome||k)}</option>`})} return opts}
function _histSalesMonthEntityOptions(monthVal, scope){const d=HIST_DASH?.sales_months?.[monthVal]||{}; let opts='<option value="">Todos</option>'; if(scope==='vendedores'){Object.entries(d.vendedores||{}).sort((a,b)=>String(a[1].nome||'').localeCompare(String(b[1].nome||''),'pt-BR')).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome)} (${v.filial||''})</option>`})} else if(scope==='filiais'){Object.entries(d.filiais||{}).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome||k)}</option>`})} return opts}
function updateHistSalesEntityFilter(){const dateVal=_histSalesCurrentDate(); const scope=document.getElementById('histSalesScope')?.value||'empresa'; const wrap=document.getElementById('histSalesEntityWrap'); const sel=document.getElementById('histSalesEntity'); if(!wrap||!sel) return; wrap.classList.toggle('hidden',!(scope==='vendedores'||scope==='filiais')); sel.innerHTML=_histSalesEntityOptions(dateVal, scope);}
function updateHistSalesMonthEntityFilter(){const monthVal=_histSalesCurrentMonth(); const scope=document.getElementById('histSalesMonthScope')?.value||'empresa'; const wrap=document.getElementById('histSalesMonthEntityWrap'); const sel=document.getElementById('histSalesMonthEntity'); if(!wrap||!sel) return; wrap.classList.toggle('hidden',!(scope==='vendedores'||scope==='filiais')); sel.innerHTML=_histSalesMonthEntityOptions(monthVal, scope);}
function renderSalesHistoricoTable(rows,title='💲 Histórico de vendas'){if(!rows.length) return `<div class="empty">Nenhum registro de vendas encontrado para o filtro escolhido.</div>`; return `<div class="glass panel sales-panel"><div class="section-head" style="margin:0 0 10px"><div><h2 style="font-size:18px">${title}</h2></div></div>${rows.map(r=>`<div class="log-row" style="margin-bottom:10px"><div><strong>${esc(r.nome||r.filial||'Empresa')}</strong><div class="small muted">${esc(r.filial||'Resumo')}</div></div><div><strong>${R(r.venda_realizado_total||0)}</strong><div class="small muted">Venda realizada</div></div><div><strong>${pct(r.venda_atingido_total||0)}</strong><div class="small muted">Venda atingida</div></div><div><strong>${R(r.servico_realizado_total||0)}</strong><div class="small muted">Serviço realizado</div></div><div><strong>${pct(r.servico_atingido_total||0)}</strong><div class="small muted">Serviço atingido</div></div></div>`).join('')}</div>`}
function renderHistoricoSalesResults(){const dateVal=_histSalesCurrentDate(); const scope=document.getElementById('histSalesScope')?.value||'empresa'; const entity=document.getElementById('histSalesEntity')?.value||''; const box=document.getElementById('histSalesResults'); const d=HIST_DASH?.sales_dates?.[dateVal]; if(!box) return; if(!d){box.innerHTML='<div class="empty">Nenhum histórico de vendas salvo para esta data.</div>'; return} let top=`<div class="kpis">${makeKpi('Venda realizada',R(d.empresa?.venda_realizado_total||0),'var(--orange)')}${makeKpi('Venda atingida',pct(d.empresa?.venda_atingido_total||0),'var(--orange)')}${makeKpi('Serviço realizado',R(d.empresa?.servico_realizado_total||0),'var(--orange)')}${makeKpi('Serviço atingido',pct(d.empresa?.servico_atingido_total||0),'var(--orange)')}</div>`; if(scope==='empresa'){box.innerHTML=top + renderSalesHistoricoTable([{nome:'Empresa',filial:'Resumo geral',...(d.empresa||{})}],'💲 Histórico diário de vendas da empresa'); return} const source = scope==='filiais' ? Object.entries(d.filiais||{}).map(([k,v])=>({...v,key:k})) : Object.entries(d.vendedores||{}).map(([k,v])=>({...v,key:k})); const rows=entity?source.filter(x=>x.key===entity):source; box.innerHTML=top + renderSalesHistoricoTable(rows,`💲 Histórico diário de vendas ${scope==='filiais'?'de filiais':'de vendedores'}`)}
function renderHistoricoSalesMonthResults(){const monthVal=_histSalesCurrentMonth(); const scope=document.getElementById('histSalesMonthScope')?.value||'empresa'; const entity=document.getElementById('histSalesMonthEntity')?.value||''; const box=document.getElementById('histSalesMonthResults'); const d=HIST_DASH?.sales_months?.[monthVal]; if(!box) return; if(!d){box.innerHTML='<div class="empty">Nenhum fechamento de vendas salvo para este mês.</div>'; return} let top=`<div class="kpis">${makeKpi('Venda realizada',R(d.empresa?.venda_realizado_total||0),'var(--orange)')}${makeKpi('Venda atingida',pct(d.empresa?.venda_atingido_total||0),'var(--orange)')}${makeKpi('Serviço realizado',R(d.empresa?.servico_realizado_total||0),'var(--orange)')}${makeKpi('Serviço atingido',pct(d.empresa?.servico_atingido_total||0),'var(--orange)')}</div>`; if(scope==='empresa'){box.innerHTML=top + renderSalesHistoricoTable([{nome:'Empresa',filial:'Resumo mensal',...(d.empresa||{})}],'🧡 Fechamento mensal de vendas'); return} const source = scope==='filiais' ? Object.entries(d.filiais||{}).map(([k,v])=>({...v,key:k})) : Object.entries(d.vendedores||{}).map(([k,v])=>({...v,key:k})); const rows=entity?source.filter(x=>x.key===entity):source; box.innerHTML=top + renderSalesHistoricoTable(rows,`🧡 Fechamento mensal de vendas ${scope==='filiais'?'de filiais':'de vendedores'}`)}
function _histMonthEntityOptions(monthVal, scope){const d=HIST_DASH?.months_closed?.[monthVal]||{}; let opts='<option value="">Todos</option>'; if(scope==='vendedores'){Object.entries(d.vendedores_finais||{}).sort((a,b)=>String(a[1].nome||'').localeCompare(String(b[1].nome||''),'pt-BR')).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome)} (${v.filial})</option>`})} else if(scope==='filiais'){Object.entries(d.filiais_finais||{}).forEach(([k,v])=>{opts+=`<option value="${k}">${esc(v.nome||k)}</option>`})} return opts}
function setHistMode(mode){window._histMode=mode; document.getElementById('histDailyPane')?.classList.toggle('hidden',mode!=='daily'); document.getElementById('histMonthPane')?.classList.toggle('hidden',mode!=='monthly'); document.getElementById('histSalesPane')?.classList.toggle('hidden',mode!=='sales'); document.getElementById('histTabDaily')?.classList.toggle('active',mode==='daily'); document.getElementById('histTabMonthly')?.classList.toggle('active',mode==='monthly'); document.getElementById('histTabSales')?.classList.toggle('active',mode==='sales'); if(mode==='daily'){updateHistEntityFilter(); renderHistoricoResults();} else if(mode==='monthly'){updateHistMonthEntityFilter(); renderHistoricoMonthResults();} else {updateHistSalesEntityFilter(); updateHistSalesMonthEntityFilter(); renderHistoricoSalesResults(); renderHistoricoSalesMonthResults();}}
function updateHistEntityFilter(){const dateVal=_histCurrentDate(); const scope=document.getElementById('histScope')?.value||'empresa'; const wrap=document.getElementById('histEntityWrap'); const sel=document.getElementById('histEntity'); if(!wrap||!sel) return; wrap.classList.toggle('hidden',!(scope==='vendedores'||scope==='filiais')); sel.innerHTML=_histEntityOptions(dateVal, scope);}
function updateHistMonthEntityFilter(){const monthVal=_histCurrentMonth(); const scope=document.getElementById('histMonthScope')?.value||'empresa'; const wrap=document.getElementById('histMonthEntityWrap'); const sel=document.getElementById('histMonthEntity'); if(!wrap||!sel) return; wrap.classList.toggle('hidden',!(scope==='vendedores'||scope==='filiais')); sel.innerHTML=_histMonthEntityOptions(monthVal, scope);}
function renderHistoricoTable(rows, scope, title='📋 Histórico'){if(!rows.length) return `<div class="empty">Nenhum registro encontrado para o filtro escolhido.</div>`; return `<div class="glass panel"><div class="section-head" style="margin:0 0 10px"><div><h2 style="font-size:18px">${title}</h2></div></div>${rows.map(r=>`<div class="log-row" style="margin-bottom:10px"><div><strong>${esc(r.nome||r.filial||'Empresa')}</strong><div class="small muted">${esc(r.filial||'Resumo')}</div></div><div><strong>${R(r.pendente||0)}</strong><div class="small muted">Pendente</div></div><div><strong>${R(r.recebido||0)}</strong><div class="small muted">Recebido</div></div><div><strong>${pct(r.perc_meta||0)}</strong><div class="small muted">Meta</div></div><div><strong>${R(r.grave_alvo||0)} / ${R(r.alerta_alvo||0)} / ${R(r.atencao_alvo||0)}</strong><div class="small muted">Alvos G/A/At</div></div></div>`).join('')}</div>`}
function renderHistoricoResults(){const dateVal=_histCurrentDate(); const scope=document.getElementById('histScope')?.value||'empresa'; const entity=document.getElementById('histEntity')?.value||''; const box=document.getElementById('histResults'); const d=HIST_DASH?.dates?.[dateVal]; if(!box){return} if(!d){box.innerHTML='<div class="empty">Nenhum histórico salvo para esta data.</div>'; return} let top=`<div class="kpis">${makeKpi('Pendente do dia',R(d.empresa?.pendente||0),'var(--red)')}${makeKpi('Recebido do dia',R(d.empresa?.recebido||0),'var(--green)')}${makeKpi('Grave do dia',R(d.empresa?.grave||0),'var(--red)')}${makeKpi('Alerta do dia',R(d.empresa?.alerta||0),'var(--orange)')}</div><div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0"><div><h2 style="font-size:18px">⚙️ Meta usada no dia</h2><div class="hint">Global: G ${Number(d.empresa?.config_global?.grave_pct||0)}% · A ${Number(d.empresa?.config_global?.alerta_pct||0)}% · At ${Number(d.empresa?.config_global?.atencao_pct||0)}% · Pesos ${Number(d.empresa?.config_global?.peso_grave||0)}/${Number(d.empresa?.config_global?.peso_alerta||0)}/${Number(d.empresa?.config_global?.peso_atencao||0)}</div></div><div class="small muted">${esc(dateVal)}</div></div></div>`; if(scope==='empresa'){box.innerHTML=top + renderHistoricoTable([{nome:'Empresa',filial:'Resumo geral',pendente:d.empresa?.pendente||0,recebido:d.empresa?.recebido||0,perc_meta:0,grave_alvo:0,alerta_alvo:0,atencao_alvo:0}], 'empresa','📋 Histórico diário da empresa'); return} const source = scope==='filiais' ? Object.entries(d.filiais||{}).map(([k,v])=>({...v,key:k})) : Object.entries(d.vendedores||{}).map(([k,v])=>({...v,key:k})); const rows=entity?source.filter(x=>x.key===entity):source; box.innerHTML=top + renderHistoricoTable(rows, scope, `📋 Histórico diário ${scope==='filiais'?'de filiais':'de vendedores'}`);}
function renderHistoricoMonthResults(){const monthVal=_histCurrentMonth(); const scope=document.getElementById('histMonthScope')?.value||'empresa'; const entity=document.getElementById('histMonthEntity')?.value||''; const box=document.getElementById('histMonthResults'); const d=HIST_DASH?.months_closed?.[monthVal]; if(!box){return} if(!d){box.innerHTML='<div class="empty">Nenhum fechamento mensal salvo para este mês.</div>'; return} const cfg=d.config_global_fechamento||{}; let top=`<div class="kpis">${makeKpi('Mês fechado',esc(monthVal),'var(--blue)')}${makeKpi('Último dia',esc(d.ultimo_dia_historico||'-'),'var(--blue)')}${makeKpi('Snapshot final',esc(d.snapshot_final_data||'-'),'var(--blue)')}${makeKpi('Meta mês',esc(d.meta_file||'-'),'var(--blue)')}</div><div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0"><div><h2 style="font-size:18px">📦 Fechamento mensal travado</h2><div class="hint">Global no fechamento: G ${Number(cfg.grave_pct||0)}% · A ${Number(cfg.alerta_pct||0)}% · At ${Number(cfg.atencao_pct||0)}% · Pesos ${Number(cfg.peso_grave||0)}/${Number(cfg.peso_alerta||0)}/${Number(cfg.peso_atencao||0)}</div></div><div class="small muted">Fechado em ${esc((d.fechado_em||'').replace('T',' ').slice(0,16))}</div></div></div>`;
 if(scope==='empresa'){const e=d.empresa_final||{}; box.innerHTML=top+renderHistoricoTable([{nome:'Empresa',filial:'Resultado final do mês',pendente:e.pendente||0,recebido:e.recebido||0,perc_meta:e.perc_meta||0,grave_alvo:e.grave_alvo||0,alerta_alvo:e.alerta_alvo||0,atencao_alvo:e.atencao_alvo||0}], 'empresa','📋 Resultado final mensal da empresa'); return}
 const source=scope==='filiais'?Object.entries(d.filiais_finais||{}).map(([k,v])=>({...v,key:k})) : Object.entries(d.vendedores_finais||{}).map(([k,v])=>({...v,key:k}));
 const rows=entity?source.filter(x=>x.key===entity):source; box.innerHTML=top + renderHistoricoTable(rows, scope, `📋 Resultado final mensal ${scope==='filiais'?'de filiais':'de vendedores'}`);}
function renderHistoricoTerceiro(){const box=document.getElementById('histThirdResults'); if(!box) return; const logs=(COB_LOGS||[]).filter(x=>String(x.usuario||'').toLowerCase()===COBRANCA10_LOGIN || String(x.usuario||'').toLowerCase()===COBRANCA10_NOME.toLowerCase()).slice().reverse(); const ent=thirdChargeEntity(); const top=`<div class="kpis">${makeKpi('Títulos na carteira',String((CLIENTES_TERCEIRO?.grave?.length||0)+(CLIENTES_TERCEIRO?.alerta?.length||0)+(CLIENTES_TERCEIRO?.atencao?.length||0)),'var(--blue)')}${makeKpi('Pendente',R(ent.pendente||0),'var(--red)')}${makeKpi('Recebido',R(ent.pago||0),'var(--green)')}${makeKpi('Cobranças lançadas',String(logs.length),'var(--orange)')}</div>`; const comm=renderTerceiroCommission(ent); const rows=logs.length?logs.map(x=>`<div class="log-row"><div><strong>${esc(x.cliente||'')}</strong><div class="small muted">${esc(x.titulo||'')} · Parcela ${esc(x.parcela||'')}</div></div><div><strong>${R(x.pendente||0)}</strong><div class="small muted">${esc(x.filial||'')}</div></div><div><strong>${esc((x.server_time||'').replace('T',' ').slice(0,16))}</strong><div class="small muted">Data</div></div><div><strong>${esc(x.telefone||'')}</strong><div class="small muted">Telefone</div></div></div>`).join(''):'<div class="empty">Nenhuma cobrança do Cobrança10 encontrada.</div>'; box.innerHTML=top+comm+`<div class="glass panel"><div class="section-head"><div><h2 style="font-size:18px">🤝 Cobranças Terceiro</h2><div class="hint">Histórico apenas do usuário Cobrança10.</div></div></div><div class="logs-list">${rows}</div></div>`}
function setHistMode(mode){window._histMode=mode; document.getElementById('histDailyPane')?.classList.toggle('hidden',mode!=='daily'); document.getElementById('histMonthPane')?.classList.toggle('hidden',mode!=='monthly'); document.getElementById('histSalesPane')?.classList.toggle('hidden',mode!=='sales'); document.getElementById('histThirdPane')?.classList.toggle('hidden',mode!=='third'); document.getElementById('histTabDaily')?.classList.toggle('active',mode==='daily'); document.getElementById('histTabMonthly')?.classList.toggle('active',mode==='monthly'); document.getElementById('histTabSales')?.classList.toggle('active',mode==='sales'); document.getElementById('histTabThird')?.classList.toggle('active',mode==='third'); if(mode==='daily'){updateHistEntityFilter(); renderHistoricoResults();} else if(mode==='monthly'){updateHistMonthEntityFilter(); renderHistoricoMonthResults();} else if(mode==='sales'){updateHistSalesEntityFilter(); updateHistSalesMonthEntityFilter(); renderHistoricoSalesResults(); renderHistoricoSalesMonthResults();} else {renderHistoricoTerceiro();}}
function renderHistoricoTab(){const dates=_histDates(); const months=_histMonths(); const salesDates=_histSalesDates(); const salesMonths=_histSalesMonths(); histSection.innerHTML=`<div class="section-head"><div><h2>🗂️ Histórico</h2><div class="hint">Consulte o histórico diário, vendas e os fechamentos mensais travados do Master/Diretor.</div></div></div><div class="tabs" style="justify-content:flex-start;margin:0 0 14px"><button id="histTabDaily" class="tab active" onclick="setHistMode('daily')">📅 Diário</button><button id="histTabMonthly" class="tab" onclick="setHistMode('monthly')">📦 Fechamento mensal</button><button id="histTabSales" class="tab" onclick="setHistMode('sales')">🧡 Vendas</button><button id="histTabThird" class="tab" onclick="setHistMode('third')">🤝 Cobranças Terceiro</button></div><div id="histDailyPane"><div class="glass panel" style="margin-bottom:14px"><div class="search-row"><div class="input-card"><label>Data</label><select id="histDate" onchange="updateHistEntityFilter();renderHistoricoResults()">${dates.map(d=>`<option value="${d}">${d}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histScope" onchange="updateHistEntityFilter();renderHistoricoResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histEntity" onchange="renderHistoricoResults()"><option value="">Todos</option></select></div></div></div><div id="histResults"></div></div><div id="histMonthPane" class="hidden"><div class="glass panel" style="margin-bottom:14px"><div class="search-row"><div class="input-card"><label>Mês fechado</label><select id="histMonth" onchange="updateHistMonthEntityFilter();renderHistoricoMonthResults()">${months.map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histMonthScope" onchange="updateHistMonthEntityFilter();renderHistoricoMonthResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histMonthEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histMonthEntity" onchange="renderHistoricoMonthResults()"><option value="">Todos</option></select></div></div></div><div id="histMonthResults"></div></div><div id="histSalesPane" class="hidden"><div class="glass panel" style="margin-bottom:14px"><div class="search-row"><div class="input-card"><label>Data de vendas</label><select id="histSalesDate" onchange="updateHistSalesEntityFilter();renderHistoricoSalesResults()">${salesDates.map(d=>`<option value="${d}">${d}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histSalesScope" onchange="updateHistSalesEntityFilter();renderHistoricoSalesResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histSalesEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histSalesEntity" onchange="renderHistoricoSalesResults()"><option value="">Todos</option></select></div></div></div><div id="histSalesResults"></div><div class="glass panel" style="margin:14px 0"><div class="search-row"><div class="input-card"><label>Mês de vendas</label><select id="histSalesMonth" onchange="updateHistSalesMonthEntityFilter();renderHistoricoSalesMonthResults()">${salesMonths.map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histSalesMonthScope" onchange="updateHistSalesMonthEntityFilter();renderHistoricoSalesMonthResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histSalesMonthEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histSalesMonthEntity" onchange="renderHistoricoSalesMonthResults()"><option value="">Todos</option></select></div></div></div><div id="histSalesMonthResults"></div></div><div id="histThirdPane" class="hidden"><div id="histThirdResults"></div></div>`; if(dates.length){document.getElementById('histDate').value=dates[0]} if(months.length){document.getElementById('histMonth').value=months[0]} if(salesDates.length){document.getElementById('histSalesDate').value=salesDates[0]} if(salesMonths.length){document.getElementById('histSalesMonth').value=salesMonths[0]} setHistMode(window._histMode||'daily');}
function renderSenhasTab(){
  const users=Object.values(AUTH_STATE?.users||{}).sort((a,b)=>String(a.nome||'').localeCompare(String(b.nome||''),'pt-BR'));
  const reqs=[...(AUTH_STATE?.password_reset_requests||[])].reverse();
  const resets=reqs.filter(r=>String(r.status||'pendente')==='pendente');
  const resolved=reqs.filter(r=>String(r.status||'pendente')==='resolvido');
  senhasSection.innerHTML=`<div class="section-head"><div><h2>🔐 Gerenciar senhas</h2><div class="hint">Master e Diretor Comercial podem redefinir senhas online, exigir troca no primeiro acesso e visualizar solicitações.</div></div></div>
  <div class="glass panel" style="margin-bottom:14px">
    <div class="section-head" style="margin:0 0 8px">
      <div><h2 style="font-size:18px">📩 Solicitações de recuperação</h2><div class="hint">Pedidos enviados pelo botão de recuperar senha.</div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn soft" onclick="adminLimparHistoricoReset('all')">🧹 Limpar histórico</button>
      </div>
    </div>
    ${resets.length?resets.map(r=>`<div class="log-row" style="margin-bottom:8px">
      <div><div style="font-weight:900">${esc(r.login||'')}</div><div class="small muted">${esc(r.obs||'Sem observação')}</div></div>
      <div><strong>${esc((r.created_at||'').replace('T',' ').slice(0,16))}</strong><div class="small muted">Data</div></div>
      <div><span class="mini-chip" style="background:#fff7ed;color:#b45309;border:1px solid #fdba74">Pendente</span></div>
      <div><button class="btn primary" onclick="adminResolverReset('${'${'}String(r.login||'').replace(/'/g,"\\'")${'}'}')">Resolver</button></div>
    </div>`).join(''):'<div class="empty">Nenhuma solicitação pendente.</div>'}
    ${resolved.length?`<div style="margin-top:14px"><h4 style="margin:0 0 8px">Histórico resolvido</h4>${resolved.map(r=>`<div class="log-row" style="margin-bottom:8px;opacity:.9">
      <div><div style="font-weight:900">${esc(r.login||'')}</div><div class="small muted">${esc(r.obs||'Sem observação')}</div></div>
      <div><strong>${esc(((r.resolved_at||r.created_at||'').replace('T',' ').slice(0,16)))}</strong><div class="small muted">Resolvido em</div></div>
      <div><span class="mini-chip" style="background:#ecfdf5;color:#166534;border:1px solid #86efac">Resolvido</span></div>
      <div></div>
    </div>`).join('')}</div>`:''}
  </div>
  <div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0 0 8px"><div><h2 style="font-size:18px">👑 Contas administrativas</h2></div></div>${renderSenhaCard(AUTH_STATE?.director||{login:'diretorcomercial',nome:'Diretor Comercial',must_change_password:true}, true)}</div>
  <div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0 0 8px"><div><h2 style="font-size:18px">➕ Criar usuário de cobrança</h2><div class="hint">Crie novos usuários de cobrança/crediarista direto do dashboard.</div></div></div><div class="form-grid bonus"><div class="input-card"><label>Login</label><input id="newUserLogin" placeholder="ex: crediaristaf07"></div><div class="input-card"><label>Nome</label><input id="newUserNome" placeholder="ex: CREDIARISTAF07"></div><div class="input-card"><label>Filial</label><input id="newUserFilial" placeholder="ex: F7"></div><div class="input-card"><label>Senha inicial</label><input id="newUserSenha" placeholder="mín. 4 caracteres"></div></div><div class="form-grid bonus" style="margin-top:10px"><div class="input-card"><label>Tipo</label><select id="newUserTipo"><option value="crediarista">Crediarista</option><option value="cobranca">Cobrança</option></select></div></div><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px"><button class="btn primary" onclick="adminCriarUsuarioCobranca()">💾 Criar usuário</button></div><div id="newUserMsg" class="note" style="margin-top:10px"></div></div>
  <div class="section-head"><div><h2>👥 Usuários do dashboard</h2><div class="hint">As senhas permanecem congeladas e só mudam se você alterar aqui ou se surgir um usuário novo.</div></div></div>
  <div class="grid-cards">${users.map(u=>renderSenhaCard(u,false)).join('')}</div>`;
}
async function adminSalvarSenha(login){const box=document.getElementById(`pwd_msg_${login}`); const senha=(document.getElementById(`pwd_${login}`)?.value||'').trim(); if(!senha || senha.length<4){if(box) box.textContent='Digite uma senha com pelo menos 4 caracteres.'; return;} try{const fd=new FormData(); fd.append('action','admin_set_password'); fd.append('login',login); fd.append('new_password',senha); fd.append('must_change_password','0'); const r=await fetch(API_CRED,{method:'POST',body:fd}); const j=await r.json(); if(box) box.textContent=j.ok?'✅ Senha atualizada online.':'⚠️ Não consegui atualizar a senha.'; if(j.ok){await carregarCredenciaisOnline(); renderSenhasTab();}}catch(e){if(box) box.textContent='⚠️ Não consegui atualizar a senha.';}}
async function adminMarcarTroca(login){const box=document.getElementById(`pwd_msg_${login}`); try{const fd=new FormData(); fd.append('action','admin_force_change'); fd.append('login',login); const r=await fetch(API_CRED,{method:'POST',body:fd}); const j=await r.json(); if(box) box.textContent=j.ok?'✅ Usuário marcado para trocar a senha no próximo acesso.':'⚠️ Não consegui marcar troca de senha.'; if(j.ok){await carregarCredenciaisOnline(); renderSenhasTab();}}catch(e){if(box) box.textContent='⚠️ Não consegui marcar troca de senha.';}}
async function adminResolverReset(login){try{const fd=new FormData(); fd.append('action','resolve_reset'); fd.append('login',login); const r=await fetch(API_CRED,{method:'POST',body:fd}); const j=await r.json(); if(j.ok){toast('Solicitação resolvida. Usuário terá que criar nova senha no próximo acesso.','success'); await carregarCredenciaisOnline(); renderSenhasTab();}else{toast('Não consegui resolver a solicitação.')}}catch(e){toast('Não consegui resolver a solicitação.')}}
async function adminLimparHistoricoReset(mode='resolved'){try{const fd=new FormData(); fd.append('action','clear_reset_history'); fd.append('mode',mode); const r=await fetch(API_CRED,{method:'POST',body:fd}); const j=await r.json(); if(j.ok){toast(mode==='all'?'Solicitações limpas da tela.':'Histórico de solicitações limpo.','success'); await carregarCredenciaisOnline(); renderSenhasTab();}else{toast('Não consegui limpar o histórico.')}}catch(e){toast('Não consegui limpar o histórico.')}}

async function adminCriarUsuarioCobranca(){
  const msg=document.getElementById('newUserMsg');
  const login=(document.getElementById('newUserLogin')?.value||'').trim().toLowerCase();
  const nome=(document.getElementById('newUserNome')?.value||'').trim();
  const filial=(document.getElementById('newUserFilial')?.value||'').trim().toUpperCase();
  const senha=(document.getElementById('newUserSenha')?.value||'').trim();
  const tipo=(document.getElementById('newUserTipo')?.value||'crediarista').trim();
  if(!login||!nome||!filial||!senha){ if(msg) msg.textContent='Preencha login, nome, filial e senha.'; return; }
  try{
    const fd=new FormData();
    fd.append('action','admin_create_user');
    fd.append('login',login); fd.append('nome',nome); fd.append('filial',filial); fd.append('password',senha); fd.append('tipo',tipo);
    const r=await fetch(API_CRED,{method:'POST',body:fd});
    const j=await r.json();
    if(msg) msg.textContent=j.ok?'✅ Usuário criado online.':'⚠️ Não consegui criar o usuário.';
    if(j.ok){ await carregarCredenciaisOnline(); renderSenhasTab(); }
  }catch(e){ if(msg) msg.textContent='⚠️ Não consegui criar o usuário.'; }
}

function renderAvisosTab(){
  avisosSection.innerHTML=`<div class="section-head"><div><h2>📣 Central de avisos</h2><div class="hint">Envie mensagens, imagens, vídeos e áudios para um usuário, uma filial ou todos.</div></div></div>
  ${renderCampaignStrip()}
  <div class="meta-layout">
    <div class="glass panel">
      <div class="form-grid bonus" style="grid-template-columns:1fr 1fr">
        <div class="input-card"><label>Destino</label><select id="msgTarget">${targetOptionsMsg()}</select></div>
        <div class="input-card"><label>Título</label><input id="msgTitle" placeholder="Ex: Campanha do dia"></div>
      </div>
      <div class="form-grid bonus" style="grid-template-columns:1fr 1fr;margin-top:12px">
        <div class="input-card"><label>Tipo</label><select id="msgKind"><option value="notice">Aviso</option><option value="campaign">Campanha</option></select></div>
        <div class="input-card"><label>Duração da campanha (até)</label><input id="msgExpires" type="date"></div>
      </div>
      <div class="input-card" style="margin-top:12px"><label>Mensagem</label><input id="msgBody" placeholder="Digite a mensagem"></div>
      <div class="input-card" style="margin-top:12px"><label>Anexo (imagem, vídeo ou áudio)</label><input id="msgFile" type="file" accept="image/*,video/*,audio/*"></div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px"><button class="btn primary" onclick="enviarMensagemOnline()">📨 Enviar agora</button></div>
      <div id="msgSendInfo" class="note" style="margin-top:10px"></div>
    </div>
    <div class="glass panel">
      <h3>🗂️ Histórico de avisos</h3>
      <div id="msgHistory"></div>
    </div>
  </div>`;
  renderMsgHistory();
}
function renderMsgHistory(){
  const host=document.getElementById('msgHistory'); if(!host) return;
  const q=(document.getElementById('msgDate')?.value||'');
  const arr=[...(MSGS||[])].reverse();
  const ativos=arr.filter(m=>!m.hidden_on_master && (!q || String(m.server_time||'').startsWith(q)));
  const hist=arr.filter(m=>m.hidden_on_master && (!q || String(m.server_time||'').startsWith(q)));
  host.innerHTML=`<div style="display:flex;gap:10px;align-items:end;flex-wrap:wrap;margin-bottom:10px"><div class="input-card" style="min-width:220px"><label>Filtrar por data</label><input id="msgDate" type="date" value="${q}"></div><button class="btn soft" onclick="renderMsgHistory()">Filtrar</button></div>${ativos.length?'<h4 style="margin:6px 0">Na tela</h4>'+ativos.map(m=>renderMsgCard(m,true,true)).join(''):'<div class="empty">Nenhum aviso ativo na tela.</div>'}${hist.length?'<h4 style="margin:16px 0 6px">Histórico</h4>'+hist.map(m=>renderMsgCard(m,true,false)).join(''):''}`;
}
async function enviarMensagemOnline(){
  const target=document.getElementById('msgTarget').value;
  const [target_type,target_id]=target.split('|');
  const title=document.getElementById('msgTitle').value||'Aviso';
  const body=document.getElementById('msgBody').value||'';
  const kind=document.getElementById('msgKind').value||'notice';
  const expires=document.getElementById('msgExpires').value||'';
  const file=document.getElementById('msgFile').files[0];
  const fd=new FormData();
  fd.append('target_type',target_type); fd.append('target_id',target_id); fd.append('target_label', document.getElementById('msgTarget').selectedOptions[0]?.textContent || target);
  fd.append('title',title); fd.append('body',body); fd.append('message_kind', kind); if(expires) fd.append('expires_at', expires);
  if(file) fd.append('media', file);
  try{
    const r=await fetch(API_MSG,{method:'POST',body:fd});
    const j=await r.json();
    document.getElementById('msgSendInfo').textContent=j.ok?'✅ Aviso enviado online com sucesso.':'⚠️ Não consegui enviar o aviso.';
    if(j.ok){document.getElementById('msgTitle').value=''; document.getElementById('msgBody').value=''; document.getElementById('msgFile').value=''; document.getElementById('msgExpires').value=''; await carregarMsgsOnline(); renderMsgHistory(); renderList();}
  }catch(e){document.getElementById('msgSendInfo').textContent='⚠️ Não consegui enviar o aviso.'}
}
async function removerMensagem(id){
  if(!confirm('Remover esta mensagem?')) return;
  const fd=new FormData(); fd.append('action','delete'); fd.append('id',id);
  try{const r=await fetch(API_MSG,{method:'POST',body:fd}); const j=await r.json(); if(j.ok){toast('Mensagem removida.','success'); await carregarMsgsOnline(); renderMsgHistory(); renderList();}else{toast('Não consegui remover a mensagem.')}}catch(e){toast('Não consegui remover a mensagem.')}}
async function limparMensagemTela(id){
  const fd=new FormData(); fd.append('action','archive_master'); fd.append('id',id);
  try{const r=await fetch(API_MSG,{method:'POST',body:fd}); const j=await r.json(); if(j.ok){toast('Mensagem removida da tela e enviada ao histórico.','success'); await carregarMsgsOnline(); renderMsgHistory(); renderList();}else{toast('Não consegui limpar a mensagem.')}}catch(e){toast('Não consegui limpar a mensagem.')}}
async function openPrimeiroAcesso(prefillLogin=''){document.getElementById('faLogin').value=prefillLogin||document.getElementById('loginUser').value||''; document.getElementById('faCurrentPass').value=document.getElementById('loginPass').value||''; document.getElementById('faNewPass').value=''; document.getElementById('faNewPass2').value=''; document.getElementById('faMsg').textContent=''; document.getElementById('firstAccessModal').classList.add('show')}
function closeFirstAccess(){document.getElementById('firstAccessModal').classList.remove('show')}
function openRecuperarSenha(){document.getElementById('recLogin').value=document.getElementById('loginUser').value||''; document.getElementById('recObs').value=''; document.getElementById('recMsg').textContent=''; document.getElementById('recoverModal').classList.add('show')}
function closeRecover(){document.getElementById('recoverModal').classList.remove('show')}
async function enviarRecuperacaoSenha(){const login=(document.getElementById('recLogin').value||'').trim().toLowerCase(); const obs=(document.getElementById('recObs').value||'').trim(); const box=document.getElementById('recMsg'); if(!login){box.textContent='Informe o usuário.'; return;} try{const fd=new FormData(); fd.append('action','request_reset'); fd.append('login',login); fd.append('obs',obs); const r=await fetch(API_CRED,{method:'POST',body:fd}); const j=await r.json(); box.textContent=j.ok?'✅ Solicitação enviada ao Master.':'⚠️ Não consegui enviar a solicitação.';}catch(e){box.textContent='⚠️ Não consegui enviar a solicitação.';}}
async function salvarPrimeiroAcesso(){const login=(document.getElementById('faLogin').value||'').trim().toLowerCase(); const atual=(document.getElementById('faCurrentPass').value||'').trim(); const nova=(document.getElementById('faNewPass').value||'').trim(); const nova2=(document.getElementById('faNewPass2').value||'').trim(); const box=document.getElementById('faMsg'); box.textContent=''; if(!login||!atual||!nova||!nova2){box.textContent='Preencha todos os campos.'; return;} if(nova.length<4){box.textContent='A nova senha deve ter pelo menos 4 caracteres.'; return;} if(nova!==nova2){box.textContent='A confirmação da senha não confere.'; return;} const auth=getAuthUser(login); if(!auth || String(auth.password)!==atual){box.textContent='Usuário ou senha atual inválidos.'; return;} try{const fd=new FormData(); fd.append('action','change_password'); fd.append('login',login); fd.append('current_password',atual); fd.append('new_password',nova); const r=await fetch(API_CRED,{method:'POST',body:fd}); const j=await r.json(); box.textContent=j.ok?'✅ Senha alterada com sucesso. Entre com a nova senha.':'⚠️ Não consegui alterar a senha.'; if(j.ok){await carregarCredenciaisOnline(); document.getElementById('loginPass').value=''; setTimeout(()=>{closeFirstAccess();},700);}}catch(e){box.textContent='⚠️ Não consegui alterar a senha.';}}
async function fazerLogin(){const u=(document.getElementById('loginUser').value||'').trim().toLowerCase(); const s=(document.getElementById('loginPass').value||'').trim(); const msg=document.getElementById('loginMsg'); msg.textContent=''; if(!u || !s){msg.textContent='Informe usuário e senha.'; return;} await carregarCredenciaisOnline(); if(u===LOGIN_MASTER.toLowerCase() && s===SENHA_MASTER){usuarioAtual={tipo:'master',nome:'Master',roleLabel:'Master'}; saveSession(); return abrirApp()} if(u===LOGIN_DIRETOR.toLowerCase()){const authDir=getAuthUser(u); const senhaDir=authDir?.password || SENHA_DIRETOR; if(String(senhaDir)===s){ if(authDir?.must_change_password){ msg.textContent='Primeiro acesso do Diretor Comercial: defina uma nova senha.'; return openPrimeiroAcesso(u);} usuarioAtual={tipo:'master',nome:'Diretor Comercial',roleLabel:'Diretor Comercial'}; saveSession(); return abrirApp(); }} const auth=getAuthUser(u); if(CREDS[u] && auth && String(auth.password)===s){ if(auth.must_change_password){ msg.textContent='Primeiro acesso: defina sua nova senha.'; return openPrimeiroAcesso(u);} usuarioAtual={tipo:'user',login:u,...CREDS[u]}; saveSession(); return abrirApp()} msg.textContent='Login ou senha inválidos.'}
async function abrirApp(){await carregarCredenciaisOnline(); await carregarConfigOnline(); await carregarHistoricoOnline(); await carregarCobrancasOnline(); await carregarMsgsOnline(); loginScreen.classList.add('hidden'); app.classList.remove('hidden'); if(usuarioAtual.tipo==='master'){document.getElementById('kpis').classList.remove('hidden'); renderKPIs(); const isDiretor=usuarioAtual?.roleLabel==='Diretor Comercial'; userBadge.textContent=isDiretor?'👑 Diretor Comercial':'👑 Master'; masterTabs.classList.remove('hidden'); document.querySelectorAll('#masterTabs .tab').forEach(btn=>{const t=btn.dataset.tab; btn.classList.toggle('hidden', isDiretor && ['cobrancas','senhas'].includes(t));}); setMainTab('vendedores')} else if(usuarioAtual.is_viewer){document.getElementById('kpis').classList.remove('hidden'); renderKPIs(); userBadge.textContent='📺 Painel'; masterTabs.classList.add('hidden'); mainFilters.classList.add('hidden'); listSection.classList.add('hidden'); metaSection.classList.add('hidden'); logSection.classList.add('hidden'); avisosSection.classList.add('hidden'); senhasSection.classList.add('hidden'); histSection.classList.add('hidden'); document.getElementById('mainScreen').classList.remove('hidden'); detailScreen.classList.add('hidden');} else {document.getElementById('kpis').classList.add('hidden'); userBadge.textContent=usuarioAtual.is_terceiro?`🤝 ${usuarioAtual.nome}`:(usuarioAtual.is_crediarista?`🧾 ${usuarioAtual.nome}`:(usuarioAtual.is_gerente?`🏬 ${usuarioAtual.filial}`:`👤 ${usuarioAtual.nome}`)); masterTabs.classList.add('hidden'); mainFilters.classList.add('hidden'); const ent=usuarioAtual.is_terceiro?findEntity({type:'terceiro',filial:'FTER',nome:COBRANCA10_NOME}):(usuarioAtual.is_crediarista?findEntity({type:'crediarista',filial:usuarioAtual.filial,login:usuarioAtual.login,nome:usuarioAtual.nome}):(usuarioAtual.is_gerente?findEntity({type:'filial',filial:usuarioAtual.filial}):findEntity({type:'vendedor',filial:usuarioAtual.filial,nome:usuarioAtual.nome}))); document.getElementById('mainScreen').classList.add('hidden'); detailScreen.classList.remove('hidden'); if(usuarioAtual.is_terceiro){openThirdChargePanel()} else if(usuarioAtual.is_crediarista){openCrediaristaPanel(usuarioAtual.login,usuarioAtual.filial,usuarioAtual.nome)} else if(ent) openEntity({type:ent.type,filial:ent.filial,nome:ent.nome,login:ent.login}) }}
function logout(){clearSession(); location.reload()}
window.addEventListener('load',async ()=>{
  const u=document.getElementById('loginUser');
  const p=document.getElementById('loginPass');
  if(u) u.focus();
  if(u) u.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault(); if(p) p.focus();}});
  if(p) p.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault(); fazerLogin();}});
  await carregarCredenciaisOnline();
  try{
    const verDash = await fetchJsonNoCache('dashboard_version.json');
    const stampDash = String((verDash && (verDash.updated_at_label||verDash.updated_at)) || '');
    if(stampDash) window.__dashboardUpdatedAtLabel = stampDash;
  }catch(_e){}
  try{
    const verSales = await fetchJsonNoCache('sales_version.json');
    const stampSales = String((verSales && (verSales.updated_at_label||verSales.updated_at)) || '');
    if(stampSales) window.__salesUpdatedAtLabel = stampSales;
  }catch(_e){}
  if(restoreSession()){abrirApp();}
  setInterval(pollSalesLive,60000);
  setInterval(pollDashboardLiveReload,60000);
  setTimeout(pollSalesLive,3000);
  setTimeout(pollDashboardLiveReload,5000);
})
</script>
</body>
</html>
"""

html = template
repls = {
    '__JS_CREDS__': js_creds,
    '__JS_AUTH_STATE__': js_auth_state,
    '__JS_TODOS__': js_todos,
    '__JS_FILIAIS__': js_filiais,
    '__JS_CLIENTES__': js_clientes,
    '__JS_CLIENTES_VEND__': js_clientes_vend,
    '__JS_CLIENTES_TERCEIRO__': js_clientes_terceiro,
    '__JS_CLIENTES_CREDIARISTA__': js_clientes_crediarista,
    '__JS_RECEBIMENTOS__': js_recebimentos,
    '__JS_RECEBIMENTOS_TERCEIRO__': js_recebimentos_terceiro,
    '__JS_RECEBIMENTOS_CREDIARISTA__': js_recebimentos_crediarista,
    '__JS_CREDIARISTAS_MAP__': js_crediaristas_map,
    '__JS_METAS_VENDAS__': js_metas_vendas,
    '__JS_MARGENS_BRUTAS__': js_margens_brutas,
    '__JS_SALES_EMPRESA__': js_sales_empresa,
    '__JS_RENT_EMPRESA__': js_rent_empresa,
    '__JS_SERVICOS_RELATORIO__': js_servicos_relatorio,
    '__CONFIG_META__': json.dumps(CONFIG_META, ensure_ascii=False),
    '__CONFIG_META_IND__': json.dumps(CONFIG_META_IND, ensure_ascii=False),
    '__JS_DESTAQUE__': js_destaque,
    '__JS_HIST_DASH__': js_hist_dash,
    '__LOGIN_MASTER__': json.dumps(LOGIN_MASTER, ensure_ascii=False),
    '__SENHA_MASTER__': json.dumps(SENHA_MASTER, ensure_ascii=False),
    '__LOGIN_DIRETOR__': json.dumps(LOGIN_DIRETOR, ensure_ascii=False),
    '__SENHA_DIRETOR__': json.dumps(SENHA_DIRETOR, ensure_ascii=False),
    '__LOGIN_PAINEL__': json.dumps(LOGIN_PAINEL, ensure_ascii=False),
    '__SENHA_PAINEL__': json.dumps(SENHA_PAINEL, ensure_ascii=False),
    '__ORDEM__': json.dumps(ORDEM_FILIAIS, ensure_ascii=False),
    '__TOTAL_P__': json.dumps(total_dash_p, ensure_ascii=False),
    '__TOTAL_PG__': json.dumps(total_dash_pg, ensure_ascii=False),
    '__LARANJITO__': _laranjito,
    '__LOGO__': _logo,
    '__PERIODO__': f"{data_inicio} a {data_fim}",
}
for k,v in repls.items():
    html = html.replace(k, v)

html_path = os.path.join(pasta, 'dashboard_vendedores.html')
with open(html_path, 'w', encoding='utf-8') as f:
    f.write(html)
print(f'🌐 HTML salvo: {html_path}')

# =========================================
# 📡 APIs PHP PARA LOG ONLINE / CONFIG ONLINE
# =========================================
COBRANCAS_API_PHP = r"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
$file = __DIR__ . '/cobrancas_log.json';
if (!file_exists($file)) file_put_contents($file, '[]');
$data = json_decode(@file_get_contents($file), true);
if (!is_array($data)) $data = [];
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
  echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit;
}
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  $payload = json_decode(file_get_contents('php://input'), true);
  if (!is_array($payload)) { echo json_encode(['ok'=>false,'error'=>'payload_invalido']); exit; }
  if (($payload['action'] ?? '') === 'delete') {
    $id = $payload['id'] ?? '';
    $cliente = $payload['cliente'] ?? '';
    $titulo = $payload['titulo'] ?? '';
    $parcela = $payload['parcela'] ?? '';
    $novo = [];
    foreach($data as $item){
      $sameId = ($id !== '' && (string)($item['id'] ?? '') === (string)$id);
      $sameComposite = ($cliente !== '' && (string)($item['cliente'] ?? '') === (string)$cliente && (string)($item['titulo'] ?? '') === (string)$titulo && (string)($item['parcela'] ?? '') === (string)$parcela);
      if(!$sameId && !$sameComposite) $novo[] = $item;
    }
    file_put_contents($file, json_encode($novo, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
    echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
  }
  if (empty($payload['id'])) $payload['id'] = uniqid('cob_', true);
  $payload['server_time'] = date('c');
  $data[] = $payload;
  file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
  echo json_encode(['ok'=>true,'id'=>$payload['id']], JSON_UNESCAPED_UNICODE); exit;
}
echo json_encode(['ok'=>false,'error'=>'metodo_nao_suportado'], JSON_UNESCAPED_UNICODE);
?>"""

CONFIG_META_API_PHP = r"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
$file = __DIR__ . '/config_meta.json';
if (!file_exists($file)) file_put_contents($file, '{"global":{},"individual":{}}');
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
  $data = json_decode(@file_get_contents($file), true);
  if (!is_array($data)) $data = ['global'=>[], 'individual'=>[]];
  if (!isset($data['global']) || !is_array($data['global'])) $data['global'] = [];
  if (!isset($data['individual']) || !is_array($data['individual'])) $data['individual'] = [];
  echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit;
}
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  $payload = json_decode(file_get_contents('php://input'), true);
  if (!is_array($payload)) { echo json_encode(['ok'=>false,'error'=>'payload_invalido']); exit; }
  $global = isset($payload['global']) && is_array($payload['global']) ? $payload['global'] : [];
  $individual = isset($payload['individual']) && is_array($payload['individual']) ? $payload['individual'] : [];
  $save = ['global'=>$global, 'individual'=>$individual];
  file_put_contents($file, json_encode($save, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
  echo json_encode(['ok'=>true,'saved_keys'=>count($individual)], JSON_UNESCAPED_UNICODE); exit;
}
echo json_encode(['ok'=>false,'error'=>'metodo_nao_suportado'], JSON_UNESCAPED_UNICODE);
?>"""

MESSAGES_API_PHP = r"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
$file = __DIR__ . '/mensagens_log.json';
$uploadDir = __DIR__ . '/uploads_mural';
if (!file_exists($uploadDir)) @mkdir($uploadDir, 0777, true);
if (!file_exists($file)) file_put_contents($file, '[]');
$data = json_decode(@file_get_contents($file), true);
if (!is_array($data)) $data = [];
if ($_SERVER['REQUEST_METHOD'] === 'GET') {
  echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit;
}
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
  if ((($_POST['action'] ?? '') === 'delete')) {
    $id = $_POST['id'] ?? '';
    if (!$id) { echo json_encode(['ok'=>false,'error'=>'id_obrigatorio']); exit; }
    $novo = [];
    foreach($data as $item){ if((string)($item['id'] ?? '') !== (string)$id) $novo[] = $item; }
    file_put_contents($file, json_encode($novo, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
    echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
  }
  if ((($_POST['action'] ?? '') === 'archive_master')) {
    $id = $_POST['id'] ?? '';
    foreach($data as &$item){ if((string)($item['id'] ?? '') === (string)$id) { $item['hidden_on_master'] = true; } }
    file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
    echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
  }
  if ((($_POST['action'] ?? '') === 'mark_read')) {
    $id = $_POST['id'] ?? '';
    $userKey = $_POST['user_key'] ?? '';
    if (!$id || !$userKey) { echo json_encode(['ok'=>false,'error'=>'parametros_obrigatorios']); exit; }
    foreach($data as &$item){
      if ((string)($item['id'] ?? '') === (string)$id) {
        if (!isset($item['read_by']) || !is_array($item['read_by'])) $item['read_by'] = [];
        if (!in_array($userKey, $item['read_by'])) $item['read_by'][] = $userKey;
      }
    }
    file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
    echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
  }
  $item = [
    'id' => uniqid('msg_', true),
    'target_type' => $_POST['target_type'] ?? 'all',
    'target_id' => $_POST['target_id'] ?? 'ALL',
    'target_label' => $_POST['target_label'] ?? ($_POST['target_id'] ?? 'ALL'),
    'title' => $_POST['title'] ?? 'Aviso',
    'body' => $_POST['body'] ?? '',
    'message_kind' => $_POST['message_kind'] ?? 'notice',
    'expires_at' => $_POST['expires_at'] ?? '',
    'read_by' => [],
    'server_time' => date('c')
  ];
  if (!empty($_FILES['media']['name'])) {
    $name = preg_replace('/[^A-Za-z0-9._-]/', '_', basename($_FILES['media']['name']));
    $dest = $uploadDir . '/' . time() . '_' . $name;
    if (move_uploaded_file($_FILES['media']['tmp_name'], $dest)) {
      $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
      $base = $scheme . '://' . $_SERVER['HTTP_HOST'] . rtrim(dirname($_SERVER['SCRIPT_NAME']), '/\\');
      $item['media_url'] = $base . '/uploads_mural/' . basename($dest);
      $item['media_type'] = $_FILES['media']['type'] ?? '';
    }
  }
  $data[] = $item;
  file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
  echo json_encode(['ok'=>true,'data'=>$item], JSON_UNESCAPED_UNICODE); exit;
}
echo json_encode(['ok'=>false,'error'=>'metodo_nao_suportado'], JSON_UNESCAPED_UNICODE);
?>"""


CREDENCIAIS_API_PHP = r"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }

$file = __DIR__ . '/credenciais_dashboard.json';
$resetLog = __DIR__ . '/password_reset_requests.json';
$masterEmail = 'sac@moveisdolar.com.br';

if (!file_exists($file)) file_put_contents($file, json_encode(['users'=>new stdClass(),'director'=>new stdClass(),'password_reset_requests'=>[]], JSON_UNESCAPED_UNICODE));
if (!file_exists($resetLog)) file_put_contents($resetLog, '[]');

$data = json_decode(@file_get_contents($file), true);
if (!is_array($data)) $data = ['users'=>[], 'director'=>[], 'password_reset_requests'=>[]];
if (!isset($data['users']) || !is_array($data['users'])) $data['users'] = [];
if (!isset($data['director']) || !is_array($data['director'])) $data['director'] = [];
if (!isset($data['password_reset_requests']) || !is_array($data['password_reset_requests'])) $data['password_reset_requests'] = [];

function save_all($file, $data){ file_put_contents($file, json_encode($data, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE)); }
function resolve_login_ref(&$data, $login){
  $login = strtolower(trim((string)$login));
  if ($login === 'diretorcomercial') return ['type'=>'director', 'key'=>'director'];
  foreach(($data['users'] ?? []) as $k=>$u){ if(strtolower((string)$k)===$login || strtolower((string)($u['login'] ?? ''))===$login) return ['type'=>'user', 'key'=>$k]; }
  return null;
}
function mark_reset_resolved(&$data, $login){ foreach(($data['password_reset_requests'] ?? []) as &$req){ if (strtolower((string)($req['login'] ?? ''))===strtolower((string)$login) && (($req['status'] ?? 'pendente')==='pendente')) $req['status']='resolvido'; } }

if ($_SERVER['REQUEST_METHOD'] === 'GET') { echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit; }
$action = $_POST['action'] ?? '';
if ($action === 'change_password') {
  $login = strtolower(trim($_POST['login'] ?? '')); $current = strval($_POST['current_password'] ?? ''); $new = strval($_POST['new_password'] ?? '');
  if (!$login || !$current || !$new) { echo json_encode(['ok'=>false,'error'=>'parametros_obrigatorios']); exit; }
  if (strlen($new) < 4) { echo json_encode(['ok'=>false,'error'=>'senha_curta']); exit; }
  $ref = resolve_login_ref($data, $login); if (!$ref) { echo json_encode(['ok'=>false,'error'=>'login_nao_encontrado']); exit; }
  if ($ref['type'] === 'director') { if (($data['director']['password'] ?? '') !== $current) { echo json_encode(['ok'=>false,'error'=>'senha_atual_invalida']); exit; } $data['director']['password']=$new; $data['director']['must_change_password']=false; }
  else { if (($data['users'][$ref['key']]['password'] ?? '') !== $current) { echo json_encode(['ok'=>false,'error'=>'senha_atual_invalida']); exit; } $data['users'][$ref['key']]['password']=$new; $data['users'][$ref['key']]['must_change_password']=false; }
  mark_reset_resolved($data, $login); save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
if ($action === 'admin_set_password') {
  $login = strtolower(trim($_POST['login'] ?? '')); $new = strval($_POST['new_password'] ?? ''); $must = ($_POST['must_change_password'] ?? '0') === '1';
  if (!$login || !$new || strlen($new) < 4) { echo json_encode(['ok'=>false,'error'=>'dados_invalidos']); exit; }
  $ref = resolve_login_ref($data, $login); if (!$ref) { echo json_encode(['ok'=>false,'error'=>'login_nao_encontrado']); exit; }
  if ($ref['type'] === 'director') { $data['director']['password']=$new; $data['director']['must_change_password']=$must; }
  else { $data['users'][$ref['key']]['password']=$new; $data['users'][$ref['key']]['must_change_password']=$must; }
  mark_reset_resolved($data, $login); save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
if ($action === 'admin_force_change') {
  $login = strtolower(trim($_POST['login'] ?? '')); if (!$login) { echo json_encode(['ok'=>false,'error'=>'login_obrigatorio']); exit; }
  $ref = resolve_login_ref($data, $login); if (!$ref) { echo json_encode(['ok'=>false,'error'=>'login_nao_encontrado']); exit; }
  if ($ref['type'] === 'director') $data['director']['must_change_password']=true; else $data['users'][$ref['key']]['must_change_password']=true;
  mark_reset_resolved($data, $login); save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
if ($action === 'admin_create_user') {
  $login = strtolower(trim($_POST['login'] ?? '')); $nome = trim($_POST['nome'] ?? ''); $filial = strtoupper(trim($_POST['filial'] ?? '')); $senha = strval($_POST['password'] ?? ''); $tipo = strtolower(trim($_POST['tipo'] ?? 'crediarista'));
  if (!$login || !$nome || !$filial || !$senha || strlen($senha) < 4) { echo json_encode(['ok'=>false,'error'=>'dados_invalidos']); exit; }
  if (resolve_login_ref($data, $login)) { echo json_encode(['ok'=>false,'error'=>'login_ja_existe']); exit; }
  $data['users'][$login] = ['login'=>$login,'nome'=>$nome,'filial'=>$filial,'password'=>$senha,'must_change_password'=>true,'is_gerente'=>false,'is_terceiro'=>($tipo==='cobranca'),'is_crediarista'=>($tipo!=='cobranca'),'only_cobranca'=>true];
  save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
if ($action === 'resolve_reset') {
  $login = strtolower(trim($_POST['login'] ?? '')); if (!$login) { echo json_encode(['ok'=>false,'error'=>'login_obrigatorio']); exit; }
  $ref = resolve_login_ref($data, $login); if (!$ref) { echo json_encode(['ok'=>false,'error'=>'login_nao_encontrado']); exit; }
  if ($ref['type'] === 'director') $data['director']['must_change_password']=true; else $data['users'][$ref['key']]['must_change_password']=true;
  foreach(($data['password_reset_requests'] ?? []) as &$req){
    if (strtolower((string)($req['login'] ?? ''))===strtolower((string)$login) && (($req['status'] ?? 'pendente')==='pendente')) {
      $req['status']='resolvido';
      $req['resolved_at']=date('c');
    }
  }
  save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
if ($action === 'clear_reset_history') {
  $mode = strtolower(trim($_POST['mode'] ?? 'resolved'));
  if ($mode === 'all') $data['password_reset_requests'] = [];
  else $data['password_reset_requests'] = array_values(array_filter(($data['password_reset_requests'] ?? []), function($r){ return (($r['status'] ?? 'pendente') !== 'resolvido'); }));
  save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
if ($action === 'request_reset') {
  $login = strtolower(trim($_POST['login'] ?? '')); $obs = trim($_POST['obs'] ?? ''); if (!$login) { echo json_encode(['ok'=>false,'error'=>'login_obrigatorio']); exit; }
  $req = ['id'=>uniqid('reset_', true), 'login'=>$login, 'obs'=>$obs, 'created_at'=>date('c'), 'status'=>'pendente'];
  $data['password_reset_requests'][] = $req; save_all($file, $data);
  $log = json_decode(@file_get_contents($resetLog), true); if (!is_array($log)) $log = []; $log[] = $req; file_put_contents($resetLog, json_encode($log, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE));
  $assunto = 'Dashboard MDL - solicitacao de recuperacao de senha'; $mensagem = "Usuario: {$login}\nObservacao: {$obs}\nData: {$req['created_at']}\n"; $headers = "From: no-reply@moveisdolar.com.br\r\n"; $mail_ok = @mail($masterEmail, $assunto, $mensagem, $headers);
  echo json_encode(['ok'=>true,'email_sent'=>$mail_ok], JSON_UNESCAPED_UNICODE); exit;
}
echo json_encode(['ok'=>false,'error'=>'acao_nao_suportada'], JSON_UNESCAPED_UNICODE);
?>"""

HISTORICO_API_PHP = r"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
$file = __DIR__ . '/historico_dashboard.json';
if (!file_exists($file)) file_put_contents($file, '{"dates":{},"months_closed":{}}');
$data = json_decode(@file_get_contents($file), true);
if (!is_array($data)) $data = ['dates'=>[], 'months_closed'=>[]];
echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit;
?>"""

# =========================================
# 📤 UPLOAD AUTOMÁTICO VIA FTP
# =========================================
import ftplib
from io import BytesIO

FTP_HOST  = 'moveisdolar.com.br'
FTP_USER  = 'moveisdolar3'
FTP_PASS  = 'Deg27ll02mdl2301#'
FTP_DIR   = '/public_html/colaborador'

if FTP_USER and FTP_PASS:
    try:
        print('\n📤 Enviando arquivos para o servidor FTP...')
        ftp = ftplib.FTP()
        ftp.connect(FTP_HOST, 21, timeout=30)
        ftp.login(FTP_USER, FTP_PASS)
        ftp.encoding = 'utf-8'
        try:
            ftp.cwd(FTP_DIR)
        except Exception:
            try:
                ftp.mkd(FTP_DIR)
            except Exception:
                pass
            ftp.cwd(FTP_DIR)
        with open(html_path, 'rb') as f_html:
            ftp.storbinary('STOR dashboard_vendedores.html', f_html)
        ftp.storbinary('STOR cobrancas_api.php', BytesIO(COBRANCAS_API_PHP.encode('utf-8')))
        ftp.storbinary('STOR config_meta_api.php', BytesIO(CONFIG_META_API_PHP.encode('utf-8')))
        ftp.storbinary('STOR mensagens_api.php', BytesIO(MESSAGES_API_PHP.encode('utf-8')))
        ftp.storbinary('STOR credenciais_api.php', BytesIO(CREDENCIAIS_API_PHP.encode('utf-8')))
        ftp.storbinary('STOR historico_api.php', BytesIO(HISTORICO_API_PHP.encode('utf-8')))
        try:
            with open(_config_meta_path, 'rb') as f_cfg:
                ftp.storbinary('STOR config_meta.json', f_cfg)
        except Exception:
            ftp.storbinary('STOR config_meta.json', BytesIO(b'{"global":{},"individual":{}}'))
        try:
            with open(cred_state_path, 'rb') as f_credstate:
                ftp.storbinary('STOR credenciais_dashboard.json', f_credstate)
        except Exception:
            ftp.storbinary('STOR credenciais_dashboard.json', BytesIO(b'{"users":{},"director":{},"password_reset_requests":[]}'))
        try:
            with open(_hist_dash_path, 'rb') as f_hist:
                ftp.storbinary('STOR historico_dashboard.json', f_hist)
        except Exception:
            ftp.storbinary('STOR historico_dashboard.json', BytesIO(b'{"dates":{},"months_closed":{}}'))
        try:
            with open(COMISSAO_HIST_PATH, 'rb') as f_ch:
                ftp.storbinary('STOR historico_comissao_cobranca.json', f_ch)
        except Exception:
            ftp.storbinary('STOR historico_comissao_cobranca.json', BytesIO(b'{"months":{}}'))
        try:
            with open(_fechamento_path, 'rb') as f_fech:
                ftp.storbinary('STOR fechamentos_mensais.json', f_fech)
        except Exception:
            ftp.storbinary('STOR fechamentos_mensais.json', BytesIO(b'{"months":{}}'))
        try:
            if metas_vendas_info.get('json_path') and os.path.exists(metas_vendas_info['json_path']):
                with open(metas_vendas_info['json_path'], 'rb') as f_meta_json:
                    ftp.storbinary('STOR metas_vendas_mes_atual.json', f_meta_json)
            if metas_vendas_info.get('xlsx_path') and os.path.exists(metas_vendas_info['xlsx_path']):
                with open(metas_vendas_info['xlsx_path'], 'rb') as f_meta_xlsx:
                    ftp.storbinary('STOR metas_vendas_mes_atual.xlsx', f_meta_xlsx)
        except Exception as e_meta_ftp:
            print(f'⚠️ Erro enviando arquivos de metas/vendas: {e_meta_ftp}')
        try:
            if margens_brutas_info.get('json_path') and os.path.exists(margens_brutas_info['json_path']):
                with open(margens_brutas_info['json_path'], 'rb') as f_margem_json:
                    ftp.storbinary('STOR margens_brutas_mes_atual.json', f_margem_json)
            if margens_brutas_info.get('xlsx_path') and os.path.exists(margens_brutas_info['xlsx_path']):
                with open(margens_brutas_info['xlsx_path'], 'rb') as f_margem_xlsx:
                    ftp.storbinary('STOR margens_brutas_mes_atual.xlsx', f_margem_xlsx)
        except Exception as e_margem_ftp:
            print(f'⚠️ Erro enviando arquivos de margens/rentabilidade: {e_margem_ftp}')
        try:
            ftp.size('cobrancas_log.json')
        except Exception:
            ftp.storbinary('STOR cobrancas_log.json', BytesIO(b'[]'))
        try:
            ftp.size('mensagens_log.json')
        except Exception:
            ftp.storbinary('STOR mensagens_log.json', BytesIO(b'[]'))
        try:
            _dashboard_ver = json.dumps({'updated_at': now_brasilia().isoformat(), 'updated_at_label': now_brasilia().strftime('%d/%m/%Y %H:%M:%S'), 'timezone': 'America/Sao_Paulo', 'scope': 'dashboard_full'}, ensure_ascii=False).encode('utf-8')
            ftp.storbinary('STOR dashboard_version.json', BytesIO(_dashboard_ver))
            ftp.storbinary('STOR sales_version.json', BytesIO(_dashboard_ver))
        except Exception as e_ver_ftp:
            print(f'⚠️ Erro enviando arquivos de versão: {e_ver_ftp}')
        ftp.quit()
        print('✅ Upload concluído → https://moveisdolar.com.br/colaborador/')
    except Exception as e:
        print(f'⚠️ Erro no upload FTP: {e}')
else:
    print('\nℹ️ FTP não configurado. Envie manualmente:')
    print(f'   {html_path} → {FTP_DIR}/dashboard_vendedores.html')

print('\n🔥 FINALIZADO!')
print("🔎 Fechamento automático em ambiente Railway")
driver.quit()