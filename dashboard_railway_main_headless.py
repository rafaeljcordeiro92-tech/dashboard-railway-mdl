# VERSAO: COBRANCA10_V9_BONUS_90_COMISSAO_REAIS
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
import shutil
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
IS_RAILWAY = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RUN_ON_RAILWAY") == "1")
pasta = os.path.dirname(os.path.abspath(__file__))
download_dir = pasta if not IS_RAILWAY else tempfile.gettempdir()

# ===== RELATÓRIOS AUDITÁVEIS DA ÚLTIMA EXECUÇÃO
# No Railway, downloads em /tmp somem quando o container reinicia.
# Por isso copiamos os XLS/JSON para /app/relatorios_publicos e depois publicamos no FTP.
RELATORIOS_DIR = os.path.join(pasta, "relatorios_publicos")
os.makedirs(RELATORIOS_DIR, exist_ok=True)
RELATORIOS_PUBLIC_BASE = "https://moveisdolar.com.br/colaborador/relatorios"
relatorios_publicos = {
    "principal_xls": None,
    "quitados_original_xls": None,
    "quitados_processado_xlsx": None,
    "quitados_json": None,
    "zip": None,
}

def _copiar_relatorio_publico(src, nome_destino):
    try:
        if not src or not os.path.exists(src):
            print(f"⚠️ Relatório não encontrado para publicar: {src}")
            return None
        dst = os.path.join(RELATORIOS_DIR, nome_destino)
        shutil.copy2(src, dst)
        print(f"💾 Relatório público salvo: {dst}")
        return dst
    except Exception as e:
        print(f"⚠️ Falha ao copiar relatório público {src} -> {nome_destino}: {e}")
        return None

def _gerar_zip_relatorios_publicos():
    try:
        import zipfile
        zip_path = os.path.join(RELATORIOS_DIR, "ultimos_relatorios_cobranca.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for label, path in relatorios_publicos.items():
                if label == "zip":
                    continue
                if path and os.path.exists(path):
                    zf.write(path, arcname=os.path.basename(path))
        relatorios_publicos["zip"] = zip_path
        print(f"📦 ZIP de relatórios salvo: {zip_path}")
        return zip_path
    except Exception as e:
        print(f"⚠️ Falha ao gerar ZIP de relatórios: {e}")
        return None

from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException, SessionNotCreatedException


def _resolve_bin(env_names, candidates):
    """Resolve binário por variável de ambiente, caminho fixo ou PATH."""
    for env in env_names:
        val = os.getenv(env)
        if val and os.path.exists(val):
            return val
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    for name in ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chromedriver"]:
        found = shutil.which(name)
        if found:
            if "driver" in name and "CHROMEDRIVER" not in env_names:
                continue
            if "driver" not in name and "CHROME" not in "".join(env_names):
                continue
            return found
    return None


def _make_chrome_options(profile_dir):
    opts = Options()

    if IS_RAILWAY:
        opts.page_load_strategy = "eager"
        # Headless deixa o Chrome mais estável no Railway, mesmo com Xvfb disponível.
        if os.getenv("DISABLE_CHROME_HEADLESS", "0") != "1":
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        # NÃO usar porta fixa 9222: em Railway pode dar conflito e o Chrome fecha.
        opts.add_argument("--remote-debugging-port=0")
        opts.add_argument("--remote-debugging-address=127.0.0.1")
        opts.add_argument("--disable-software-rasterizer")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-background-networking")
        opts.add_argument("--disable-background-timer-throttling")
        opts.add_argument("--disable-backgrounding-occluded-windows")
        opts.add_argument("--disable-renderer-backgrounding")
        opts.add_argument("--hide-scrollbars")
        opts.add_argument("--mute-audio")
        opts.add_argument("--no-first-run")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--disable-features=VizDisplayCompositor,TranslateUI")
        opts.add_argument("--disable-setuid-sandbox")
        opts.add_argument("--disable-infobars")
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--allow-insecure-localhost")
        opts.add_argument("--disable-crash-reporter")
        opts.add_argument("--disable-sync")
        opts.add_argument("--metrics-recording-only")
        opts.add_argument("--disable-default-apps")
        # Perfil único por execução: evita "Chrome instance exited" por profile lock.
        opts.add_argument(f"--user-data-dir={profile_dir}")
        opts.add_argument(f"--data-path={os.path.join(profile_dir, 'data')}")
        opts.add_argument(f"--disk-cache-dir={os.path.join(profile_dir, 'cache')}")
    else:
        opts.add_argument("--start-maximized")

    prefs = {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
        "profile.default_content_settings.popups": 0,
    }
    opts.add_experimental_option("prefs", prefs)

    chrome_bin = _resolve_bin(
        ["GOOGLE_CHROME_BIN", "CHROME_BIN"],
        ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"]
    )
    if chrome_bin and os.path.exists(chrome_bin):
        opts.binary_location = chrome_bin

    return opts


def iniciar_driver_chrome():
    chrome_driver_bin = _resolve_bin(
        ["CHROMEDRIVER", "CHROMEDRIVER_PATH"],
        ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"]
    )

    ultimo_erro = None
    for tentativa in range(1, 4):
        profile_dir = os.path.join(
            tempfile.gettempdir(),
            f"chrome-profile-mdl-{os.getpid()}-{int(time.time()*1000)}-{tentativa}"
        )
        os.makedirs(profile_dir, exist_ok=True)
        opts = _make_chrome_options(profile_dir)

        try:
            print(f"🧭 Iniciando Chrome tentativa {tentativa}/3")
            print(f"   IS_RAILWAY={IS_RAILWAY} DISPLAY={os.getenv('DISPLAY')}")
            print(f"   Chrome binary={getattr(opts, 'binary_location', '')}")
            print(f"   ChromeDriver={chrome_driver_bin or 'Selenium Manager'}")
            print(f"   Profile={profile_dir}")

            if chrome_driver_bin and os.path.exists(chrome_driver_bin):
                drv = webdriver.Chrome(service=Service(chrome_driver_bin), options=opts)
            else:
                drv = webdriver.Chrome(options=opts)
            return drv

        except (SessionNotCreatedException, WebDriverException) as e:
            ultimo_erro = e
            print(f"⚠️ Falha ao iniciar Chrome na tentativa {tentativa}/3: {e}")
            time.sleep(2)

    print("❌ Não foi possível iniciar Chrome/Chromedriver após 3 tentativas.")
    print(f"   GOOGLE_CHROME_BIN={os.getenv('GOOGLE_CHROME_BIN')}")
    print(f"   CHROME_BIN={os.getenv('CHROME_BIN')}")
    print(f"   CHROMEDRIVER={os.getenv('CHROMEDRIVER')}")
    print(f"   CHROMEDRIVER_PATH={os.getenv('CHROMEDRIVER_PATH')}")
    raise ultimo_erro


driver = iniciar_driver_chrome()
driver.set_page_load_timeout(120)
wait = WebDriverWait(driver, 40)


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


def _set_input_by_id_safely(input_id, valor):
    el = wait.until(EC.presence_of_element_located((By.ID, input_id)))
    try:
        driver.execute_script("arguments[0].removeAttribute('readonly'); arguments[0].removeAttribute('disabled');", el)
    except Exception:
        pass
    driver.execute_script("arguments[0].value = '';", el)
    if valor is not None and str(valor) != "":
        el.send_keys(str(valor))
    try:
        driver.execute_script("arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el)
        driver.execute_script("arguments[0].dispatchEvent(new Event('blur',{bubbles:true}));", el)
    except Exception:
        pass
    return el


def _selecionar_situacao_quitados():
    """
    Tenta selecionar Situação = Quitados no relatório de Contas a Receber.
    O SGI pode mudar id/name, então tentamos várias formas.
    """
    tentativas = [
        (By.ID, "situacao"),
        (By.ID, "situacao_titulo"),
        (By.ID, "situacao_conta"),
        (By.NAME, "filtros[situacao]"),
        (By.NAME, "filtros[situacao_titulo]"),
    ]
    for by, sel in tentativas:
        try:
            el = driver.find_element(by, sel)
            s = Select(el)
            # tenta por value primeiro
            for val in ["quitado", "quitados", "Q", "2", "3"]:
                try:
                    s.select_by_value(val)
                    print(f"✅ Situação Quitados OK via {sel}={val}")
                    return True
                except Exception:
                    pass
            # tenta por texto
            for opt in s.options:
                txt = (opt.text or "").strip().lower()
                if "quitad" in txt:
                    s.select_by_visible_text(opt.text)
                    print(f"✅ Situação Quitados OK via texto: {opt.text}")
                    return True
        except Exception:
            pass

    # fallback por label
    try:
        xp = "//label[contains(translate(normalize-space(.),'ÇÃÕÁÉÍÓÚÂÊÔÀÈÌÒÙ','CAOAEIOUAEOA EIOU'),'Situacao')]/following::select[1]"
        el = driver.find_element(By.XPATH, xp)
        s = Select(el)
        for opt in s.options:
            if "quitad" in (opt.text or "").lower():
                s.select_by_visible_text(opt.text)
                print(f"✅ Situação Quitados OK via label: {opt.text}")
                return True
    except Exception:
        pass

    print("⚠️ Não consegui confirmar Situação = Quitados automaticamente")
    return False


def _parse_quitados_xls_180d(caminho_quitados, colmap):
    """
    Lê o relatório de quitados e devolve lista de títulos quitados.
    Mantém vendedor do ERP como referência, mas a atribuição do mérito será feita no dashboard
    cruzando com cobrancas_log.json pelo último cobrador antes do pagamento.
    """
    dfq = pd.read_excel(caminho_quitados, header=None, engine="openpyxl")
    quitados = []
    vend_atual = None
    agora = datetime.now()

    def _limpa(v):
        s = str(v or "").strip()
        return "" if s in ("nan", "None") else s

    def _limpar_nome_erp_local(txt):
        try:
            return limpar_nome_erp(txt)
        except NameError:
            s = re.sub(r"^Vendedor:\s*", "", str(txt).strip(), flags=re.IGNORECASE)
            s = re.sub(r"^\d+\s*-\s*", "", s)
            s = re.sub(r"^C\.\d+\s*-\s*", "", s, flags=re.IGNORECASE)
            return s.strip()

    def _limpar_nome_display_local(txt):
        try:
            return limpar_nome_display(txt)
        except NameError:
            s = re.sub(r"\s*\(GER\s*F\d+\)\s*$", "", str(txt).strip(), flags=re.IGNORECASE)
            s = re.sub(r"\s*\(F\d+\)\s*$", "", s, flags=re.IGNORECASE)
            return s.strip()

    for i in range(len(dfq)):
        row = dfq.iloc[i]
        c0 = _limpa(row[colmap["filial"]]) if len(row) > colmap["filial"] else ""
        c1 = _limpa(row[colmap["cliente"]]) if len(row) > colmap["cliente"] else ""

        if "Vendedor:" in c0:
            vend_atual = _limpar_nome_erp_local(c0)
            continue

        if not vend_atual:
            continue
        if c1 in ("", "Cliente", "Filial"):
            continue
        if c0.upper().startswith("TOTAL") or c1.upper().startswith("TOTAL"):
            continue

        venc = _parse_data(row[colmap["vencimento"]]) if len(row) > colmap["vencimento"] else None
        pagto = _parse_data(row[colmap["pagamento"]]) if len(row) > colmap["pagamento"] else None
        if not venc or not pagto:
            continue

        pago = tratar_valor(row[colmap["pago_total"]]) if len(row) > colmap["pago_total"] else 0.0
        if pago <= 0:
            continue

        try:
            dias_atraso_pg = max(0, (pagto - venc).days)
        except Exception:
            dias_atraso_pg = 0

        if dias_atraso_pg >= 60:
            faixa = "grave"
        elif 30 <= dias_atraso_pg < 60:
            faixa = "alerta"
        elif 15 <= dias_atraso_pg < 30:
            faixa = "atencao"
        else:
            # quitou antes de entrar na regra de cobrança
            continue

        filial_txt = c0
        mfil = re.search(r"FILIAL\s*(\d+)", filial_txt.upper())
        filial_key = f"F{int(mfil.group(1))}" if mfil else ""

        quitados.append({
            "cliente": c1[:80],
            "vendedor_erp": _limpar_nome_display_local(vend_atual),
            "filial": filial_key,
            "filial_label": filial_txt,
            "lancamento": _limpa(row[colmap["num_lancamento"]]) if len(row) > colmap["num_lancamento"] else "",
            "titulo": _limpa(row[colmap["num_titulo"]]) if len(row) > colmap["num_titulo"] else "",
            "parcela": _limpa(row[colmap["num_parcela"]]) if len(row) > colmap["num_parcela"] else "",
            "vencimento": _limpa(row[colmap["vencimento"]]) if len(row) > colmap["vencimento"] else "",
            "pagamento": _limpa(row[colmap["pagamento"]]) if len(row) > colmap["pagamento"] else "",
            "pago": round(float(pago), 2),
            "dias_atraso_pagamento": dias_atraso_pg,
            "faixa": faixa,
            "forma_pagamento": _limpa(row[colmap["forma_pagamento"]]) if len(row) > colmap["forma_pagamento"] else "",
            "conta_caixa": _limpa(row[colmap["conta_caixa"]]) if len(row) > colmap["conta_caixa"] else "",
            "origem": "relatorio_quitados_180d",
        })

    print(f"✅ Quitados 180d lidos: {len(quitados)} título(s)")
    return quitados


def coletar_quitados_180d_contas_receber():
    """
    Relatório complementar para conciliar cobranças feitas com pagamentos que saíram da faixa 15-90.
    Filtros:
    - Vencimento inicial em branco
    - Vencimento final = hoje
    - Situação = Quitados
    - + Data último pagamento inicial = hoje - 180 dias
    - Data último pagamento final = hoje
    - Formas de pagamento iguais ao relatório atual
    """
    data_hoje = datetime.now().strftime("%d/%m/%Y")
    data_180 = (datetime.now() - timedelta(days=180)).strftime("%d/%m/%Y")

    print("\n🔎 Iniciando relatório complementar de QUITADOS 180 dias...")
    driver.get(URL + "/relatorio_contas_receber")
    wait.until(EC.presence_of_element_located((By.ID, "data_vencimento_inicial")))
    Select(driver.find_element(By.ID, "data_vencimento")).select_by_value("intervalo")
    time.sleep(1.5)

    # Vencimento inicial em branco / final hoje
    _set_input_by_id_safely("data_vencimento_inicial", "")
    _set_input_by_id_safely("data_vencimento_final", data_hoje)

    # Situação = Quitados
    _selecionar_situacao_quitados()

    # Filiais
    try:
        driver.find_element(By.XPATH, "//label[contains(text(),'Filiais')]/following::button[1]").click()
        time.sleep(1.5)
        filiais_sel = ["1", "2", "3", "4", "5", "6", "7", "8", "10"]
        container = driver.find_element(By.XPATH, "//label[contains(text(),'Filiais')]/following::ul[1]")
        for c in container.find_elements(By.XPATH, ".//input[@type='checkbox']"):
            if c.get_attribute("value") in filiais_sel:
                driver.execute_script("arguments[0].click();", c)
        print("✅ Filiais OK quitados")
        time.sleep(1.5)
    except Exception as e:
        print(f"⚠️ Erro filiais quitados: {e}")

    # Abre +
    try:
        clicar_seguro_xpath("//span[contains(@class,'glyphicon-plus')]", timeout=20)
        print("✅ Mais filtros quitados")
        time.sleep(1.5)
    except Exception as e:
        print(f"⚠️ Não abriu + quitados: {e}")

    # Data último pagamento
    try:
        _set_input_by_id_safely("data_ultimo_pagamento_inicial", data_180)
        _set_input_by_id_safely("data_ultimo_pagamento_final", data_hoje)
        print(f"✅ Data último pagamento: {data_180} até {data_hoje}")
    except Exception as e:
        print(f"⚠️ Erro datas último pagamento: {e}")

    # Formas de pagamento
    try:
        marcar_multiselect_por_label("Forma de Pagamento", ["3", "47", "17"], timeout=20, limpar_antes=True)
        print("✅ Formas OK quitados")
        time.sleep(1.5)
    except Exception as e:
        print(f"⚠️ Erro formas quitados: {e}")

    try:
        Select(wait.until(EC.presence_of_element_located((By.ID, "_formato")))).select_by_value("xls")
        print("✅ Formato XLS quitados")
        time.sleep(1.5)
    except Exception as e:
        print(f"⚠️ Erro formato XLS quitados: {e}")

    arquivos_antes = set(f for f in os.listdir(download_dir) if nome_arquivo_contas_valido(f))
    driver.find_element(By.ID, "gerar").click()
    print("📥 Gerando XLS quitados... aguardando download...")

    caminho_q = None
    for tentativa in range(75):
        time.sleep(2)
        baixando = any(f.endswith(".crdownload") or f.endswith(".tmp") for f in os.listdir(download_dir))
        if tentativa % 5 == 0:
            print(f"⏳ Quitados tentativa {tentativa}/75 | baixando={baixando}")
        if baixando:
            continue
        novos = set(f for f in os.listdir(download_dir) if nome_arquivo_contas_valido(f)) - arquivos_antes
        if novos:
            caminho_q = max([os.path.join(download_dir, f) for f in novos], key=os.path.getctime)
            print(f"✅ Download quitados OK: {caminho_q}")
            try:
                relatorios_publicos["quitados_original_xls"] = _copiar_relatorio_publico(caminho_q, "ultimo_contas_receber_quitados_original.xls")
            except Exception as e_pub_q:
                print(f"⚠️ Não consegui copiar XLS original de quitados: {e_pub_q}")
            break

    if not caminho_q:
        print("⚠️ Nenhum XLS de quitados baixado. Seguindo sem conciliação extra.")
        return {"xlsx_path": None, "json_path": None, "dados": {"quitados": [], "erro": "download_nao_encontrado"}}

    quitados = _parse_quitados_xls_180d(caminho_q, COL)
    out_json = os.path.join(pasta, "quitados_180d_contas_receber.json")
    out_xlsx = os.path.join(pasta, "quitados_180d_contas_receber.xlsx")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump({
            "gerado_em": datetime.now().isoformat(),
            "periodo_pagamento": {"inicio": data_180, "fim": data_hoje},
            "criterio": "quitados pagos em ate 180 dias apos cobranca, conciliados no dashboard pelo ultimo cobrador antes do pagamento",
            "quitados": quitados,
        }, f, ensure_ascii=False, indent=2)
    try:
        pd.DataFrame(quitados).to_excel(out_xlsx, index=False)
    except Exception:
        out_xlsx = None

    print(f"💾 Quitados JSON: {out_json}")
    if out_xlsx:
        print(f"💾 Quitados XLSX: {out_xlsx}")
    try:
        relatorios_publicos["quitados_json"] = _copiar_relatorio_publico(out_json, "quitados_180d_contas_receber.json")
        if out_xlsx:
            relatorios_publicos["quitados_processado_xlsx"] = _copiar_relatorio_publico(out_xlsx, "quitados_180d_contas_receber.xlsx")
    except Exception as e_pub_q2:
        print(f"⚠️ Não consegui preparar quitados para publicação: {e_pub_q2}")

    return {"xlsx_path": out_xlsx, "json_path": out_json, "dados": {"quitados": quitados}}


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
        print(f"✅ Download OK: {caminho}")
        relatorios_publicos["principal_xls"] = _copiar_relatorio_publico(caminho, "ultimo_contas_receber_principal.xls")
        break

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
#   recebido_faixa  = pago nos títulos com pagto >= data_corte (delta do período)
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

# ===== RELATÓRIO COMPLEMENTAR: QUITADOS 180 DIAS
# IMPORTANTE: roda aqui porque neste ponto os helpers limpar_nome_erp, limpar_nome_display,
# tratar_valor e _parse_data já foram definidos.
quitados_180_info = {"json_path": None, "xlsx_path": None, "dados": {"quitados": []}}
try:
    quitados_180_info = coletar_quitados_180d_contas_receber()
except Exception as e:
    print(f"⚠️ Erro ao coletar quitados 180d: {e}")
    quitados_180_info = {"json_path": None, "xlsx_path": None, "dados": {"quitados": [], "erro": str(e)}}


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

# ✅ V7: para os recebimentos por faixa, o período deve ser o mês inteiro.
# Inclui pagamentos feitos no próprio dia 01 do mês.
_data_corte_parse = _dt(_dt.now().year, _dt.now().month, 1)
print(f"✅ V7_RECEBIMENTO_MES_COMPLETO: recebimentos por faixa desde {_data_corte_parse.strftime('%d/%m/%Y')} inclusive")

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
    if _faixa and _pagto and _pago_val > 0 and _pagto >= _data_corte_parse:
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

def _load_crediaristas_config_do_meta():
    default = [
        {"login": "crediaristaf02_01", "nome": "Crediarista F2 01", "filial": "F2", "pct": 100},
        {"login": "crediaristaf03_01", "nome": "Crediarista F3 01", "filial": "F3", "pct": 100},
        {"login": "crediaristaf04_01", "nome": "Crediarista F4 01", "filial": "F4", "pct": 100},
        {"login": "crediaristaf05_01", "nome": "Crediarista F5 01", "filial": "F5", "pct": 100},
        {"login": "crediaristaf06_01", "nome": "Crediarista F6 01", "filial": "F6", "pct": 100},
        {"login": "crediaristaf08_01", "nome": "Crediarista F8 01", "filial": "F8", "pct": 100},
        {"login": "crediaristaf09_01", "nome": "Crediarista F9 01", "filial": "F9", "pct": 100},
    ]
    try:
        _cfgp = os.path.join(pasta, "cache_historico", "config_meta.json")
        if os.path.exists(_cfgp):
            with open(_cfgp, "r", encoding="utf-8") as _fc:
                _raw = json.load(_fc)
            _glob = _raw.get("global", _raw) if isinstance(_raw, dict) else {}
            rows = _glob.get("crediaristas_config") or []
            clean = []
            for r in rows:
                if not isinstance(r, dict): continue
                filial = str(r.get("filial") or "").upper().strip()
                if filial and not filial.startswith("F"): filial = "F" + filial.zfill(2).lstrip("0")
                if filial.startswith("F0"): filial = "F" + filial[2:]
                login = str(r.get("login") or "").lower().strip()
                nome = str(r.get("nome") or "").strip() or f"Crediarista {filial}"
                try: pct = float(str(r.get("pct", 100)).replace(",", "."))
                except Exception: pct = 100.0
                pct = max(0.0, min(100.0, pct))
                if filial and login and pct > 0: clean.append({"login": login, "nome": nome, "filial": filial, "pct": pct})
            if clean: return clean
    except Exception as e:
        print(f"⚠️ Não consegui carregar crediaristas_config: {e}")
    return default

CREDIARISTAS_CONFIG = _load_crediaristas_config_do_meta()
CREDIARISTAS_FILIAIS = {r["filial"]: r["login"] for r in CREDIARISTAS_CONFIG}
CREDIARISTAS_NOMES = {r["login"]: r.get("nome") or f"Crediarista {r['filial']}" for r in CREDIARISTAS_CONFIG}

def nome_crediarista_filial(filial, login=None):
    if login and str(login).lower() in CREDIARISTAS_NOMES:
        return CREDIARISTAS_NOMES[str(login).lower()]
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
    _nome_cred = nome_crediarista_filial(_fil_cred, _login_cred)
    _senha_ini = creds_salvas.get(f"{_login_cred}_{_fil_cred}") or creds_salvas.get(_login_cred) or (_login_cred.upper() + str(random.randint(100,999)))
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
    "crediaristas_config": [
        {"login": "crediaristaf02_01", "nome": "Crediarista F2 01", "filial": "F2", "pct": 100},
        {"login": "crediaristaf03_01", "nome": "Crediarista F3 01", "filial": "F3", "pct": 100},
        {"login": "crediaristaf04_01", "nome": "Crediarista F4 01", "filial": "F4", "pct": 100},
        {"login": "crediaristaf05_01", "nome": "Crediarista F5 01", "filial": "F5", "pct": 100},
        {"login": "crediaristaf06_01", "nome": "Crediarista F6 01", "filial": "F6", "pct": 100},
        {"login": "crediaristaf08_01", "nome": "Crediarista F8 01", "filial": "F8", "pct": 100},
        {"login": "crediaristaf09_01", "nome": "Crediarista F9 01", "filial": "F9", "pct": 100}
    ],
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
#   1. Lê todos os títulos pagos no período (pagto >= data_corte, conta caixa ≠ 100)
#   2. Classifica por faixa de vencimento (grave/alerta/atenção)
#   3. Distribui inativos e FDEP para ativos da filial (60% gerente / 40% vendedores)
#   4. recebimentos_det_js = relatório visual (com detalhes dos títulos)
#   5. recebido_faixa = somatório por faixa por vendedor (para os gráficos de meta)
#   OS DOIS SÃO DERIVADOS DA MESMA FONTE → valores sempre batem
# =========================================================================

# Passo A: Lê títulos brutos do XLS (todos os vendedores)
# _rec_raw[chave] = {grave:[], alerta:[], atencao:[], is_ativo, is_fdep, filial}
_rec_raw = {}
# Evita duplicar títulos quando o mesmo pagamento aparece no XLS principal e no complementar de quitados.
_rec_seen_keys = set()
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
    if _pagto2 < _data_corte_parse:
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

    _titulo_seen2 = str(_row2[COL["num_titulo"]]).strip()
    _parcela_seen2 = str(_row2[COL["num_parcela"]]).strip()
    _lanc_seen2 = str(_row2[COL["num_lancamento"]]).strip()
    _pag_seen2 = str(_row2[COL["pagamento"]]).strip()
    _seen2 = f"{normalizar_texto_match(_c12[:60])}|{_lanc_seen2}|{_titulo_seen2}|{_parcela_seen2}|{_pag_seen2}"
    if _seen2 in _rec_seen_keys:
        continue
    _rec_seen_keys.add(_seen2)

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
        "origem": "xls_principal",
    })

# Passo A.1: Inclui o relatório complementar de QUITADOS 180d na mesma fonte dos recebimentos.
# Antes o robô baixava/salvava quitados_180d_contas_receber.json, mas não somava esses títulos
# em recebimentos_det_js/recebido_faixa. Assim, pagamentos que saíam do relatório principal
# por estarem quitados podiam deixar as faixas Grave/Alerta/Atenção zeradas.
_quitados_extra = (quitados_180_info.get("dados", {}) or {}).get("quitados", []) or []
_ativos_lookup_receb = {}
try:
    for _, _rv_lookup in df_vend.iterrows():
        _nome_lookup = str(_rv_lookup.get("nome_exibicao", "")).strip()
        _fil_lookup = str(_rv_lookup.get("filial_vendedor", "")).strip().upper()
        if _nome_lookup and _fil_lookup:
            _ativos_lookup_receb[(normalizar_texto_match(_nome_lookup), _fil_lookup)] = _nome_lookup
except Exception:
    _ativos_lookup_receb = {}

_qtd_extra_usados = 0
_qtd_extra_dup = 0
for _q in _quitados_extra:
    try:
        _fxq = str(_q.get("faixa", "")).strip().lower()
        if _fxq not in ("grave", "alerta", "atencao"):
            continue
        _pagtoq = _parse_data(_q.get("pagamento"))
        _pagoq = float(_q.get("pago", 0) or 0)
        if not _pagtoq or _pagoq <= 0 or _pagtoq < _data_corte_parse:
            continue

        _clienteq = str(_q.get("cliente", "")).strip()
        _seenq = f"{normalizar_texto_match(_clienteq[:60])}|{str(_q.get('lancamento','')).strip()}|{str(_q.get('titulo','')).strip()}|{str(_q.get('parcela','')).strip()}|{str(_q.get('pagamento','')).strip()}"
        if _seenq in _rec_seen_keys:
            _qtd_extra_dup += 1
            continue
        _rec_seen_keys.add(_seenq)

        _filq = str(_q.get("filial", "")).strip().upper() or "OUTROS"
        _nomeq_raw = str(_q.get("vendedor_erp", "")).strip() or "INATIVO"
        _nomeq_norm = normalizar_texto_match(_nomeq_raw)
        _nome_ativo = _ativos_lookup_receb.get((_nomeq_norm, _filq))

        if _nome_ativo:
            _nomeq = _nome_ativo
            _fvq = _filq
            _is_atq = True
            _is_fpq = False
        else:
            _nomeq = limpar_nome_display(_nomeq_raw)
            _fvq = "FDEP" if _filq == "FDEP" else _filq
            _is_atq = False
            _is_fpq = (_fvq == "FDEP")

        _kvq = f"{_nomeq}_{_fvq}"
        if _kvq not in _rec_raw:
            _rec_raw[_kvq] = {
                "grave": [], "alerta": [], "atencao": [],
                "is_ativo": _is_atq, "is_fdep": _is_fpq, "filial": _fvq,
            }

        _rec_raw[_kvq][_fxq].append({
            "cliente": _clienteq[:40],
            "dias": int(_q.get("dias_atraso_pagamento", 0) or 0),
            "pago": _pagoq,
            "vencimento": str(_q.get("vencimento", "")).strip(),
            "pagamento": str(_q.get("pagamento", "")).strip(),
            "parcela": str(_q.get("parcela", "")).strip(),
            "titulo": str(_q.get("titulo", "")).strip(),
            "vendedor": (_nomeq + ("" if _is_atq else (" [FDEP]" if _is_fpq else " [Quitado/Inativo]")))[:30],
            "origem": "quitados_180d",
        })
        _qtd_extra_usados += 1
    except Exception as _e_q:
        print(f"⚠️ Quitado 180d ignorado por erro: {_e_q}")

print(f"💰 Quitados 180d incorporados aos recebimentos: {_qtd_extra_usados} título(s) | duplicados ignorados: {_qtd_extra_dup}")

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


# ✅ V7: diagnóstico para confirmar nos logs se os valores entraram no HTML
try:
    _dbg_g = sum(float(v.get('grave', 0) or 0) for v in recebido_faixa.values())
    _dbg_a = sum(float(v.get('alerta', 0) or 0) for v in recebido_faixa.values())
    _dbg_t = sum(float(v.get('atencao', 0) or 0) for v in recebido_faixa.values())
    print(f"🧾 DEBUG V7 recebimentos por faixa desde {_data_corte_parse.strftime('%d/%m/%Y')}: grave=R$ {_dbg_g:.2f} | alerta=R$ {_dbg_a:.2f} | atencao=R$ {_dbg_t:.2f} | total=R$ {(_dbg_g+_dbg_a+_dbg_t):.2f}")
except Exception as _e_dbg_rec:
    print(f"⚠️ DEBUG V7 recebimentos falhou: {_e_dbg_rec}")

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

# ── CREDIARISTAS: configuráveis por usuário/filial/percentual ─────────────────
clientes_crediarista_js = {}
recebimentos_crediarista_js = {}
for _cred_cfg in CREDIARISTAS_CONFIG:
    _fil_cred = str(_cred_cfg.get('filial', '')).upper()
    _login_cred = str(_cred_cfg.get('login', '')).lower()
    _pct_cred = max(0.0, min(100.0, float(_cred_cfg.get('pct', 100) or 100)))
    _src_cli = clientes_js.get(_fil_cred, {}) or {}
    clientes_crediarista_js[_login_cred] = {'grave': [], 'alerta': [], 'atencao': []}
    for _fx in ['grave','alerta','atencao']:
        _base_fx = list(_src_cli.get(_fx, []) or [])
        _base_fx = sorted(_base_fx, key=lambda r: _hashlib.md5((cobranca_row_key_py(r)+'|'+_login_cred).encode('utf-8')).hexdigest())
        _n = int(round(len(_base_fx) * (_pct_cred/100.0)))
        clientes_crediarista_js[_login_cred][_fx] = _base_fx[:_n]
    recebimentos_crediarista_js[_login_cred] = {'grave': [], 'alerta': [], 'atencao': []}

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
js_crediaristas_map = json.dumps(CREDIARISTAS_CONFIG, ensure_ascii=False)
js_destaque = json.dumps(destaque_semana or {}, ensure_ascii=False)
js_hist_dash = json.dumps(hist_dash, ensure_ascii=False)
js_quitados_180 = json.dumps((quitados_180_info.get('dados') or {}).get('quitados', []), ensure_ascii=False)

total_dash_p  = round(total_final_p,  2)
total_dash_pg = round(total_final_pg, 2)



# =========================================
# 🔥 HTML COMPLETO v2 — 4 GRÁFICOS META
# =========================================
import re as _re, base64 as _b64

_laranjito = "https://moveisdolar.com.br/colaborador/mascote%20feliz1.png"
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


/* ===== AJUSTE FINAL LARANJITO PROPORCIONAL SEM FUNDO ===== */
.kpi.kpi-laranjito{
  position:relative;
  overflow:hidden;
  padding-right:92px !important;
}
.kpi .laranjito-card{
  position:absolute !important;
  right:12px !important;
  bottom:8px !important;
  top:auto !important;
  transform:none !important;
  width:74px !important;
  height:74px !important;
  max-width:74px !important;
  max-height:74px !important;
  object-fit:contain !important;
  object-position:center !important;
  border-radius:0 !important;
  background:transparent !important;
  box-shadow:none !important;
  border:0 !important;
  outline:0 !important;
  padding:0 !important;
  margin:0 !important;
  animation:laranjitoPulseImg 1.45s ease-in-out infinite !important;
  pointer-events:none !important;
  z-index:2 !important;
}
@keyframes laranjitoPulseImg{
  0%,100% { transform:scale(1); filter:drop-shadow(0 0 6px rgba(255,147,0,.35)); }
  50% { transform:scale(1.08); filter:drop-shadow(0 0 14px rgba(255,147,0,.75)); }
}
.kpi .laranjito-card::after{content:none!important;}
.kpi .laranjito-caption{display:none!important;}


/* ===== CONFIGURAÇÃO GLOBAL DE MENSAGEM DE COBRANÇA ===== */
.cobranca-config-grid{
  display:grid;
  grid-template-columns: 1.4fr .9fr;
  gap:14px;
}
.cobranca-template{
  min-height:180px;
  resize:vertical;
  line-height:1.45;
}
.placeholder-list{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:6px;
  margin-top:8px;
}
.placeholder-list code{
  font-size:11px;
  background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.09);
  padding:5px 7px;
  border-radius:9px;
  color:#e5e7eb;
}
.preview-whats{
  white-space:pre-wrap;
  background:rgba(15,23,42,.76);
  border:1px solid rgba(255,255,255,.08);
  border-radius:14px;
  padding:12px;
  color:#dbeafe;
  min-height:130px;
}
@media(max-width:900px){.cobranca-config-grid{grid-template-columns:1fr}}



/* ===== LISTA SEM COBRANÇAS HOJE ===== */
.sem-cobrancas-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin-top:12px}
.sem-cobranca-chip{display:flex;align-items:center;gap:8px;border:1px solid rgba(239,68,68,.18);background:rgba(239,68,68,.06);border-radius:12px;padding:8px 10px;font-size:12px;font-weight:700}
.sem-cobranca-chip small{display:block;color:var(--text-muted);font-weight:600;margin-top:2px}


/* ===== FIX LEGIBILIDADE AVISOS/CAMPANHAS EM FUNDO CLARO ===== */
.campaign-banner{
  color:#1f2937 !important;
}
.campaign-banner h1,
.campaign-banner h2,
.campaign-banner h3,
.campaign-banner strong,
.campaign-banner .msg-head strong{
  color:#111827 !important;
  text-shadow:none !important;
}
.campaign-banner .hint,
.campaign-banner .small,
.campaign-banner .muted,
.campaign-banner .msg-card,
.campaign-banner .msg-card div{
  color:#334155 !important;
  text-shadow:none !important;
}
.campaign-banner .msg-card.campaign-banner,
.campaign-banner .msg-card{
  background:rgba(255,255,255,.58) !important;
  border:1px solid rgba(180,130,40,.22) !important;
  box-shadow:0 8px 24px rgba(120,80,20,.08) !important;
}
.campaign-banner .btn.soft{
  color:#111827 !important;
  background:rgba(255,255,255,.72) !important;
  border-color:rgba(120,80,20,.22) !important;
}
.campaign-banner .unread-chip{
  background:#fff7ed !important;
  border-color:#fb923c !important;
  color:#9a3412 !important;
}
.campaign-banner .mini-chip{
  font-weight:800 !important;
}
.campaign-banner .msg-head .small,
.campaign-banner .msg-head .muted{
  color:#475569 !important;
}
.campaign-banner [style*="white-space:pre-wrap"]{
  color:#1f2937 !important;
  font-weight:700 !important;
}


/* ===== FIX LEGIBILIDADE AVISOS NO MODAL DO SINO ===== */
.modal-card .modal-list .msg-card.campaign-banner,
#bellList .msg-card.campaign-banner{
  background:linear-gradient(180deg,#f7f1df,#f2ead7) !important;
  border:1px solid #e4d8b2 !important;
  color:#1f2937 !important;
}
.modal-card .modal-list .msg-card.campaign-banner *,
#bellList .msg-card.campaign-banner *{
  text-shadow:none !important;
}
.modal-card .modal-list .msg-card.campaign-banner strong,
#bellList .msg-card.campaign-banner strong{
  color:#111827 !important;
}
.modal-card .modal-list .msg-card.campaign-banner .small,
.modal-card .modal-list .msg-card.campaign-banner .muted,
#bellList .msg-card.campaign-banner .small,
#bellList .msg-card.campaign-banner .muted{
  color:#475569 !important;
}
.modal-card .modal-list .msg-card.campaign-banner [style*="white-space:pre-wrap"],
#bellList .msg-card.campaign-banner [style*="white-space:pre-wrap"]{
  color:#1f2937 !important;
  font-weight:700 !important;
}
.modal-card .modal-list .msg-card.campaign-banner .unread-chip,
#bellList .msg-card.campaign-banner .unread-chip{
  background:#fff7ed !important;
  border-color:#fb923c !important;
  color:#9a3412 !important;
}
#bellList .msg-card.campaign-banner .mini-chip{
  background:#fff7ed !important;
  border-color:#fdba74 !important;
  color:#c2410c !important;
}


/* ===== COBRANÇA INTELIGENTE: RECOBRANÇA / CONTADOR ===== */
.cob-history-chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  margin-left:6px;
  padding:4px 8px;
  border-radius:999px;
  border:1px solid rgba(251,146,60,.55);
  background:rgba(251,146,60,.13);
  color:#fed7aa;
  font-size:11px;
  font-weight:900;
}
.cob-retry-chip{
  display:inline-flex;
  align-items:center;
  gap:6px;
  margin-left:6px;
  padding:4px 8px;
  border-radius:999px;
  border:1px solid rgba(248,113,113,.62);
  background:rgba(248,113,113,.14);
  color:#fecaca;
  font-size:11px;
  font-weight:900;
  animation:pulse 1.35s infinite;
}
.cob-info-box{
  margin-top:7px;
  padding:8px 10px;
  border-radius:12px;
  border:1px solid rgba(251,146,60,.32);
  background:rgba(251,146,60,.08);
  color:#ffd6a3;
  font-size:12px;
  font-weight:800;
}
.cob-info-box.waiting{
  border-color:rgba(96,165,250,.32);
  background:rgba(96,165,250,.08);
  color:#bfdbfe;
}


/* ===== FIX GLOBAL: CAMPANHAS CLARAS EM QUALQUER MODAL/LISTA ===== */
.msg-card.campaign-banner,
.campaign-banner .msg-card,
#bellList .msg-card.campaign-banner,
.modal-card .msg-card.campaign-banner,
.modal-list .msg-card.campaign-banner{
  background:linear-gradient(180deg,#f7f1df,#f2ead7) !important;
  border:1px solid #e4d8b2 !important;
  color:#1f2937 !important;
  text-shadow:none !important;
}
.msg-card.campaign-banner *,
.campaign-banner .msg-card *,
#bellList .msg-card.campaign-banner *,
.modal-card .msg-card.campaign-banner *,
.modal-list .msg-card.campaign-banner *{
  text-shadow:none !important;
}
.msg-card.campaign-banner strong,
.campaign-banner .msg-card strong,
#bellList .msg-card.campaign-banner strong,
.modal-card .msg-card.campaign-banner strong,
.modal-list .msg-card.campaign-banner strong{
  color:#111827 !important;
}
.msg-card.campaign-banner .small,
.msg-card.campaign-banner .muted,
.campaign-banner .msg-card .small,
.campaign-banner .msg-card .muted,
#bellList .msg-card.campaign-banner .small,
#bellList .msg-card.campaign-banner .muted,
.modal-card .msg-card.campaign-banner .small,
.modal-card .msg-card.campaign-banner .muted,
.modal-list .msg-card.campaign-banner .small,
.modal-list .msg-card.campaign-banner .muted{
  color:#475569 !important;
}
.msg-card.campaign-banner [style*="white-space:pre-wrap"],
.campaign-banner .msg-card [style*="white-space:pre-wrap"],
#bellList .msg-card.campaign-banner [style*="white-space:pre-wrap"],
.modal-card .msg-card.campaign-banner [style*="white-space:pre-wrap"],
.modal-list .msg-card.campaign-banner [style*="white-space:pre-wrap"]{
  color:#1f2937 !important;
  font-weight:800 !important;
}
.msg-card.campaign-banner .btn.soft,
.campaign-banner .msg-card .btn.soft{
  color:#111827 !important;
  background:rgba(255,255,255,.78) !important;
  border-color:rgba(120,80,20,.22) !important;
}
.msg-card.campaign-banner .btn.danger,
.campaign-banner .msg-card .btn.danger{
  color:#7f1d1d !important;
  background:#fee2e2 !important;
  border-color:#fecaca !important;
}
.msg-card.campaign-banner .unread-chip,
#bellList .msg-card.campaign-banner .unread-chip,
.modal-card .msg-card.campaign-banner .unread-chip{
  background:#fff7ed !important;
  border-color:#fb923c !important;
  color:#9a3412 !important;
}
.msg-card.campaign-banner .mini-chip,
#bellList .msg-card.campaign-banner .mini-chip{
  background:#fff7ed !important;
  border-color:#fdba74 !important;
  color:#c2410c !important;
}

/* ===== LARANJITO NOTIFICAÇÕES FIXO ===== */
#laranjitoNotify{
  position:fixed;
  top:92px;
  right:22px;
  z-index:9998;
  width:66px;
  height:66px;
  border-radius:999px;
  border:2px solid rgba(255,138,0,.65);
  background:radial-gradient(circle at 35% 25%,rgba(255,255,255,.35),transparent 35%),rgba(17,24,39,.92);
  box-shadow:0 0 0 4px rgba(255,138,0,.12),0 14px 38px rgba(0,0,0,.42),0 0 28px rgba(255,138,0,.25);
  display:none;
  align-items:center;
  justify-content:center;
  cursor:pointer;
  transition:.18s transform ease,.18s filter ease;
}
#laranjitoNotify:hover{transform:scale(1.06);filter:brightness(1.08)}
#laranjitoNotify img{width:54px;height:54px;object-fit:contain;border-radius:999px}
#laranjitoNotifyBadge{
  position:absolute;
  top:-6px;
  right:-5px;
  min-width:22px;
  height:22px;
  border-radius:999px;
  background:#ef4444;
  color:#fff;
  font-size:12px;
  font-weight:950;
  display:flex;
  align-items:center;
  justify-content:center;
  border:2px solid #111827;
}
#laranjitoNotifyPanel{
  position:fixed;
  top:166px;
  right:22px;
  z-index:9999;
  width:min(420px,calc(100vw - 34px));
  max-height:70vh;
  overflow:auto;
  display:none;
  border:1px solid rgba(255,138,0,.35);
  background:rgba(17,20,29,.98);
  border-radius:22px;
  padding:14px;
  box-shadow:0 22px 55px rgba(0,0,0,.55);
}
#laranjitoNotifyPanel.show{display:block}
.laranjito-note{
  padding:11px 12px;
  border-radius:15px;
  border:1px solid rgba(255,255,255,.11);
  background:rgba(255,255,255,.05);
  margin-bottom:10px;
  color:#e5e7eb;
  font-weight:800;
}
.laranjito-note .small{color:#aab4c8!important;margin-top:4px}

/* ===== COBRANÇA INTELIGENTE: CONTADOR NO HISTÓRICO ===== */
.log-cob-count{
  display:inline-flex;
  align-items:center;
  gap:6px;
  padding:4px 9px;
  border-radius:999px;
  background:rgba(251,146,60,.12);
  border:1px solid rgba(251,146,60,.45);
  color:#fed7aa;
  font-size:11px;
  font-weight:900;
  margin-top:4px;
}


/* ===== AJUSTE FINAL LARANJITO ALERTAS ===== */
#laranjitoNotify.has-notes{
  display:flex;
  animation:laranjitoPulse 1.25s infinite;
}
@keyframes laranjitoPulse{
  0%{transform:scale(1); box-shadow:0 0 0 0 rgba(255,138,0,.42),0 14px 38px rgba(0,0,0,.42),0 0 28px rgba(255,138,0,.25)}
  60%{transform:scale(1.055); box-shadow:0 0 0 14px rgba(255,138,0,0),0 18px 45px rgba(0,0,0,.48),0 0 38px rgba(255,138,0,.38)}
  100%{transform:scale(1); box-shadow:0 0 0 0 rgba(255,138,0,0),0 14px 38px rgba(0,0,0,.42),0 0 28px rgba(255,138,0,.25)}
}
#laranjitoNotify.no-new{
  animation:none!important;
}
#laranjitoNotify img{
  width:58px!important;
  height:58px!important;
  object-fit:contain!important;
  border-radius:999px!important;
  display:block!important;
}
#laranjitoNotifyPanel .btn.soft{
  color:#fff!important;
}


/* ===== VISUALIZADOR INLINE DA TELA CONGELADA ===== */
#snapshotInlineViewer{
  margin-top:14px;
  border:1px solid rgba(255,138,0,.35);
  background:rgba(9,12,18,.96);
  border-radius:22px;
  padding:14px;
  display:none;
}
#snapshotInlineViewer.show{display:block}
.snapshot-inline-toolbar{
  display:flex;
  justify-content:space-between;
  align-items:center;
  gap:10px;
  margin-bottom:12px;
  padding:10px 12px;
  border-radius:14px;
  background:rgba(255,255,255,.05);
  border:1px solid rgba(255,255,255,.10);
}
.snapshot-inline-body{
  overflow:auto;
  max-height:78vh;
  border-radius:18px;
}


/* ===== HOTFIX FINAL LARANJITO BOLINHA ===== */
#laranjitoNotify{
  overflow:hidden!important;
  font-size:0!important;
  line-height:0!important;
}
#laranjitoNotify img#laranjitoNotifyImg{
  width:58px!important;
  height:58px!important;
  object-fit:contain!important;
  display:block!important;
  border-radius:999px!important;
}
#laranjitoNotify.only-current-user-hidden{display:none!important;}


/* ===== FIX DEFINITIVO BOLINHA LARANJITO ===== */
#laranjitoNotify{
  overflow:hidden!important;
  font-size:0!important;
}
#laranjitoNotify img#laranjitoNotifyImg{
  width:60px!important;
  height:60px!important;
  object-fit:contain!important;
  display:block!important;
  border-radius:999px!important;
  background:transparent!important;
}
#laranjitoNotifyFallback{
  display:none;
  font-size:38px;
  line-height:1;
}
#laranjitoNotify.img-fail #laranjitoNotifyImg{display:none!important}
#laranjitoNotify.img-fail #laranjitoNotifyFallback{display:block!important}
body.master-view #laranjitoNotify, body.diretor-view #laranjitoNotify{display:none!important}

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


<div id="laranjitoNotify" onclick="toggleLaranjitoNotifyPanel()" title="Alertas e parabéns">
  <img id="laranjitoNotifyImg" src="" alt="" referrerpolicy="no-referrer">
  <span id="laranjitoNotifyFallback">🍊</span>
  <span id="laranjitoNotifyBadge">0</span>
</div>
<div id="laranjitoNotifyPanel"></div>

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
const QUITADOS_180=__JS_QUITADOS_180__||[];
let RECEBIMENTOS_CONCILIADOS={};
let CREDIARISTAS_CONFIG=Array.isArray(__JS_CREDIARISTAS_MAP__)?__JS_CREDIARISTAS_MAP__:[];
if(!CREDIARISTAS_CONFIG.length && __JS_CREDIARISTAS_MAP__ && typeof __JS_CREDIARISTAS_MAP__==='object'){
  CREDIARISTAS_CONFIG=Object.entries(__JS_CREDIARISTAS_MAP__).map(([filial,login])=>({filial,login,nome:`Crediarista ${filial}`,pct:100}));
}
function getCrediaristasConfig(){return Array.isArray(CONFIG_META?.crediaristas_config)&&CONFIG_META.crediaristas_config.length?CONFIG_META.crediaristas_config:CREDIARISTAS_CONFIG}
const CREDIARISTAS_MAP=new Proxy({}, {get(t,k){const row=getCrediaristasConfig().find(r=>String(r.filial||'').toUpperCase()===String(k||'').toUpperCase());return row?String(row.login||'').toLowerCase():undefined}, ownKeys(){return getCrediaristasConfig().map(r=>r.filial)}, getOwnPropertyDescriptor(){return {enumerable:true,configurable:true}}});
const COBRANCA10_LOGIN='cobranca10';
const COBRANCA10_NOME='Cobrança10';
const METAS_VENDAS=__JS_METAS_VENDAS__||{metas:{}};
const MARGENS_BRUTAS=__JS_MARGENS_BRUTAS__||{filiais:{},vendedores:{}};
let SALES_EMPRESA=__JS_SALES_EMPRESA__||{};
let RENT_EMPRESA=__JS_RENT_EMPRESA__||{};

function getRentEmpresa(){
  let e = (RENT_EMPRESA && Object.keys(RENT_EMPRESA).length) ? {...RENT_EMPRESA} : {};
  const mb = MARGENS_BRUTAS || {};
  if((!e || !Object.keys(e).length) && mb.empresa) e = {...mb.empresa};

  // Fallback: se por qualquer motivo a empresa não veio no JSON,
  // soma as filiais do relatório de margem bruta.
  if((!Number(e.custo_total||0)) && mb.filiais){
    const vals = Object.values(mb.filiais || {});
    const soma = (campo)=>vals.reduce((acc,x)=>acc + Number(x?.[campo]||0), 0);
    e.custo_total = soma('custo_total');
    e.valor_total = soma('valor_total');
    e.valor_total_liquido = soma('valor_total_liquido');
    e.margem_bruta_valor = soma('margem_bruta_valor');
  }

  if((!Number(e.margem_bruta_pct||0)) && Number(e.valor_total||0)>0){
    e.margem_bruta_pct = Number(e.margem_bruta_valor||0) / Number(e.valor_total||0) * 100;
  }
  if((!Number(e.markup_realizado||0)) && Number(e.custo_total||0)>0){
    e.markup_realizado = Number(e.valor_total||0) / Number(e.custo_total||0);
  }
  return e || {};
}

let SERVICOS_RELATORIO=__JS_SERVICOS_RELATORIO__||{empresa:{},servicos:{},filiais:{},vendedores:{},detalhes:[]};
let CONFIG_META={grave_pct:20,alerta_pct:15,atencao_pct:10,peso_grave:60,peso_alerta:30,peso_atencao:10,bonus_50:'',bonus_75:'',bonus_85:'',bonus_100:'',cob_cred_rateio_filial_pct:50,cob_cred_rateio_cred_pct:50,cobranca_global_rateio_pct:20,cobranca_msg_template_terceira:`Olá, {primeiro_nome}. Tudo bem?
Aqui é da Lojas MDL - Móveis do Lar.

Já tentamos contato sobre a parcela vencida em {vencimento}, no valor de {valor}, referente ao título {titulo}/{parcela}.

Para evitar novos encargos e restrições, pedimos que regularize o pagamento o quanto antes.
Caso já tenha pago, por gentileza desconsidere esta mensagem.`,cobranca_msg_template:`Olá, {primeiro_nome} tudo bem?\nAqui é da Lojas MDL - Móveis do Lar.\nPassando para lembrar que tem uma parcelinha vencida na data de {vencimento}, no valor de {valor}.\nCaso o pagamento já tenha sido realizado, por gentileza, desconsidere esta mensagem.\nSe precisar do boleto, chave PIX ou tiver qualquer dúvida, fico à disposição para ajudar.`,...(__CONFIG_META__||{})};
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
const API_COMIS='historico_comissionamento_api.php';
const RELATORIOS_PUBLICOS=__JS_RELATORIOS_PUBLICOS__;

function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms));}
async function fetchComTimeout(url, opts={}, ms=3500){
  const ctrl = new AbortController();
  const timer = setTimeout(()=>{try{ctrl.abort()}catch(e){}}, ms);
  try{
    return await fetch(url,{...opts,cache:'no-store',signal:ctrl.signal});
  }finally{
    clearTimeout(timer);
  }
}
async function tentarAtualizarOnlineDepoisLogin(){
  try{
    await Promise.allSettled([
      carregarCredenciaisOnline(),
      carregarConfigOnline(),
      carregarHistoricoOnline(),
      carregarHistoricoComissaoOnline(),
      carregarCobrancasOnline(),
      carregarMsgsOnline()
    ]);
    try{renderKPIs()}catch(e){}
    try{refreshBell()}catch(e){}; try{renderLaranjitoNotify(); showLaranjitoOncePerAccess()}catch(e){}
    try{
      if(usuarioAtual?.tipo==='master'){
        if(!detailScreen.classList.contains('hidden') && currentDetailRef) openEntity(currentDetailRef);
        else renderList();
        if(isUltimoDiaMes23()) setTimeout(()=>salvarSnapshotComissionamentoMensal(true),900);
      }
    }catch(e){}
  }catch(e){console.log('Falha atualização online pós-login',e);}
}

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
let HIST_COMISSAO={months:{}};
const SESSION_KEY='mdl_dashboard_session_v1';
function getAuthUser(login){const k=String(login||'').trim().toLowerCase(); if(k===LOGIN_DIRETOR.toLowerCase()) return AUTH_STATE?.director||null; return (AUTH_STATE?.users||{})[k]||null}
async function carregarCredenciaisOnline(){try{const r=await fetchComTimeout(API_CRED+'?_='+Date.now(),{},2500); const j=await r.json(); if(j.ok && j.data){AUTH_STATE=j.data;}}catch(e){console.log('Falha ao carregar credenciais online',e);}}

async function carregarHistoricoOnline(){try{const r=await fetchComTimeout(API_HIST+'?_='+Date.now(),{},2500); const j=await r.json(); if(j.ok && j.data){HIST_DASH=j.data;}}catch(e){console.log('Falha ao carregar histórico online',e);}}
async function carregarHistoricoComissaoOnline(){try{const r=await fetchComTimeout(API_COMIS+'?_='+Date.now(),{},3000); const j=await r.json(); if(j.ok && j.data){HIST_COMISSAO=j.data;}}catch(e){console.log('Falha ao carregar histórico de comissionamento',e);}}



let LARANJITO_NOTES=[];
let LARANJITO_UNREAD=0;
function currentSessionNoticeKey(){
  return 'mdl_laranjito_seen_'+(usuarioAtual?.login||usuarioAtual?.nome||usuarioAtual?.tipo||'anon')+'_'+new Date().toISOString().slice(0,10);
}
function shouldShowLaranjitoBubble(){
  // Aparece somente para colaborador logado olhando o próprio painel individual.
  // Master/Diretor nunca veem essa bolinha, mesmo abrindo painel de alguém.
  try{
    const tipo=String(usuarioAtual?.tipo||'').toLowerCase();
    if(tipo==='master' || tipo==='diretor' || tipo==='painel') return false;
    const detail=document.getElementById('detailScreen');
    if(!(detail && !detail.classList.contains('hidden') && currentDetailRef)) return false;
    const login=String(usuarioAtual?.login||'').toLowerCase();
    const refLogin=String(currentDetailRef?.login||'').toLowerCase();
    const uNome=normName(usuarioAtual?.nome||'');
    const rNome=normName(currentDetailRef?.nome||'');
    const uFil=String(usuarioAtual?.filial||'').toUpperCase();
    const rFil=String(currentDetailRef?.filial||'').toUpperCase();
    if(login && refLogin && login!==refLogin) return false;
    if(uNome && rNome && uNome!==rNome && tipo==='vendedor') return false;
    if(uFil && rFil && uFil!==rFil && (tipo==='filial'||tipo==='crediarista'||tipo==='cobranca')) return false;
    return true;
  }catch(e){return false}
}
function addLaranjitoNote(title,msg,kind='info'){
  const key=String(title||'')+'|'+String(msg||'');
  if(LARANJITO_NOTES.some(n=>n.key===key)) return;
  LARANJITO_NOTES.push({key,title,msg,kind,dt:new Date().toLocaleString('pt-BR')});
  LARANJITO_UNREAD++;
  renderLaranjitoNotify();
}
function renderLaranjitoNotify(){
  const btn=document.getElementById('laranjitoNotify');
  const badge=document.getElementById('laranjitoNotifyBadge');
  const panel=document.getElementById('laranjitoNotifyPanel');
  if(!btn||!badge||!panel) return;


  try{
    const img=document.getElementById('laranjitoNotifyImg');
    const btn=document.getElementById('laranjitoNotify');
    if(img && !img.dataset.ready){
      img.dataset.ready='1';
      const urls=[
        '/colaborador/mascote%20feliz1.png',
        'https://moveisdolar.com.br/colaborador/mascote%20feliz1.png',
        (typeof LARANJITO!=='undefined' && LARANJITO)?LARANJITO:''
      ].filter(Boolean);
      let ix=0;
      img.onerror=function(){
        ix++;
        if(ix<urls.length){ this.src=urls[ix]; }
        else{ if(btn) btn.classList.add('img-fail'); }
      };
      img.onload=function(){ if(btn) btn.classList.remove('img-fail'); };
      img.src=urls[0];
    }
  }catch(e){}

  const visible = shouldShowLaranjitoBubble() && LARANJITO_NOTES.length>0;
  btn.style.display = visible ? 'flex' : 'none';
  if(!visible){panel.classList.remove('show'); return;}

  btn.classList.toggle('has-notes', LARANJITO_UNREAD>0);
  btn.classList.toggle('no-new', LARANJITO_UNREAD<=0);
  badge.textContent=String(LARANJITO_UNREAD||0);
  badge.style.display=(LARANJITO_UNREAD>0)?'flex':'none';

  panel.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">
    <strong>🍊 Alertas do Laranjito</strong>
    <button class="btn soft" onclick="clearLaranjitoNotes()">Marcar lidas</button>
  </div>` + LARANJITO_NOTES.map(n=>`<div class="laranjito-note"><div>${esc(n.title||'Aviso')}</div><div class="small">${esc(n.msg||'')}</div><div class="small">${esc(n.dt||'')}</div></div>`).join('');
}
function toggleLaranjitoNotifyPanel(){
  const panel=document.getElementById('laranjitoNotifyPanel');
  if(panel) panel.classList.toggle('show');
}
function clearLaranjitoNotes(){
  // Não apaga as mensagens. Apenas limpa o contador vermelho da bolinha.
  LARANJITO_UNREAD=0;
  try{localStorage.setItem(currentSessionNoticeKey(),'1')}catch(e){}
  renderLaranjitoNotify();
}
function showLaranjitoOncePerAccess(){
  // A bolinha aparece uma vez por acesso/login. Não joga mais toast sozinho toda hora.
  try{
    const k=currentSessionNoticeKey();
    if(localStorage.getItem(k)==='1') return;
    const panel=document.getElementById('laranjitoNotifyPanel');
    if(panel && LARANJITO_NOTES.length){
      setTimeout(()=>panel.classList.add('show'),700);
      localStorage.setItem(k,'1');
    }
  }catch(e){}
}

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

function emptyRec(){return {grave:[],alerta:[],atencao:[]}}
function recTotal(src){return ['grave','alerta','atencao'].reduce((acc,fx)=>acc+(src?.[fx]||[]).reduce((a,b)=>a+Number(b.pago||0),0),0)}
function recebimentosSomenteConciliados(ent){
  try{return mergeRecebimentosConciliados(emptyRec(), ent||{})}catch(e){return emptyRec()}
}

function crediaristaEntities(){return getCrediaristasConfig().map((row)=>{
  const filialKey=String(row.filial||'').toUpperCase();
  const loginKey=String(row.login||'').toLowerCase();
  const filData=FILIAIS?.[filialKey]||{};
  const nomeCred=String(row.nome||`Crediarista ${filialKey}`);
  const recOwn=recebimentosSomenteConciliados({type:'crediarista',login:loginKey,filial:filialKey,nome:nomeCred,is_crediarista:true});
  const gRec=(recOwn.grave||[]).reduce((a,b)=>a+Number(b.pago||0),0);
  const aRec=(recOwn.alerta||[]).reduce((a,b)=>a+Number(b.pago||0),0);
  const tRec=(recOwn.atencao||[]).reduce((a,b)=>a+Number(b.pago||0),0);
  const cli=CLIENTES_CREDIARISTA?.[loginKey]||{grave:[],alerta:[],atencao:[]};
  const gp=(cli.grave||[]).reduce((a,b)=>a+Number(b.pendente||0),0);
  const ap=(cli.alerta||[]).reduce((a,b)=>a+Number(b.pendente||0),0);
  const tp=(cli.atencao||[]).reduce((a,b)=>a+Number(b.pendente||0),0);
  const pendCred=gp+ap+tp; const recTotalOwn=gRec+aRec+tRec;
  return {type:'crediarista',login:loginKey,filial:filialKey,nome:nomeCred,pct_base:Number(row.pct||100),is_crediarista:true,is_gerente:false,only_cobranca:true,
    pendente:pendCred,pago:recTotalOwn,total:pendCred+recTotalOwn,perc_filial:100,
    grave_pend:gp,alerta_pend:ap,atencao_pend:tp,grave_rec:gRec,alerta_rec:aRec,atencao_rec:tRec,
    grave_alvo:gp*Number((CONFIG_META||{}).grave_pct||20)/100,alerta_alvo:ap*Number((CONFIG_META||{}).alerta_pct||15)/100,atencao_alvo:tp*Number((CONFIG_META||{}).atencao_pct||10)/100,
    grave_perc:gp>0?(gRec/(gp*Number((CONFIG_META||{}).grave_pct||20)/100)*100):0,
    alerta_perc:ap>0?(aRec/(ap*Number((CONFIG_META||{}).alerta_pct||15)/100)*100):0,
    atencao_perc:tp>0?(tRec/(tp*Number((CONFIG_META||{}).atencao_pct||10)/100)*100):0,
    perc_meta:0,rentabilidade_pct:Number(filData.rentabilidade_pct||0),sem_ativo:Boolean(filData.sem_ativo||false)};
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
const _toastOriginalLaranjito = toast;
toast = function(msg, type='info'){
  try{
    const s=String(msg||'');
    if(/parab[eé]ns|ganhou|meta|laranjito|comemorando|liberada|ótimo ritmo|otimo ritmo/i.test(s)){
      addLaranjitoNote('Tudo certo!', s, type);
      return;
    }
  }catch(e){}
  return _toastOriginalLaranjito(msg,type);
};

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
  triste: '/colaborador/mascote%20triste1.png',
  preocupado: '/colaborador/mascote%20preocupado1.png',
  feliz: '/colaborador/mascote%20feliz1.png'
};
function laranjitoSrc(status){
  return LARANJITO_IMG[status] || LARANJITO_IMG.triste;
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
  // ✅ Total de Serviços da tela inicial deve bater com o Controle de Meta do SGI.
  // Fonte oficial do TOTAL: sales.servico_realizado_total, vindo da tela /metas/consulta.
  // O relatório de serviços separado continua sendo usado apenas para detalhar por tipo
  // (Ouro, FOB, Cupom Copa etc.), mas não substitui o total oficial.
  const servicoRelatorioTotal = Number(SERVICOS_RELATORIO?.empresa?.real_total || 0);
  const servicoRealizadoOficial = Number(sales.servico_realizado_total || 0);
  const servicoAtingidoOficial = Number(sales.servico_meta_total||0)>0
    ? (servicoRealizadoOficial / Number(sales.servico_meta_total||0) * 100)
    : Number(sales.servico_atingido_total||0);

  const prevServicoReal = Number(prevEmpresa.servico_realizado_total || 0);
  const vendaDiaria=Math.max(0, Number(sales.venda_realizado_total||0)-Number(prevEmpresa.venda_realizado_total||0)) + Math.max(0, servicoRealizadoOficial-prevServicoReal);
  try{
    console.log('[MDL serviços]', {
      total_controle_meta_sgi: Number(sales.servico_realizado_total||0),
      total_relatorio_servicos_tipos: servicoRelatorioTotal,
      usado_no_card_servicos: servicoRealizadoOficial
    });
  }catch(e){}

  const RENT_OK=getRentEmpresa();
  RENT_EMPRESA=RENT_OK;
  const markupBase=(Number(sales.venda_realizado_total||0)+servicoRealizadoOficial);
  const markupCost=Number(RENT_OK?.custo_total||0);
  const markupTotal=markupCost>0?(markupBase/markupCost):0;
  try{
    console.log('[MDL margem]', {
      rent_empresa_boot: RENT_EMPRESA,
      margens_empresa: MARGENS_BRUTAS?.empresa,
      markupBase,
      markupCost,
      markupTotal
    });
  }catch(e){}
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
    if(n.includes('OURO')) return '🪙';
    if(n.includes('FOB')) return '🚚';
    if(n.includes('COPA') || n.includes('CUPOM')) return '⚽';
    return '🛠️';
  }
  const topServiceCards = Object.values((SERVICOS_RELATORIO && SERVICOS_RELATORIO.servicos) || {})
    .slice()
    .sort((a,b)=>Number(_srvTotal(b)||0)-Number(_srvTotal(a)||0))
    .slice(0,4)
    .map(s=>makeKpi(`${servicoIcone(s.servico)} ${String(s.servico||'Serviço').slice(0,30)}`, R(_srvTotal(s)||0), 'var(--blue-400)', `${Number(s.quantidade||0).toLocaleString('pt-BR')} item(ns)`));

  const cards=[
    makeKpi('💰 Total pendente',R(TOTAL_P),'var(--red)','', 'card-cobranca'),
    makeKpi('🏦 Total recebido',R(TOTAL_PG),'var(--green)','', 'card-cobranca'),
    makeKpi('🚨 Grave',R(grave),'var(--red)','', 'card-cobranca'),
    makeKpi('🟠 Alerta',R(alerta),'var(--orange)','', 'card-cobranca'),
    makeKpi('📦 Mercantil realizado',R(sales.venda_realizado_total||0),'var(--amber-400)',`Meta ${R(sales.venda_meta_total||0)} · Atingido ${pct(sales.venda_atingido_total||0)}`),
    makeKpi('📈 Mercantil projetado',R(sales.venda_projetado||0),'var(--amber-500)',`Meta período ${R(sales.venda_meta_periodo||0)}`),
    makeKpi('🛠️ Serviços realizado',R(servicoRealizadoOficial),'var(--blue)',`Meta ${R(sales.servico_meta_total||0)} · Atingido ${pct(servicoAtingidoOficial)} · controle de meta SGI`),
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

function renderUpdateStrip(){
  return `<div class="glass" style="margin:10px 0 14px;padding:10px 14px;display:flex;align-items:center;justify-content:flex-start;min-height:42px;border-color:rgba(148,163,184,.20)"><div style="font-size:12px;color:#a9b2c7">🕒 Última atualização do dashboard: <strong style="color:#e5e7eb">${esc(latestUpdatedLabel()||'--')}</strong></div></div>`;
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

    // Atualização atômica do pacote de vendas:
    // só busca metas/margens/serviços quando sales_version mudar.
    // Assim o dashboard não mistura parte nova de vendas com serviços/margem antigos.
    if(stamp && window.__lastSalesVersion===stamp && window.__salesBundleLoaded){
      return;
    }

    let metasWrap=null, margensWrap=null, servWrap=null;
    try{ metasWrap=await fetchJsonNoCache('metas_vendas_mes_atual.json'); }catch(_e){}
    try{ margensWrap=await fetchJsonNoCache('margens_brutas_mes_atual.json'); }catch(_e){}
    try{ servWrap=await fetchJsonNoCache('relatorio_servicos_mes_atual.json'); }catch(_e){}

    if(metasWrap) SALES_EMPRESA=calcSalesEmpresaFromMetas(metasWrap||{});
    if(margensWrap) RENT_EMPRESA=((margensWrap||{}).empresa)||{};
    if(servWrap) SERVICOS_RELATORIO=(servWrap||{});

    if(stamp) window.__lastSalesVersion=stamp;
    window.__salesBundleLoaded=true;

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


function _srvTotal(s){return Number((s&&((s.real_total_oficial!=null?s.real_total_oficial:null) ?? (s.total_oficial!=null?s.total_oficial:null) ?? s.real_total))||0);}
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
    const total = Number(_srvTotal(r)||0);
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
function setFiltroFilial(f){
  filtroFilial=f;
  renderFilters();

  const detalheAberto = !detailScreen.classList.contains('hidden');
  if(detalheAberto){
    if(mainTab==='filiais'){
      if(f && f!=='TODAS'){
        openEntity({type:'filial',filial:f,nome:filialLabel(f)});
        renderFilters();
        return;
      }
      detailScreen.classList.add('hidden');
      document.getElementById('mainScreen').classList.remove('hidden');
      renderList();
      return;
    }
    detailScreen.classList.add('hidden');
    document.getElementById('mainScreen').classList.remove('hidden');
  }
  renderList();
}
function currentEntities(){let arr=mainTab==='filiais'?flattenFiliais():flattenVendedores(); if(mainTab==='vendedores' && usuarioAtual?.tipo==='master'){const t=thirdChargeEntity(); const hasThird=Number(t.pendente||0)>0 || Number(t.pago||0)>0 || Number(t.grave_pend||0)>0 || Number(t.alerta_pend||0)>0 || Number(t.atencao_pend||0)>0; if(hasThird) arr=[t,...arr]; const creds=crediaristaEntities().filter(x=>Number(x.pendente||0)>0||Number(x.pago||0)>0); if(creds.length) arr=[...creds,...arr]} return arr.filter(x=>filtroFilial==='TODAS'||x.filial===filtroFilial || x.is_terceiro || x.is_crediarista)}
function renderEntityCard(ent){const m=calcMeta(ent); const isThird=!!(ent?.is_terceiro || ent?.type==='terceiro'); const isCred=!!(ent?.is_crediarista || ent?.type==='crediarista'); if(isThird || isCred){const credLogin=String(ent.login||crediaristaLoginByFilial(ent.filial)||'').toLowerCase(); const credFilial=String(ent.filial||'').toUpperCase(); const credNome=String(ent.nome||`CREDIARISTA${credFilial}`); const label=isThird?'Cobrança terceiro':'Crediarista'; const sub=isThird?'Clique para abrir a carteira terceirizada':'Clique para abrir a carteira do crediarista'; const actionAttr=isThird?`data-action="third-card" role="button" tabindex="0"`:`data-action="cred-card" data-login="${esc(credLogin)}" data-filial="${esc(credFilial)}" data-nome="${esc(credNome)}" role="button" tabindex="0"`; return `<div class="glass card ${m.geral>=50?'card-hit':(m.geral<30?'card-low-red':(m.geral<40?'card-low-orange':''))}" style="box-shadow:0 0 0 2px rgba(239,68,68,.12) inset" ${actionAttr}><div class="title">${esc(credNome)}</div><div class="numbers" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)"><div class="stat-box" style="min-width:0"><div class="mini">Pendente</div><div class="big" style="color:var(--red);font-size:15px;word-break:break-word">${R(ent.pendente||0)}</div></div><div class="stat-box" style="min-width:0"><div class="mini">Recebido</div><div class="big" style="color:var(--green);font-size:15px;word-break:break-word">${R(ent.pago||0)}</div></div></div><div class="meta-row"><div class="mini-chip">🔴 Grave ${pct(m.grave.perc)}</div><div class="mini-chip">🟠 Alerta ${pct(m.alerta.perc)}</div><div class="mini-chip">🟡 Atenção ${pct(m.atencao.perc)}</div><div class="mini-chip" style="font-size:12px">🔵 Meta geral ${pct(m.geral)}</div></div>${renderMascotStatus(m.geral,label)}<div class="legend-inline"><span><i class="dot" style="background:#2f67f6"></i>${sub}</span></div></div>`} const bonus=getBonus(m.cfg,m.geral);const sales=summarizeSalesCard(ent);const salesPct=sales?.n||0;const salesBorder=salesPct>=100?'box-shadow:0 0 0 2px rgba(242,201,76,.35) inset':salesPct>=80?'box-shadow:0 0 0 2px rgba(34,197,94,.18) inset':salesPct>=50?'box-shadow:0 0 0 2px rgba(249,115,22,.18) inset':'box-shadow:0 0 0 2px rgba(239,68,68,.12) inset';const cls=m.geral>=50?'card-hit':(m.geral<30?'card-low-red':(m.geral<40?'card-low-orange':''));const pulseNote=m.geral>=50?'<div class="legend-inline"><span><i class="dot" style="background:#2f67f6"></i>Meta atingida no mês</span></div>':'';return `<div class="glass card ${cls}" style="${salesBorder}" onclick='openEntity(${JSON.stringify({type:ent.type,filial:ent.filial,nome:ent.nome})})'><div class="title">${esc(ent.nome)} ${ent.type==='vendedor'?`(${ent.filial})`:''}</div><div class="numbers" style="grid-template-columns:minmax(0,1fr) minmax(0,1fr)"><div class="stat-box" style="min-width:0"><div class="mini">Pendente</div><div class="big" style="color:var(--red);font-size:15px;word-break:break-word">${R(ent.pendente||0)}</div></div><div class="stat-box" style="min-width:0"><div class="mini">Recebido</div><div class="big" style="color:var(--green);font-size:15px;word-break:break-word">${R(ent.pago||0)}</div></div></div><div class="meta-row"><div class="mini-chip">🔴 Grave ${pct(m.grave.perc)}</div><div class="mini-chip">🟠 Alerta ${pct(m.alerta.perc)}</div><div class="mini-chip">🟡 Atenção ${pct(m.atencao.perc)}</div><div class="mini-chip" style="font-size:12px">🔵 Meta geral ${pct(m.geral)}</div></div>${renderSalesCardSummary(ent)}${renderDualMascotStatus(ent)}${bonus?`<div class="legend-inline"><span><i class="dot" style="background:#2f67f6"></i>${esc(bonus.text)}</span></div>`:''}${pulseNote}</div>`}
function renderGroupBars(entities){if(!entities.length) return `<div class="empty">Nenhum dado para exibir.</div>`; const max=Math.max(1,...entities.map(e=>Math.max(Number(e.grave_pend||0),Number(e.alerta_pend||0),Number(e.atencao_pend||0),Number(e.pago||0)))); return `<div class="glass big-chart-card"><div class="section-head"><div><h2>📊 Panorama por ${mainTab==='filiais'?'filial':'vendedor'}</h2><div class="hint">Barras por faixa: Grave, Alerta, Atenção e Recebido</div></div><div class="legend-inline"><span><i class="dot" style="background:var(--red)"></i>Grave</span><span><i class="dot" style="background:var(--orange)"></i>Alerta</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção</span><span><i class="dot" style="background:var(--green)"></i>Recebido</span></div></div><div class="groupbars">${entities.map(e=>{const vals=[{c:'var(--red)',v:Number(e.grave_pend||0),t:'Grave'},{c:'var(--orange)',v:Number(e.alerta_pend||0),t:'Alerta'},{c:'var(--yellow)',v:Number(e.atencao_pend||0),t:'Atenção'},{c:'var(--green)',v:Number(e.pago||0),t:'Recebido'}]; return `<div class="group"><div class="bars">${vals.map(v=>`<div title="${v.t}: ${R(v.v)}" class="bar" style="height:${Math.max(12,(v.v/max)*240)}px;background:linear-gradient(180deg,${v.c},${v.c})"></div>`).join('')}<span class="wave one"></span><span class="wave two"></span><span class="bubble b1"></span><span class="bubble b2"></span><span class="bubble b3"></span></div><div class="glabel">${esc(trunc(e.nome,16))}</div></div>`}).join('')}</div><div class="axis"><span>Escala relativa automática</span><span>${entities.length} ${mainTab==='filiais'?'filiais':'colaboradores'}</span></div></div>`}

function renderNoChargeAlerts(){
  const hoje=(new Date()).toISOString().slice(0,10);
  const totalPend=(obj)=>((obj?.grave||[]).length+(obj?.alerta||[]).length+(obj?.atencao||[]).length);
  const doneHoje=(keys)=>(COB_LOGS||[]).filter(x=>{
    const u=String(x.usuario||'').toLowerCase();
    return keys.map(k=>String(k||'').toLowerCase()).includes(u) && String(x.server_time||'').slice(0,10)===hoje;
  }).length;
  const entries=[];

  // Vendedores / colaboradores
  flattenVendedores().forEach(v=>{
    const pending=totalPend(CLIENTES_VEND[v.nome]||{});
    const done=doneHoje([v.nome, v.login]);
    if(pending>0 && done===0) entries.push({tipo:'Colaborador',nome:v.nome,filial:v.filial,pending,done});
  });

  // Filiais / gerentes
  flattenFiliais().forEach(f=>{
    const pending=totalPend(CLIENTES_FIL[f.filial]||{});
    const done=doneHoje([f.nome, f.filial, filialLabel(f.filial)]);
    if(pending>0 && done===0) entries.push({tipo:'Filial',nome:filialLabel(f.filial),filial:f.filial,pending,done});
  });

  // Crediaristas
  crediaristaEntities().forEach(c=>{
    const key=String(c.login||'').toLowerCase();
    const pending=totalPend(CLIENTES_CREDIARISTA[key]||{});
    const done=doneHoje([c.nome, c.login, c.filial]);
    if(pending>0 && done===0) entries.push({tipo:'Crediarista',nome:c.nome,filial:c.filial,pending,done});
  });

  // Cobrança terceiro / Cobrança10
  const t=thirdChargeEntity();
  const pendingTer=totalPend(CLIENTES_TERCEIRO||{});
  const doneTer=doneHoje([COBRANCA10_NOME, COBRANCA10_LOGIN, 'cobranca10']);
  if(pendingTer>0 && doneTer===0) entries.push({tipo:'Cobrança',nome:COBRANCA10_NOME,filial:'FTER',pending:pendingTer,done:doneTer});

  const uniq=[];
  const seen=new Set();
  entries.forEach(e=>{
    const k=`${e.tipo}|${e.nome}|${e.filial}`;
    if(!seen.has(k)){seen.add(k); uniq.push(e);}
  });
  uniq.sort((a,b)=>String(a.tipo).localeCompare(String(b.tipo),'pt-BR') || Number(b.pending||0)-Number(a.pending||0));
  if(!uniq.length) return '';
  return `<div class="glass panel" style="margin-bottom:16px;padding:14px 18px">
    <div class="section-head" style="margin:0">
      <div><h2 style="margin:0;font-size:18px">⏰ Sem cobranças hoje</h2><div class="hint">Todos os usuários/carteiras que ainda não registraram cobrança hoje: colaboradores, filiais, crediaristas e cobrança.</div></div>
    </div>
    <div class="sem-cobrancas-grid">${uniq.map(e=>`<div class="sem-cobranca-chip"><i class="dot" style="background:#ef4444"></i><div>${esc(e.nome)}<small>${esc(e.tipo)} ${e.filial?`· ${esc(e.filial)}`:''} · ${e.pending} clientes</small></div></div>`).join('')}</div>
  </div>`;
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

function renderTerceiroDetail(ent){const src=getClientesEnt(ent); const totalTit=(src.grave?.length||0)+(src.alerta?.length||0)+(src.atencao?.length||0); detailScreen.innerHTML=`${renderUpdateStrip()}<div class="back-row"><button class="btn soft" onclick="backToMain()">⬅️ Voltar</button><div><h2>${esc(ent.nome)}</h2><div class="sub">${ent.is_crediarista?`Painel de cobrança da filial ${ent.filial} · base configurada ${Number(ent.pct_base||100)}% · recebido só por cobrança própria paga`:`Painel de cobrança terceirizada · percentual global sem duplicidade`}</div></div><div class="badge">${ent.is_crediarista?'🧾 Crediarista':'🤝 Cobrança terceiro'}</div></div><div class="detail-top"><div class="glass panel"><h3>🧾 Resumo da carteira</h3><div class="metrics-grid"><div class="metric"><div class="k">Títulos</div><div class="v">${totalTit}</div></div><div class="metric"><div class="k">Pendente</div><div class="v" style="color:var(--red)">${R(ent.pendente||0)}</div></div><div class="metric"><div class="k">Recebido</div><div class="v" style="color:var(--green)">${R(ent.pago||0)}</div></div><div class="metric"><div class="k">Cobrado hoje</div><div class="v">${getCobradosHoje(ent).length}</div></div></div><div class="legend-inline" style="margin-top:12px"><span><i class="dot" style="background:var(--red)"></i>Grave ${src.grave?.length||0}</span><span><i class="dot" style="background:var(--orange)"></i>Alerta ${src.alerta?.length||0}</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção ${src.atencao?.length||0}</span></div></div><div>${renderTerceiroCommission(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">💰 Recebimentos por faixa <span>clique para abrir</span></div><div class="acc-body">${renderRecebimentos(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">🧾 Relatório de cobranças <span>clique para abrir</span></div><div class="acc-body">${renderCobrancasEnt(ent)}</div></div>`}

// ── PAINEL CREDIARISTA ─────────────────────────────────────────────────────
// Mostra: resumo da carteira espelhada + meta de cobrança + recebimentos + cobranças
// NÃO mostra: painel de vendas, comissão mercantil, campanhas de venda
function renderCrediaristaDetail(ent){
  const src=getClientesEnt(ent);
  const totalTit=(src.grave?.length||0)+(src.alerta?.length||0)+(src.atencao?.length||0);
  const meta=calcMeta(ent);
  detailScreen.innerHTML=`
    ${renderInboxBanner()}
    ${renderUpdateStrip()}
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

function openEntity(ref){if(ref && (ref.type==='crediarista' || ref.is_crediarista)){return openCrediaristaPanel(ref.login||'', ref.filial||'', ref.nome||'')} const ent=findEntity(ref); if(!ent) return; currentDetailRef={type:ent.type,filial:ent.filial,nome:ent.nome,login:ent.login||''}; mascotCongrats(ent); try{renderLaranjitoNotify(); showLaranjitoOncePerAccess()}catch(e){}; document.getElementById('mainScreen').classList.add('hidden'); detailScreen.classList.remove('hidden'); if(ent.is_terceiro || ent.type==='terceiro'){return renderTerceiroDetail(ent)} if(ent.is_crediarista || ent.type==='crediarista'){return openCrediaristaPanel(ent.login||'', ent.filial||'', ent.nome||'')} const meta=calcMeta(ent); const bonus=getBonus(meta.cfg,meta.geral); const deltaVal=Number(ent.var_pago_delta||0); const prevBase=Math.max(Math.abs(Number(ent.pago||0)-deltaVal),1); const pctFallback=(Math.abs(deltaVal)/prevBase)*100; const compPerc=(ent.var_pago_perc==null || Math.abs(Number(ent.var_pago_perc||0))<0.01)?pctFallback:Math.abs(Number(ent.var_pago_perc||0)); detailScreen.innerHTML=`${usuarioAtual && usuarioAtual.tipo!=='master' ? renderInboxBanner() : ''}${renderUpdateStrip()}<div class="back-row"><button class="btn soft" onclick="backToMain()">⬅️ Voltar</button><div><h2>${ent.type==='filial'?filialLabel(ent.filial):esc(ent.nome)}</h2><div class="sub">${ent.type==='filial'?'Painel individual da filial':'Painel individual do vendedor'} · ${ent.filial}</div></div><div class="badge">${ent.type==='filial'?'🏬 Filial':'👤 Vendedor'}</div></div><div class="detail-top"><div class="glass panel"><h3>🎯 Meta do mês <span class="note">· Não acumulativo</span></h3><div class="mega-progress"><div class="ring-wrap">${renderPiggyBank(meta.geral)}</div><div><div class="metrics-grid"><div class="metric"><div class="k">Pendente</div><div class="v" style="color:var(--red)">${R(ent.pendente||0)}</div></div><div class="metric"><div class="k">Recebido</div><div class="v" style="color:var(--green)">${R(ent.pago||0)}</div></div><div class="metric"><div class="k">% da filial</div><div class="v">${pct(ent.perc_filial||100)}</div></div><div class="metric"><div class="k">Configuração usada</div><div class="v">${Number(meta.cfg.grave_pct||0)}/${Number(meta.cfg.alerta_pct||0)}/${Number(meta.cfg.atencao_pct||0)}</div></div><div class="metric"><div class="k">Comparado a ontem</div><div class="v" style="font-size:16px">${renderDeltaPill(ent.var_pago_delta,compPerc)} <span>${R(Math.abs(Number(ent.var_pago_delta||0)))}</span></div></div></div><div class="legend-inline" style="margin-top:12px"><span><i class="dot" style="background:var(--red)"></i>Grave alvo ${R(meta.grave.alvo)} · recebido ${R(meta.grave.rec)}</span><span><i class="dot" style="background:var(--orange)"></i>Alerta alvo ${R(meta.alerta.alvo)} · recebido ${R(meta.alerta.rec)}</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção alvo ${R(meta.atencao.alvo)} · recebido ${R(meta.atencao.rec)}</span></div></div></div><div class="meta-grid">${renderMetaBox('Grave','var(--red)',meta.grave)}${renderMetaBox('Alerta','var(--orange)',meta.alerta)}${renderMetaBox('Atenção','var(--yellow)',meta.atencao)}${renderMetaBox('Meta geral','var(--blue)',{perc:meta.geral,alvo:meta.grave.alvo+meta.alerta.alvo+meta.atencao.alvo,rec:meta.grave.rec+meta.alerta.rec+meta.atencao.rec})}</div><div style="height:18px"></div><h3>🌊 Gráfico Geral Contas a Receber</h3>${renderSingleBars(ent,meta,true)}<div style="height:16px"></div><div class="glass panel"><h3>🏆 Bônus e premiações <span class="note">· Não acumulativo</span></h3>${renderBonusBox(meta.cfg,meta.geral)}</div></div><div>${renderSalesPanel(ent)}<div style="height:16px"></div>${renderCommissionSummary(ent)}<div style="height:16px"></div>${renderCampaignSummary(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">💰 Recebimentos por faixa <span>clique para ${'abrir'}</span></div><div class="acc-body">${renderRecebimentos(ent)}</div></div><div class="accordion"><div class="acc-head" onclick="toggleAcc(this)">🧾 Relatório de cobranças <span>clique para ${'abrir'}</span></div><div class="acc-body">${renderCobrancasEnt(ent)}</div></div>`}
function canVerComissionamento(){return usuarioAtual?.tipo==='master'}
function renderCommissionSummary(ent){if(!canVerComissionamento()) return '';
  const c=calcCommissionSummary(ent);
  const totalLiberado = Number(c.totalPrevisto||0)>0;
  const totalExibido = c.totalPrevisto || 0;
  const moneyCell=(title,val,locked=false,extra='')=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''} ${extra}"><div class="k">${title}</div><div class="v">${R(val||0)}</div></div>`;
  const pctCell=(title,val,locked=false)=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''}"><div class="k">${title}</div><div class="v">${String(Number(val||0).toFixed(2)).replace('.',',')}%</div></div>`;
  const rentNote = c.rentUnlocked
    ? `Rentabilidade atual ${String(Number(c.rentAtual||0).toFixed(2)).replace('.',',')}% · faixa aplicada ${c.rentFaixaTxt}.`
    : `Rentabilidade atual ${String(Number(c.rentAtual||0).toFixed(2)).replace('.',',')}% · bloqueada até bater 50% da meta de cobrança.`;
  return `<div class="glass panel commission-card"><h3>💵 Comissionamento previsto <span class="note">· calculado pela política salva</span></h3>${c.metaAtingida?`<div class="meta-hit-banner"><img src="${LARANJITO}" alt=""><span>Meta liberada! O Laranjito está comemorando sua liberação de comissão/bonus.</span></div>`:''}<div class="commission-grid">${`<div class="commission-item unlocked"><div class="k">Faixa aplicada</div><div class="v" style="font-size:16px">${esc(c.faixaTxt)}</div></div>`}${pctCell('% comissão mercantil',c.comPerc,!c.elegivelMercantil)}${pctCell('% serviços',c.servPct,!c.elegivelServicos)}${pctCell('% caminhão',c.camPct,!c.elegivelServicos)}${moneyCell('Comissão vendas',c.vendasComissao,!c.elegivelMercantil)}${moneyCell('Comissão serviços',c.servicosComissao,!c.elegivelServicos)}${moneyCell('Comissão caminhão',c.caminhaoComissao,!c.elegivelServicos)}${moneyCell('Bônus por meta',c.bonusMeta,!c.bonusLiberado)}${moneyCell('Rentab 48%',c.rent48,!(c.rentUnlocked && c.rentAtual>=48))}${moneyCell('Rentab 52,15%',c.rent52,!(c.rentUnlocked && c.rentAtual>=52.15))}${moneyCell('Rentab 55,50%',c.rent55,!(c.rentUnlocked && c.rentAtual>=55.50))}${moneyCell('Total previsto',totalExibido,!totalLiberado,'total-final '+(!totalLiberado?'total-locked':''))}</div><div class="commission-note">Base mercantil bruta: ${R(c.vendaRealBruto||0)} · Caminhão abatido: ${R(c.camReal||0)} · Mercantil líquido para comissão: ${R(c.vendaReal||0)} · Serviço: ${R(c.servReal||0)}. Mínimo comissão mercantil ${pct(c.minVenda)} · mínimo serviços/caminhão ${pct(c.minServico)}. Bônus meta mercantil: vendedor 90/100/120%; gerente/classificação loja a partir de 90%. Rentabilidades liberam ao bater 50% da meta de cobrança. ${rentNote}</div></div>`
}

function backToMain(){currentDetailRef=null; try{renderLaranjitoNotify()}catch(e){}; detailScreen.classList.add('hidden');document.getElementById('mainScreen').classList.remove('hidden')}
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
  return out.sort((a,b)=>Number(_srvTotal(b)||0)-Number(_srvTotal(a)||0));
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
  const servAtingido=salesNum(salesCell(servRow,['Atingido Total']));
  const camReal=moneyNum(salesCell(camRow,['Realizado (R$) Total','Realizado(R$) Total']));
  const camAtingido=salesNum(salesCell(camRow,['Atingido Total']));
  const vendaReal=Math.max(0,vendaRealBruto-camReal);
  const policy=ent.type==='filial'?cc.gerente_policy:cc.vendedor_policy;
  const faixa=faixaMatchRealizado(policy,vendaReal) || {};
  const comPerc=Number(faixa.comissao||0);
  const servPct=Number(faixa.servico_pct||0);
  const camPct=Number(faixa.caminhao_pct||0);
  let bonusMeta=0;
  let bonusLiberado=false;
  const minVenda = ent.type==='filial' ? Number(cfg.gerente_vendas_min_pct||80) : Number(cfg.vendas_min_pct||80);
  const minServico = ent.type==='filial' ? Number(cfg.gerente_servicos_min_pct||80) : Number(cfg.servicos_min_pct||80);
  const bonusMercantilMin = 90; // bônus vendedor e classificação loja/gerente só a partir de 90% da meta mercantil
  const rentMin50 = 50;
  const geralMeta = calcMeta(ent).geral||0;
  const elegivelMercantil=vendaPerc>=minVenda;
  const elegivelServicos=servAtingido>=minServico;
  const elegivelCaminhao=camRow ? (camAtingido>=minServico) : elegivelServicos;
  const vendasComissao=elegivelMercantil?(vendaReal*comPerc/100):0;
  const servicosComissao=elegivelServicos?(servReal*servPct/100):0;
  const caminhaoComissao=elegivelCaminhao?(camReal*camPct/100):0;
  if(ent.type==='filial'){
    if(vendaPerc>=bonusMercantilMin){ bonusMeta=Number(faixa.bonusLoja||0); bonusLiberado=bonusMeta>0; }
  } else {
    if(vendaPerc>=120){ bonusMeta=Number(faixa.bonus120||0); bonusLiberado=bonusMeta>0; }
    else if(vendaPerc>=100){ bonusMeta=Number(faixa.bonus100||0); bonusLiberado=bonusMeta>0; }
    else if(vendaPerc>=90){ bonusMeta=Number(faixa.bonus90||0); bonusLiberado=bonusMeta>0; }
  }

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
    vendaRealBruto,vendaReal,vendaPerc,servReal,servAtingido,camReal,camAtingido,comPerc,servPct,camPct,
    vendasComissao,servicosComissao,caminhaoComissao,bonusMeta,bonusLiberado,
    elegivelMercantil,elegivelServicos,elegivelCaminhao,rentUnlocked,rent48,rent52,rent55,
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

function renderCommissionSummary(ent){if(!canVerComissionamento()) return '';const c=calcCommissionSummary(ent); const totalLiberado = Number(c.totalPrevisto||0)>0; const totalExibido = c.totalPrevisto || 0; const moneyCell=(title,val,locked=false,extra='')=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''} ${extra}"><div class="k">${title}</div><div class="v">${R(val||0)}</div></div>`; const pctCell=(title,val,locked=false)=>`<div class="commission-item ${locked?'locked':''} ${!locked?'unlocked':''}"><div class="k">${title}</div><div class="v">${String(Number(val||0).toFixed(2)).replace('.',',')}%</div></div>`; return `<div class="glass panel commission-card"><h3>💵 Comissionamento previsto <span class="note">· calculado pela política salva</span></h3>${c.metaAtingida?`<div class="meta-hit-banner"><img src="${LARANJITO}" alt=""><span>Meta liberada! O Laranjito está comemorando sua liberação de comissão/bonus.</span></div>`:''}<div class="commission-grid">${`<div class="commission-item unlocked"><div class="k">Faixa aplicada</div><div class="v" style="font-size:16px">${esc(c.faixaTxt)}</div></div>`}${pctCell('% comissão mercantil',c.comPerc,!c.elegivelMercantil)}${pctCell('% serviços',c.servPct,!c.elegivelServicos)}${pctCell('% caminhão',c.camPct,!c.elegivelServicos)}${moneyCell('Comissão vendas',c.vendasComissao,!c.elegivelMercantil)}${moneyCell('Comissão serviços',c.servicosComissao,!c.elegivelServicos)}${moneyCell('Comissão caminhão',c.caminhaoComissao,!c.elegivelServicos)}${moneyCell('Bônus por meta',c.bonusMeta,!c.bonusLiberado)}${moneyCell('Rentab 48%',c.rent48,!c.rentUnlocked)}${moneyCell('Rentab 52,15%',c.rent52,!c.rentUnlocked)}${moneyCell('Rentab 55,50%',c.rent55,!c.rentUnlocked)}${moneyCell('Total previsto',totalExibido,!totalLiberado,'total-final '+(!totalLiberado?'total-locked':''))}</div><div class="commission-note">Base mercantil bruta: ${R(c.vendaRealBruto||0)} · Caminhão abatido: ${R(c.camReal||0)} · Mercantil líquido para comissão: ${R(c.vendaReal||0)} · Serviço: ${R(c.servReal||0)}. Mínimo comissão mercantil ${pct(c.minVenda)} · mínimo serviços/caminhão ${pct(c.minServico)}. Bônus meta mercantil: vendedor 90/100/120%; gerente/classificação loja a partir de 90%. Rentabilidades liberam ao bater 50% da meta de cobrança.</div></div>`}
function backToMain(){currentDetailRef=null; try{renderLaranjitoNotify()}catch(e){}; detailScreen.classList.add('hidden');document.getElementById('mainScreen').classList.remove('hidden')}
function renderMetaBox(title,color,obj){return `<div class="meta-card"><div class="meta-title">${title}</div><div class="meta-main" style="color:${color}">${pct(obj.perc||0)}</div><div class="meta-sub">Alvo: ${R(obj.alvo||0)}</div><div class="meta-sub">Recebido: ${R(obj.rec||0)}</div></div>`}
function renderBonusBox(cfg,geral){const achieved=(geral>=100&&cfg.bonus_100)?100:(geral>=85&&cfg.bonus_85)?85:(geral>=75&&cfg.bonus_75)?75:(geral>=50&&cfg.bonus_50)?50:0; const items=[[50,cfg.bonus_50||'-'],[75,cfg.bonus_75||'-'],[85,cfg.bonus_85||'-'],[100,cfg.bonus_100||'-']];return `<div class="bonus-box"><h4>Faixas configuradas</h4><div class="bonus-list">${items.map(([p,t])=>`<div class="bonus-item ${achieved===p?'active':''}" style="${achieved===p?'box-shadow:0 0 0 2px rgba(59,130,246,.18),0 0 26px rgba(59,130,246,.2);animation:liquid 1.6s ease-in-out infinite alternate':''}"><div class="left"><span>🎯</span><span>${p}%</span></div><div style="display:flex;align-items:center;gap:10px">${achieved===p?`<img src="${LARANJITO}" alt="laranjito" style="width:34px;height:34px;border-radius:10px;object-fit:cover">`:''}<span>${esc(t)}</span></div></div>`).join('')}</div></div>`}
function renderSingleBars(ent,meta,big=false){const vals=[['Grave',meta.grave.pend,'var(--red)'],['Alerta',meta.alerta.pend,'var(--orange)'],['Atenção',meta.atencao.pend,'var(--yellow)'],['Recebido',Number(ent.pago||0),'var(--green)']]; const max=Math.max(1,...vals.map(v=>v[1])); return `<div class="glass big-chart-card" style="margin-top:0"><div class="legend-inline"><span><i class="dot" style="background:var(--red)"></i>Grave</span><span><i class="dot" style="background:var(--orange)"></i>Alerta</span><span><i class="dot" style="background:var(--yellow)"></i>Atenção</span><span><i class="dot" style="background:var(--green)"></i>Recebido</span></div><div class="groupbars" style="justify-content:center"><div class="group" style="min-width:100%"><div class="bars" style="height:${big?320:260}px;justify-content:space-around;border-left:none">${vals.map(v=>`<div style="text-align:center"><div class="bar" style="width:${big?72:54}px;height:${Math.max(18,(v[1]/max)*(big?250:200))}px;background:linear-gradient(180deg,rgba(255,255,255,.18),transparent),linear-gradient(180deg,${v[2]},${v[2]})"><span class="wave one"></span><span class="wave two"></span><span class="bubble b1"></span><span class="bubble b2"></span><span class="bubble b3"></span></div><div class="glabel" style="margin-top:10px">${v[0]}<br><strong>${R(v[1])}</strong></div></div>`).join('')}</div></div></div></div>`}
function recebKeyVend(ent){return `${ent.nome}_${ent.filial}`}

function normConc(s){return String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toUpperCase().replace(/[^A-Z0-9]+/g,' ').trim()}
function parseDataBRjs(s){
  const m=String(s||'').match(/(\d{2})\/(\d{2})\/(\d{4})/);
  if(!m) return null;
  return new Date(Number(m[3]), Number(m[2])-1, Number(m[1]));
}
function similarCliente(a,b){
  const x=normConc(a), y=normConc(b);
  if(!x || !y) return false;
  return x===y || x.includes(y.slice(0,18)) || y.includes(x.slice(0,18));
}
function getQuitadosConciliados(){
  const out={};
  const logs=(COB_LOGS||[]).slice().filter(l=>String(l.acao||'')==='whatsapp' || l.telefone || l.titulo || l.parcela);
  const byTitulo={};
  logs.forEach(l=>{
    const k=`${String(l.titulo||'').trim()}|${String(l.parcela||'').trim()}`;
    if(!byTitulo[k]) byTitulo[k]=[];
    byTitulo[k].push(l);
  });

  (QUITADOS_180||[]).forEach(q=>{
    const k=`${String(q.titulo||'').trim()}|${String(q.parcela||'').trim()}`;
    const cand=(byTitulo[k]||[]).filter(l=>similarCliente(l.cliente,q.cliente));
    if(!cand.length) return;

    const pagto=parseDataBRjs(q.pagamento);
    if(!pagto) return;

    const antes=cand.filter(l=>{
      const raw=String(l.server_time||l.criado_em||l.data||'');
      const d=raw ? new Date(raw.replace(' ', 'T')) : null;
      if(!d || isNaN(d.getTime())) return true;
      const diffDias=(pagto-d)/(1000*60*60*24);
      return diffDias>=0 && diffDias<=180;
    });
    if(!antes.length) return;

    antes.sort((a,b)=>String(a.server_time||'').localeCompare(String(b.server_time||'')));
    const l=antes[antes.length-1];

    const usuarioKey=normConc(l.usuario||l.destino_nome||'');
    const destinoKey=normConc(l.destino_nome||'');
    const filialKey=String(l.filial||q.filial||'').toUpperCase();
    const faixa=q.faixa||'grave';
    const rec={
      cliente:q.cliente,
      dias:q.dias_atraso_pagamento,
      pago:Number(q.pago||0),
      vencimento:q.vencimento,
      pagamento:q.pagamento,
      parcela:q.parcela,
      titulo:q.titulo,
      vendedor:l.usuario||l.destino_nome||'',
      origem:'conciliado_quitados_180d',
      cobrador:l.usuario||'',
      destino_nome:l.destino_nome||'',
      destino_tipo:l.destino_tipo||'',
      filial:filialKey
    };

    [usuarioKey,destinoKey,normConc(`${l.destino_nome||''}_${filialKey}`),normConc(`${l.usuario||''}_${filialKey}`),normConc(filialKey)].forEach(key=>{
      if(!key) return;
      if(!out[key]) out[key]={grave:[],alerta:[],atencao:[]};
      if(!out[key][faixa]) out[key][faixa]=[];
      // evita duplicar no mesmo key
      const exists=out[key][faixa].some(x=>String(x.titulo)===String(rec.titulo)&&String(x.parcela)===String(rec.parcela)&&similarCliente(x.cliente,rec.cliente));
      if(!exists) out[key][faixa].push(rec);
    });
  });

  return out;
}
function mergeRecebimentosConciliados(base, ent){
  const result={
    grave:[...((base||{}).grave||[])],
    alerta:[...((base||{}).alerta||[])],
    atencao:[...((base||{}).atencao||[])]
  };
  const keys=[
    normConc(ent?.nome),
    normConc(ent?.login),
    normConc(ent?.filial),
    normConc(`${ent?.nome||''}_${ent?.filial||''}`),
    normConc(`${ent?.login||''}_${ent?.filial||''}`)
  ].filter(Boolean);
  keys.forEach(k=>{
    const extra=RECEBIMENTOS_CONCILIADOS[k];
    if(!extra) return;
    ['grave','alerta','atencao'].forEach(fx=>{
      (extra[fx]||[]).forEach(r=>{
        const exists=result[fx].some(x=>String(x.titulo)===String(r.titulo)&&String(x.parcela)===String(r.parcela)&&similarCliente(x.cliente,r.cliente));
        if(!exists) result[fx].push(r);
      });
    });
  });
  ['grave','alerta','atencao'].forEach(fx=>result[fx].sort((a,b)=>Number(b.pago||0)-Number(a.pago||0)));
  return result;
}

function getRecebimentos(ent){
  let base;
  if(ent.type==='terceiro' || ent.is_terceiro) base=RECEBIMENTOS_TERCEIRO||{grave:[],alerta:[],atencao:[]};
  else if(ent.type==='crediarista' || ent.is_crediarista){
    // Crediarista: somente recebimentos conciliados com cobrança feita pelo próprio usuário antes do pagamento.
    base={grave:[],alerta:[],atencao:[]};
  } else if(ent.type==='vendedor') base=RECEBIMENTOS[recebKeyVend(ent)]||{grave:[],alerta:[],atencao:[]};
  else {
    base={grave:[],alerta:[],atencao:[]};
    Object.entries(RECEBIMENTOS||{}).forEach(([k,v])=>{if(k.endsWith('_'+ent.filial)){['grave','alerta','atencao'].forEach(fx=>base[fx].push(...(v[fx]||[])))}}); 
  }
  base=mergeRecebimentosConciliados(base, ent||{});
  ['grave','alerta','atencao'].forEach(fx=>base[fx].sort((a,b)=>Number(b.pago||0)-Number(a.pago||0)));
  return base;
}
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

const DEFAULT_COBRANCA_TEMPLATE = `Olá, {primeiro_nome} tudo bem?
Aqui é da Lojas MDL - Móveis do Lar.
Passando para lembrar que tem uma parcelinha vencida na data de {vencimento}, no valor de {valor}.
Caso o pagamento já tenha sido realizado, por gentileza, desconsidere esta mensagem.
Se precisar do boleto, chave PIX ou tiver qualquer dúvida, fico à disposição para ajudar.`;

function cobrancaTemplateAtual(){
  return String(CONFIG_META?.cobranca_msg_template || DEFAULT_COBRANCA_TEMPLATE);
}
function primeiroNomeClienteJs(nome){
  const s=String(nome||'').trim();
  return s ? s.split(/\s+/)[0] : 'Cliente';
}
function valorBR(v){
  return Number(v||0).toLocaleString('pt-BR',{style:'currency',currency:'BRL'});
}

function parseCobDate(raw){
  if(!raw) return null;
  const s=String(raw).trim();
  let d=null;
  // aceita ISO, "YYYY-MM-DD HH:mm:ss", ou data local
  d=new Date(s.replace(' ', 'T'));
  if(!d || isNaN(d.getTime())){
    const m=s.match(/(\d{2})\/(\d{2})\/(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
    if(m) d=new Date(Number(m[3]),Number(m[2])-1,Number(m[1]),Number(m[4]||0),Number(m[5]||0));
  }
  return (d && !isNaN(d.getTime()))?d:null;
}
function fmtCobDate(raw){
  const d=parseCobDate(raw);
  if(!d) return String(raw||'');
  return d.toLocaleString('pt-BR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});
}
function daysSinceCob(raw){
  const d=parseCobDate(raw);
  if(!d) return 9999;
  return Math.floor((Date.now()-d.getTime())/(1000*60*60*24));
}
function sameCobTitle(a,b){
  return String(a?.titulo||'').trim()===String(b?.titulo||'').trim()
      && String(a?.parcela||'').trim()===String(b?.parcela||'').trim()
      && (typeof similarCliente==='function' ? similarCliente(a?.cliente||a?.nome||'', b?.cliente||b?.nome||'') : normName(a?.cliente||a?.nome||'')===normName(b?.cliente||b?.nome||''));
}
function entMatchesCobLog(log,ent){
  if(!ent) return true;
  const usuario=String(log.usuario||'').toLowerCase();
  const destinoNome=String(log.destino_nome||'');
  const destinoTipo=String(log.destino_tipo||'').toLowerCase();
  const filial=String(log.filial||'').toUpperCase();
  if(ent.type==='terceiro'||ent.is_terceiro) return destinoTipo==='terceiro' || usuario.includes('terceiro') || String(ent.nome||'')===destinoNome;
  if(ent.type==='crediarista'||ent.is_crediarista){
    const login=String(ent.login||ent.nome||'').toLowerCase();
    return usuario===login || destinoNome===String(ent.nome||'') || (destinoTipo==='crediarista' && filial===String(ent.filial||'').toUpperCase());
  }
  if(ent.type==='filial') return filial===String(ent.filial||'').toUpperCase() && (destinoTipo==='filial' || destinoNome===String(ent.nome||'') || !destinoTipo);
  return destinoNome===String(ent.nome||'') || usuario===String(ent.nome||'').toLowerCase();
}
function cobLogsTitulo(reg,ent=null){
  return (COB_LOGS||[]).filter(x=>String(x.acao||'')==='whatsapp' && sameCobTitle(x,reg) && entMatchesCobLog(x,ent))
    .sort((a,b)=>(parseCobDate(a.server_time||a.data)||0)-(parseCobDate(b.server_time||b.data)||0));
}
function pagamentoAposCobranca(reg,log){
  const dtLog=parseCobDate(log?.server_time||log?.data);
  if(!dtLog) return false;
  return (QUITADOS_180||[]).some(q=>{
    if(!sameCobTitle(q,reg)) return false;
    const dp=parseDataBRjs(q.pagamento);
    return dp && dp.getTime()>=dtLog.getTime();
  });
}
function cobStatusTitulo(reg,ent=null){
  const logs=cobLogsTitulo(reg,ent);
  const last=logs.length?logs[logs.length-1]:null;
  const pago=last?pagamentoAposCobranca(reg,last):false;
  const dias=last?daysSinceCob(last.server_time||last.data):9999;
  const qtd=logs.length;
  return {
    logs,last,pago,dias,qtd,
    ultima:last?(last.server_time||last.data||''):'',
    ultima_fmt:last?fmtCobDate(last.server_time||last.data):'',
    bloqueado: Boolean(last && !pago && dias<3),
    deve_voltar: Boolean(last && !pago && dias>=3),
    proxima_tentativa: qtd+1
  };
}
function cobrancaTemplateTerceiraAtual(){
  return String(CONFIG_META?.cobranca_msg_template_terceira || `Olá, {primeiro_nome}. Tudo bem?
Aqui é da Lojas MDL - Móveis do Lar.

Já tentamos contato sobre a parcela vencida em {vencimento}, no valor de {valor}, referente ao título {titulo}/{parcela}.

Para evitar novos encargos e restrições, pedimos que regularize o pagamento o quanto antes.
Caso já tenha pago, por gentileza desconsidere esta mensagem.`);
}

function montarMensagemCobranca(reg){
  const st=reg?._cob_status||cobStatusTitulo(reg, phoneContext?.entRef||null);
  const tentativa=Number(st?.proxima_tentativa||1);
  let tpl=(tentativa>=3)?cobrancaTemplateTerceiraAtual():cobrancaTemplateAtual();
  const dados={
    primeiro_nome: primeiroNomeClienteJs(reg.cliente||reg.nome||''),
    cliente: String(reg.cliente||reg.nome||''),
    vencimento: String(reg.vencimento||''),
    valor: valorBR(reg.pendente||0),
    titulo: String(reg.titulo||''),
    parcela: String(reg.parcela||''),
    filial: String(reg.filial||''),
    vendedor: String(reg.vendedor||''),
    dias: String(reg.dias||''),
    qtd_cobrancas: String(st?.qtd||0),
    ultima_cobranca: String(st?.ultima_fmt||''),
    tentativa: String(tentativa)
  };
  Object.entries(dados).forEach(([k,v])=>{
    tpl=tpl.replaceAll(`{${k}}`, v);
  });
  return tpl;
}
function exemploMensagemCobranca(){
  return montarMensagemCobranca({
    cliente:'MARIA APARECIDA DA SILVA',
    vencimento:'10/05/2026',
    pendente:199.90,
    titulo:'123456',
    parcela:'03',
    filial:'F1',
    vendedor:'VENDEDOR EXEMPLO',
    dias:25
  });
}
function atualizarPreviewCobranca(){
  const tpl=document.getElementById('cobMsgTemplate')?.value;
  const tpl3=document.getElementById('cobMsgTemplate3')?.value;
  const oldTpl=CONFIG_META.cobranca_msg_template;
  const oldTpl3=CONFIG_META.cobranca_msg_template_terceira;
  CONFIG_META.cobranca_msg_template=tpl || DEFAULT_COBRANCA_TEMPLATE;
  CONFIG_META.cobranca_msg_template_terceira=tpl3 || cobrancaTemplateTerceiraAtual();
  const el=document.getElementById('cobMsgPreview');
  if(el) el.textContent=exemploMensagemCobranca();
  const el3=document.getElementById('cobMsgPreview3');
  if(el3){
    const exemplo={cliente:'MARIA APARECIDA DA SILVA',vencimento:'10/05/2026',pendente:199.90,titulo:'123456',parcela:'03',filial:'F1',vendedor:'VENDEDOR EXEMPLO',dias:25,_cob_status:{qtd:2,proxima_tentativa:3,ultima_fmt:'20/05/2026 10:30'}};
    el3.textContent=montarMensagemCobranca(exemplo);
  }
  CONFIG_META.cobranca_msg_template=oldTpl;
  CONFIG_META.cobranca_msg_template_terceira=oldTpl3;
}
async function salvarMensagemCobrancaGlobal(){
  const msgEl=document.getElementById('cobMsgSaveStatus');
  const tpl=String(document.getElementById('cobMsgTemplate')?.value||'').trim();
  const tpl3=String(document.getElementById('cobMsgTemplate3')?.value||'').trim();
  if(!tpl){
    if(msgEl) msgEl.textContent='⚠️ A mensagem não pode ficar vazia.';
    return;
  }
  CONFIG_META.cobranca_msg_template=tpl;
  if(tpl3) CONFIG_META.cobranca_msg_template_terceira=tpl3;
  try{
    const payload={global:CONFIG_META,individual:CONFIG_META_IND};
    const resp=await fetch(API_CFG,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await resp.json();
    if(j.ok){
      await carregarConfigOnline();
      if(msgEl) msgEl.textContent='✅ Mensagem global de cobrança salva online.';
      toast('Mensagem de cobrança atualizada.','success');
      renderLogsTab();
    }else{
      if(msgEl) msgEl.textContent='⚠️ Não consegui salvar online.';
    }
  }catch(e){
    console.log('Erro ao salvar mensagem de cobrança',e);
    if(msgEl) msgEl.textContent='⚠️ Falha ao salvar online.';
  }
}
function restaurarMensagemCobrancaPadrao(){
  const t=document.getElementById('cobMsgTemplate');
  if(t) t.value=DEFAULT_COBRANCA_TEMPLATE;
  const t3=document.getElementById('cobMsgTemplate3'); if(t3) t3.value=cobrancaTemplateTerceiraAtual();
  atualizarPreviewCobranca();
}

function renderCobrancaConfigPanel(){
  const tpl=esc(cobrancaTemplateAtual());
  const tpl3=esc(cobrancaTemplateTerceiraAtual());
  return `<div class="glass panel" style="margin-bottom:14px">
    <div class="section-head" style="margin:0 0 10px">
      <div>
        <h2 style="margin:0">💬 Mensagens de cobrança</h2>
        <div class="hint">Configuração global usada ao abrir WhatsApp. O sistema usa a mensagem padrão na 1ª e 2ª cobrança. A partir da 3ª, usa a Terceira Mensagem.</div>
      </div>
      <button class="btn primary" onclick="salvarMensagemCobrancaGlobal()">Salvar global</button>
    </div>
    <div class="cobranca-config-grid">
      <div>
        <div class="input-card">
          <label>Mensagem padrão de cobrança</label>
          <textarea id="cobMsgTemplate" class="cobranca-template" oninput="atualizarPreviewCobranca()">${tpl}</textarea>
        </div>
        <div class="input-card" style="margin-top:12px">
          <label>Terceira Mensagem de Cobrança</label>
          <textarea id="cobMsgTemplate3" class="cobranca-template" oninput="atualizarPreviewCobranca()">${tpl3}</textarea>
        </div>
        <div class="placeholder-list">
          <code>{primeiro_nome}</code><code>{cliente}</code>
          <code>{vencimento}</code><code>{valor}</code>
          <code>{titulo}</code><code>{parcela}</code>
          <code>{filial}</code><code>{vendedor}</code>
          <code>{qtd_cobrancas}</code><code>{ultima_cobranca}</code><code>{tentativa}</code>
        </div>
        <div style="display:flex;gap:10px;margin-top:10px;align-items:center;flex-wrap:wrap">
          <button class="btn primary" onclick="salvarMensagemCobrancaGlobal()">Salvar global</button>
          <button class="btn soft" onclick="restaurarMensagemCobrancaPadrao()">Restaurar padrão</button>
          <span id="cobMsgSaveStatus" class="hint"></span>
        </div>
      </div>
      <div>
        <div class="input-card">
          <label>Prévia mensagem padrão</label>
          <div id="cobMsgPreview" class="preview-whats">${esc(exemploMensagemCobranca())}</div>
        </div>
        <div class="input-card" style="margin-top:12px">
          <label>Prévia terceira mensagem</label>
          <div id="cobMsgPreview3" class="preview-whats">${esc((()=>{const old=CONFIG_META.cobranca_msg_template_terceira; const ex={cliente:'MARIA APARECIDA DA SILVA',vencimento:'10/05/2026',pendente:199.90,titulo:'123456',parcela:'03',filial:'F1',vendedor:'VENDEDOR EXEMPLO',dias:25,_cob_status:{qtd:2,proxima_tentativa:3,ultima_fmt:'20/05/2026 10:30'}}; return montarMensagemCobranca(ex);})())}</div>
        </div>
      </div>
    </div>
  </div>`;
}


function normalizarListaTelefones(contatos){let base=[]; if(Array.isArray(contatos)) base=contatos; else if(typeof contatos==='string') base=contatos.split(/[;,/|]+/); const out=[]; const seen=new Set(); base.forEach(item=>{const num=String(item||'').replace(/\D/g,''); if(num.length>=10){const finalNum=num.startsWith('55')?num:'55'+num; if(!seen.has(finalNum)){seen.add(finalNum); out.push(finalNum);}}}); return out}
function matchCob(r,ent=null){return cobLogsTitulo(r,ent).length>0}
function renderCobrancasEnt(ent){
  const src=getClientesEnt(ent);
  const cobradosHoje=getCobradosHoje(ent);
  const allHoje=[...(src.grave||[]),...(src.alerta||[]),...(src.atencao||[])].filter(r=>r.novo);

  const srcAll=[...(src.grave||[]),...(src.alerta||[]),...(src.atencao||[])];

  function decorateRow(r){
    const st=cobStatusTitulo(r,ent);
    return {...r,_cob_status:st};
  }

  function shouldShowInGeral(r){
    const st=r._cob_status||cobStatusTitulo(r,ent);
    if(!st.last) return true;
    if(st.pago) return false;
    return st.deve_voltar; // volta somente depois de 3 dias sem pagamento
  }

  const renderRows=(arr,showFaixa)=>!arr.length?'<div class="empty">Nada nesta aba.</div>':arr.slice(0,150).map(raw=>{
    const r=raw._cob_status?raw:decorateRow(raw);
    const st=r._cob_status||{};
    const cobrado=Boolean(st.last);
    const bloqueado=Boolean(st.bloqueado);
    const retry=Boolean(st.deve_voltar);
    const tentativa=Number(st.proxima_tentativa||1);
    const statusChip = retry
      ? `<span class="cob-retry-chip">🔁 Cobrar novamente · ${tentativa}ª tentativa</span>`
      : (cobrado ? `<span class="cob-history-chip">🕒 Cobrado ${st.qtd}x</span>` : '');
    const info = cobrado
      ? `<div class="cob-info-box ${bloqueado?'waiting':''}">${retry?'⚠️ Cliente já foi cobrado e não pagou em 3 dias.':'✅ Cliente cobrado recentemente.'} Última cobrança: <strong>${esc(st.ultima_fmt||'')}</strong> · Total de cobranças: <strong>${st.qtd||0}</strong>${tentativa>=3?' · A próxima mensagem será a <strong>Terceira Mensagem de Cobrança</strong>.':''}</div>`
      : '';
    const btn = bloqueado
      ? `<button class="btn soft" title="Só volta para cobrança após 3 dias sem pagamento" disabled>⏳ Aguardando 3 dias</button>`
      : `<button class="btn wa" onclick='abrirWhats(${JSON.stringify(r)}, ${JSON.stringify({type:ent.type,filial:ent.filial,nome:ent.nome,login:ent.login||''})})'>💬 ${retry?'Cobrar novamente':'WhatsApp'}</button>`;
    return `<div class="row-item ${retry?'retry-due':''}"><div class="row-top"><div><div class="name">${esc(r.cliente||r.nome||'')} ${r.novo?'<span class="mini-chip" style="margin-left:6px;background:#eef7ff;color:#1e3a8a;border-color:#93c5fd">Novo hoje</span>':''} ${statusChip}</div>${info}<div class="small muted">✍️ Avalista: ${esc((r.avalista && String(r.avalista).toLowerCase()!=='nan')?r.avalista:'Sem Aval')}</div>${(r.avalista && String(r.avalista).toLowerCase()!=='nan')?'<div class="small avalista-alert">⚠️ Atenção, lembre de cobrar o AVALISTA</div>':''}<div class="small muted">🔒 Restrição crédito: ${/sem restr/i.test(String(r.restricao||''))?`<span class="restr-ok">${esc(r.restricao||'Sem Restrição')}</span>`:esc(r.restricao||'Sem informação')}</div><div class="small muted">👤 ${esc(r.vendedor||'')}</div><div class="small muted">☎️ ${esc(Array.isArray(r.telefones)?r.telefones.join(', '):(r.contato||''))}</div></div><div><strong>${esc(r.titulo||'')}</strong><div class="small muted">Título</div></div><div><strong>${r.dias||0}d</strong><div class="small muted">Dias</div></div><div><strong>${esc(r.vencimento||'')}</strong><div class="small muted">Vencimento</div></div><div><strong>${R(r.pendente||0)}</strong><div class="small muted">Pendente</div></div><div>${showFaixa?`<div class="small muted">${esc(r.faixa_label||'')}</div>`:''}${btn}</div></div></div>`;
  }).join('');

  const faixas=['grave','alerta','atencao'];
  const tabs=`<div class="tabs" style="justify-content:flex-start;margin:0 0 12px"><button class="tab active" data-cobtab="geral" onclick="switchCobTab(this,'geral')">Para cobrar</button><button class="tab" data-cobtab="novos" onclick="switchCobTab(this,'novos')">Novos Hoje</button><button class="tab" data-cobtab="cobrados" onclick="switchCobTab(this,'cobrados')">Cobrados Hoje</button><button class="tab" data-cobtab="aguardando" onclick="switchCobTab(this,'aguardando')">Aguardando 3 dias</button></div>`;
  let geral='';
  let aguardando=[];
  faixas.forEach(fx=>{
    const arr=(src[fx]||[]).map(r=>decorateRow({...r,faixa_label:fx}));
    aguardando.push(...arr.filter(r=>r._cob_status?.bloqueado));
    const vis=arr.filter(shouldShowInGeral);
    const label=fx==='grave'?'Grave':fx==='alerta'?'Alerta':'Atenção';
    geral+=`<div class="faixa-block"><div class="faixa-title ${fx}">${label}<span>${vis.length} títulos · ${R(vis.reduce((a,b)=>a+Number(b.pendente||0),0))}</span></div><div class="tableish">${renderRows(vis,false)}</div></div>`;
  });

  const cobradosRows=(cobradosHoje||[]).map(x=>{
    const m=srcAll.find(r=>cobrancaRowKey(r)===cobrancaRowKey(x))||{};
    return decorateRow({cliente:x.cliente,titulo:x.titulo,parcela:x.parcela,vencimento:x.vencimento,pendente:x.pendente,vendedor:x.usuario||m.vendedor||'',dias:m.dias||'',telefones:Array.isArray(m.telefones)&&m.telefones.length?m.telefones:[x.telefone],contato:m.contato||x.telefone,avalista:m.avalista||'',restricao:m.restricao||'',faixa_label:m.faixa||'',novo:false,pagamento:m.pagamento||'',lancamento:m.lancamento||''});
  });

  return `${tabs}<div class="cob-pane" data-cobpane="geral">${geral}</div><div class="cob-pane hidden" data-cobpane="novos">${renderRows(allHoje.map(r=>decorateRow({...r,faixa_label:r.faixa||''})).filter(shouldShowInGeral),true)}</div><div class="cob-pane hidden" data-cobpane="cobrados">${renderRows(cobradosRows,true)}</div><div class="cob-pane hidden" data-cobpane="aguardando">${renderRows(aguardando,true)}</div>`;
}
function switchCobTab(btn,name){const box=btn.closest('.acc-body'); box.querySelectorAll('[data-cobtab]').forEach(b=>b.classList.toggle('active',b===btn)); box.querySelectorAll('[data-cobpane]').forEach(p=>p.classList.toggle('hidden',p.dataset.cobpane!==name));}
function abrirWhats(reg,entRef){const nums=normalizarListaTelefones((reg.telefones&&reg.telefones.length)?reg.telefones:reg.contato); if(!nums.length){toast('Cliente sem telefone válido.'); return} reg._cob_status=cobStatusTitulo(reg,entRef); phoneContext={reg,entRef}; if(nums.length===1){enviarWhats(nums[0]); return} const phoneList=document.getElementById('phoneList'); phoneList.innerHTML=nums.map(n=>`<button class="btn soft" style="width:100%" onclick="enviarWhats('${n}')">${n}</button>`).join(''); document.getElementById('phoneModal').classList.add('show')}
function closePhoneModal(){document.getElementById('phoneModal').classList.remove('show'); phoneContext=null}
function enviarWhats(numero){if(!phoneContext) return; const {reg,entRef}=phoneContext; const msg=montarMensagemCobranca(reg); window.open(`https://wa.me/${numero}?text=${encodeURIComponent(msg)}`,'_blank'); registrarCobrancaOnline(reg,entRef,numero); closePhoneModal()}
async function registrarCobrancaOnline(r,entRef,numero){
  // Para crediarista usa o login como usuario para que getCobradosHoje() funcione corretamente
  const usuarioLog = (entRef.type==='crediarista'||entRef.is_crediarista)
    ? (String(entRef.login||entRef.nome||usuarioAtual?.login||'').toLowerCase() || usuarioAtual?.login || 'master')
    : (usuarioAtual?.nome||usuarioAtual?.login||'master');
  const payload={
    cliente:r.cliente||r.nome||'',titulo:r.titulo||'',parcela:r.parcela||'',
    vencimento:r.vencimento||'',pendente:Number(r.pendente||0),telefone:numero,
    usuario:usuarioLog,filial:entRef.filial||'',
    destino_tipo:entRef.type||'',destino_nome:entRef.nome||'',acao:'whatsapp',tentativa:Number(r._cob_status?.proxima_tentativa||1),qtd_cobrancas_antes:Number(r._cob_status?.qtd||0),ultima_cobranca_anterior:String(r._cob_status?.ultima_fmt||'')
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
async function carregarCobrancasOnline(){try{const r=await fetchComTimeout(API_COB+'?_='+Date.now(),{},3000); const txt=await r.text(); let j={ok:false}; try{j=JSON.parse(txt);}catch(e){} COB_LOGS=(j.ok&&Array.isArray(j.data))?j.data:[]; RECEBIMENTOS_CONCILIADOS=getQuitadosConciliados(); console.log('🔗 Quitados conciliados:', RECEBIMENTOS_CONCILIADOS); if(!j.ok && txt) console.log('cobrancas_api retorno:', txt);}catch(e){console.log(e); COB_LOGS=[]}}

async function removerCobranca(id,cliente='',titulo='',parcela=''){if(!confirm('Remover esta cobrança do histórico?')) return; try{const r=await fetch(API_COB,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',id,cliente,titulo,parcela})}); const txt=await r.text(); let j={ok:false}; try{j=JSON.parse(txt);}catch(e){} if(j.ok){toast('Cobrança removida.','success'); await carregarCobrancasOnline(); renderLogsTab(); renderList(); if(currentDetailRef) openEntity(currentDetailRef);}else{console.log('Falha remover cobrança:', txt); toast('Não consegui remover.')}}catch(e){console.log(e); toast('Falha ao remover cobrança.')}}
function toggleAcc(el){el.parentElement.classList.toggle('open')}
async function carregarConfigOnline(){try{const r=await fetchComTimeout(API_CFG+'?_='+Date.now(),{},2500); const j=await r.json(); if(j.ok && j.data){CONFIG_META={...CONFIG_META,...(j.data.global||{})}; CREDIARISTAS_CONFIG=getCrediaristasConfig(); const ind=(j.data.individual && typeof j.data.individual==='object' && !Array.isArray(j.data.individual))?j.data.individual:{}; CONFIG_META_IND=ind;}}catch(e){console.log('Falha ao carregar config meta',e);}}

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

function renderCrediaristasConfigPanel(){
  const rows=getCrediaristasConfig();
  return `<div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">🧾 Crediaristas configuráveis</h2><div class="hint">Fluxo correto: primeiro crie o login em Senhas. Depois, aqui, vincule esse login à filial/base e ao %. Quando trocar a pessoa, crie novo login, exemplo CREDIARISTAF2_02, e remova o antigo daqui. O histórico antigo permanece salvo. O % é só da carteira que o crediarista enxerga; não altera o rateio 60% filial / 40% vendedores.</div></div></div>
  <div id="credConfigRows">${rows.map(r=>`<div class="glass" style="padding:10px;margin-bottom:8px;border-radius:14px"><div class="form-grid bonus">
    <div class="input-card"><label>Login do usuário</label><input class="cred-login" value="${esc(r.login||'')}" placeholder="crediaristaf2_01"></div>
    <div class="input-card"><label>Nome exibido</label><input class="cred-nome" value="${esc(r.nome||'')}" placeholder="Maria - crediarista F2"></div>
    <div class="input-card"><label>Filial/base</label><select class="cred-filial">${ORDEM.map(f=>`<option value="${f}" ${String(r.filial||'').toUpperCase()===f?'selected':''}>${f}</option>`).join('')}</select></div>
    <div class="input-card"><label>% da base</label><input class="cred-pct" type="number" step="0.01" value="${Number(r.pct||100)}"></div>
  </div><button type="button" class="btn soft" onclick="this.closest('.glass').remove()">🗑️ Remover</button></div>`).join('')}</div>
  <button type="button" class="btn soft" onclick="addCrediaristaConfigRow()">➕ Adicionar crediarista</button>`;
}
function addCrediaristaConfigRow(){
  const box=document.getElementById('credConfigRows'); if(!box) return;
  box.insertAdjacentHTML('beforeend', `<div class="glass" style="padding:10px;margin-bottom:8px;border-radius:14px"><div class="form-grid bonus">
    <div class="input-card"><label>Login do usuário</label><input class="cred-login" placeholder="crediaristaf2_01"></div>
    <div class="input-card"><label>Nome exibido</label><input class="cred-nome" placeholder="Nome da crediarista"></div>
    <div class="input-card"><label>Filial/base</label><select class="cred-filial">${ORDEM.map(f=>`<option value="${f}">${f}</option>`).join('')}</select></div>
    <div class="input-card"><label>% da base</label><input class="cred-pct" type="number" step="0.01" value="100"></div>
  </div><button type="button" class="btn soft" onclick="this.closest('.glass').remove()">🗑️ Remover</button></div>`);
}
function readCrediaristasConfigFromUI(){
  const box=document.getElementById('credConfigRows'); if(!box) return getCrediaristasConfig();
  return Array.from(box.querySelectorAll(':scope > .glass')).map(row=>{
    const login=String(row.querySelector('.cred-login')?.value||'').trim().toLowerCase();
    const filial=String(row.querySelector('.cred-filial')?.value||'').toUpperCase();
    const nome=String(row.querySelector('.cred-nome')?.value||'').trim()||`Crediarista ${filial}`;
    const pct=Math.max(0,Math.min(100,Number(row.querySelector('.cred-pct')?.value||100)));
    return {login,nome,filial,pct};
  }).filter(r=>r.login&&r.filial&&r.pct>0);
}

function renderMetasTab(){const cards=[...flattenVendedores(),...flattenFiliais()]; const currentMode=window._metaMode||'global'; const currentTarget=window._metaSelectedTarget||''; metaSection.innerHTML=`<div class="section-head"><div><h2>🎯 Configuração de metas e bônus</h2><div class="hint">Altere globalmente ou por vendedor/filial. Ao salvar, já fica online.</div></div></div><div class="meta-layout"><div class="glass panel"><div class="tabs" style="justify-content:flex-start;margin-top:0"><button id="btnModeGlobal" class="tab" onclick="setMetaMode('global')">🌐 Padrão global</button><button id="btnModeInd" class="tab" onclick="setMetaMode('individual')">👤 Por vendedor/filial</button></div><div id="metaSelectWrap" class="hidden" style="margin:8px 0 14px"><div class="input-card"><label>Selecionar alvo</label><select id="metaTarget" onchange="loadMetaSelected()"><option value="">Selecione...</option>${optionTargets()}</select></div></div><div class="section-head" style="margin-top:10px"><div><h2 style="font-size:18px">% de meta por faixa</h2></div></div><div class="form-grid"><div class="input-card"><label>Grave</label><input id="cfg_grave_pct" type="number" step="0.01"></div><div class="input-card"><label>Alerta</label><input id="cfg_alerta_pct" type="number" step="0.01"></div><div class="input-card"><label>Atenção</label><input id="cfg_atencao_pct" type="number" step="0.01"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">Pesos da meta geral</h2></div></div><div class="form-grid"><div class="input-card"><label>Peso Grave</label><input id="cfg_peso_grave" type="number" step="0.01"></div><div class="input-card"><label>Peso Alerta</label><input id="cfg_peso_alerta" type="number" step="0.01"></div><div class="input-card"><label>Peso Atenção</label><input id="cfg_peso_atencao" type="number" step="0.01"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">Bônus / mensagem da faixa <span class="note">· Não acumulativo</span></h2></div></div><div class="form-grid bonus"><div class="input-card"><label>50%</label><input id="cfg_bonus_50" placeholder="Ex: Parabéns, você ganhou R$ 100,00"></div><div class="input-card"><label>75%</label><input id="cfg_bonus_75"></div><div class="input-card"><label>85%</label><input id="cfg_bonus_85"></div><div class="input-card"><label>100%</label><input id="cfg_bonus_100"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">💲 Meta mínima Vendas e Serviços</h2><div class="hint">Configuração inicial para comissão de vendedor e gerente/filial.</div></div></div><div class="form-grid bonus"><div class="input-card"><label>Vendedor · mínimo vendas (%)</label><input id="cfg_vendas_min_pct" type="number" step="0.01" placeholder="80"></div><div class="input-card"><label>Vendedor · mínimo serviços (%)</label><input id="cfg_servicos_min_pct" type="number" step="0.01" placeholder="80"></div><div class="input-card"><label>Gerente/Filial · mínimo vendas (%)</label><input id="cfg_gerente_vendas_min_pct" type="number" step="0.01" placeholder="90"></div><div class="input-card"><label>Gerente/Filial · mínimo serviços (%)</label><input id="cfg_gerente_servicos_min_pct" type="number" step="0.01" placeholder="90"></div></div><div class="section-head" style="margin-top:14px"><div><h2 style="font-size:18px">🤝 Rateio cobrança global</h2><div class="hint">Percentual do total único da cobrança geral distribuído para os usuários do tipo cobrança global (ex.: Cobrança10).</div></div></div><div class="form-grid bonus"><div class="input-card"><label>Usuários de cobrança global (%)</label><input id="cfg_cobranca_global_rateio_pct" type="number" step="0.01" placeholder="20"></div></div>${renderCrediaristasConfigPanel()}<div id="commissionPanel"></div><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:16px"><button class="btn primary" onclick="salvarMeta()">💾 Salvar configuração</button><button class="btn ghost" onclick="removerMetaIndividual()">🗑️ Remover individual</button></div><div id="metaSaveMsg" class="note" style="margin-top:10px"></div><div id="metaSavedList" class="note" style="margin-top:10px"></div></div></div>`; const sel=document.getElementById('metaTarget'); if(sel && currentTarget) sel.value=currentTarget; setMetaMode(currentMode); renderSavedMetaList();}
function setMetaMode(mode){window._metaMode=mode; const bg=document.getElementById('btnModeGlobal'); const bi=document.getElementById('btnModeInd'); if(bg) bg.classList.toggle('active',mode==='global'); if(bi) bi.classList.toggle('active',mode==='individual'); const wrap=document.getElementById('metaSelectWrap'); if(wrap) wrap.classList.toggle('hidden',mode!=='individual'); if(mode==='global'){fillMetaForm('global')} else {const raw=(document.getElementById('metaTarget')?.value)||window._metaSelectedTarget||''; if(raw){window._metaSelectedTarget=raw; fillMetaForm('individual',raw)} else {fillMetaForm('global')}}}
function loadMetaSelected(){const val=document.getElementById('metaTarget').value; window._metaSelectedTarget=val; if(!val){fillMetaForm('global'); return;} fillMetaForm('individual',val)}
function collectMetaForm(){const out={}; ['grave_pct','alerta_pct','atencao_pct','peso_grave','peso_alerta','peso_atencao','vendas_min_pct','servicos_min_pct','gerente_vendas_min_pct','gerente_servicos_min_pct','cobranca_global_rateio_pct'].forEach(k=>out[k]=Number(document.getElementById('cfg_'+k).value||0)); ['bonus_50','bonus_75','bonus_85','bonus_100'].forEach(k=>out[k]=document.getElementById('cfg_'+k).value||''); return {...out,crediaristas_config:readCrediaristasConfigFromUI(),...readCommissionPanel()}}
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
function renderLogsTab(){const cfgPanel=renderCobrancaConfigPanel(); const filOpts=['<option value="">Todas as filiais</option>',...ORDEM.map(f=>`<option value="${f}">${f}</option>`)].join(''); const vendOpts=['<option value="">Todos os usuários</option>',...Array.from(new Set(COB_LOGS.map(x=>x.usuario).filter(Boolean))).sort().map(v=>`<option value="${esc(v)}">${esc(v)}</option>`)].join(''); logSection.innerHTML=cfgPanel+`<div class="section-head"><div><h2>🧾 Histórico de cobranças</h2><div class="hint">Filtre por data, usuário ou filial. Também é possível remover lançamentos indevidos.</div></div></div><div class="glass panel"><div class="search-row"><div class="input-card"><label>Buscar cliente/título</label><input id="logQ" placeholder="Nome, título, parcela"></div><div class="input-card"><label>Data inicial</label><input id="logDe" type="date"></div><div class="input-card"><label>Data final</label><input id="logAte" type="date"></div><div class="input-card"><label>Filial</label><select id="logFil">${filOpts}</select></div></div><div class="search-row" style="margin-top:10px"><div class="input-card"><label>Usuário</label><select id="logVend">${vendOpts}</select></div><div style="display:flex;align-items:end;gap:10px"><button class="btn primary" onclick="applyLogFilter()">Filtrar</button><button class="btn soft" onclick="clearLogFilter()">Limpar</button></div></div><div id="logsList" class="logs-list"></div></div>`; applyLogFilter()}
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
async function carregarMsgsOnline(){try{const r=await fetchComTimeout(API_MSG+'?_='+Date.now(),{},3000); const txt=await r.text(); let j={ok:false}; try{j=JSON.parse(txt);}catch(e){} MSGS=(j.ok&&Array.isArray(j.data))?j.data:[]; if(!j.ok && txt) console.log('mensagens_api retorno:', txt);}catch(e){console.log(e); MSGS=[]} refreshBell()}

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
  return `<div class="campaign-banner highlight-pulse" style="background:linear-gradient(180deg,#f7f1df,#f2ead7);border:1px solid #e4d8b2;color:#1f2937"><div class="section-head" style="margin:0 0 8px"><div><h2 style="margin:0;font-size:22px">📣 Campanha ativa</h2><div class="hint">Mensagem destacada do Master</div></div><button class="btn soft" onclick="openBell()">Ver detalhes</button></div>${arr.map(m=>renderMsgCard(m,false,false,true)).join('')}</div>`;
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
function renderSenhaCard(u, isDirector=false){
  const key=isDirector?'diretorcomercial':u.login;
  const senhaAtual=String((isDirector ? (AUTH_STATE?.director?.password||SENHA_DIRETOR) : (u.password||u.senha||''))||'');
  const senhaIni=String((isDirector ? (AUTH_STATE?.director?.initial_password||SENHA_DIRETOR) : (u.initial_password||u.senha_inicial||''))||'');
  const pend=(AUTH_STATE?.password_reset_requests||[]).filter(r=>String(r.login||'').toLowerCase()===String(key).toLowerCase() && String(r.status||'pendente')==='pendente').length;
  return `<div class="glass card" style="cursor:default">
    <div class="title" style="min-height:auto">${esc(isDirector?'Diretor Comercial':u.nome)} ${!isDirector?`(${u.filial||''})`:''}</div>
    <div class="legend-inline">
      <span><i class="dot" style="background:${u.must_change_password?'#f59e0b':'#22c55e'}"></i>${u.must_change_password?'Precisa trocar senha':'Senha ativa'}</span>
      ${pend?`<span><i class="dot" style="background:#ef4444"></i>${pend} solicitação(ões)</span>`:''}
    </div>
    <div class="note" style="margin-top:10px;background:rgba(15,23,42,.04);border:1px solid rgba(15,23,42,.08);border-radius:14px;padding:10px 12px">
      <div><b>Login:</b> <code>${esc(key)}</code></div>
      <div><b>Senha definida agora:</b> <code style="font-size:14px">${esc(senhaAtual||'—')}</code></div>
      ${senhaIni && senhaIni!==senhaAtual?`<div class="small muted">Senha inicial: <code>${esc(senhaIni)}</code></div>`:''}
    </div>
    <div class="form-grid bonus" style="grid-template-columns:1.1fr .9fr;margin-top:12px">
      <div class="input-card"><label>Nova senha para ${esc(key)}</label><input id="pwd_${key}" placeholder="Digite a nova senha"></div>
      <div class="input-card"><label>Ações</label><div style="display:flex;gap:8px;flex-wrap:wrap"><button class="btn primary" type="button" onclick="adminSalvarSenha('${key}')">💾 Salvar senha</button><button class="btn soft" type="button" onclick="adminMarcarTroca('${key}')">🔁 Exigir troca</button></div></div>
    </div>
    ${pend?`<div class="note" style="margin-top:10px">Solicitação pendente de recuperação. <button class="btn soft" style="margin-left:8px" onclick="adminResolverReset('${key}')">Resolver solicitação</button></div>`:''}
    <div id="pwd_msg_${key}" class="note" style="margin-top:8px"></div>
  </div>`
}

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

function mesAtualComissao(){const d=new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`}
function _histComMeses(){return Object.keys(HIST_COMISSAO?.months||{}).sort().reverse()}
function _comEntKey(ent){return `${ent.type||'ent'}::${ent.filial||''}::${ent.login||ent.nome||''}`}
function _recebResumo(ent){const r=getRecebimentos(ent); const sum=(fx)=>(r[fx]||[]).reduce((a,b)=>a+Number(b.pago||0),0); return {grave:sum('grave'),alerta:sum('alerta'),atencao:sum('atencao'),total:sum('grave')+sum('alerta')+sum('atencao'),qtd:(r.grave||[]).length+(r.alerta||[]).length+(r.atencao||[]).length}}

function snapKV(label,value,color=''){
  return `<div class="snap-kv"><div>${esc(label)}</div><strong style="${color?`color:${color}`:''}">${value}</strong></div>`;
}
function snapMetric(title,value,sub='',color=''){
  return `<div class="snap-card"><div class="snap-title">${esc(title)}</div><div class="snap-value" style="${color?`color:${color}`:''}">${value}</div>${sub?`<div class="snap-sub">${sub}</div>`:''}</div>`;
}
function snapMiniBox(title, perc, alvo, rec, color){
  return `<div class="snap-mini"><div class="snap-title">${title}</div><div class="snap-percent" style="color:${color}">${pct(perc||0)}</div><div class="snap-sub">Alvo: ${R(alvo||0)}</div><div class="snap-sub">Recebido: ${R(rec||0)}</div></div>`;
}
function snapSalesRows(ent, key, label){
  let rows=getSalesRows(ent,key);
  if(String(key||'').includes('servico') && servicosEntidadeTotal(ent)>0 && rows.length) rows=[rows[0]];
  if(!rows.length) return '';
  return `<div class="snap-box"><h3>${label}</h3>${rows.slice(0,1).map(r=>{
    const srv=serviceOfficialOverride(ent,key,r);
    const ating=srv ? srv.atingidoTotal : salesCell(r,['Atingido Total']);
    const atingPeriodo=srv ? srv.atingidoPeriodo : salesCell(r,['Atingido Período']);
    const realizadoTotal=srv ? srv.realizado : esc(salesCell(r,['Realizado (R$) Total','Realizado(R$) Total']));
    const realizadoPeriodo=srv ? srv.realizado : esc(salesCell(r,['Realizado (R$) Período','Realizado(R$) Período']));
    const proj=salesCell(r,['Projetado (R$)','Projetado(R$)']);
    const title=srv ? `${salesTitleForRow(ent,r,key)} · relatório serviços` : salesTitleForRow(ent,r,key);
    return `<div class="snap-sales-title">${esc(title)}</div><div class="snap-grid4">
      ${snapKV('Meta total',esc(salesCell(r,['Meta (R$) Total','Meta(R$) Total'])))}
      ${snapKV('Realizado total',realizadoTotal,'#34d399')}
      ${snapKV('Atingido total',esc(ating),'#f59e0b')}
      ${snapKV('Meta período',esc(salesCell(r,['Meta (R$) Período','Meta(R$) Período'])))}
      ${snapKV('Realizado período',realizadoPeriodo,'#34d399')}
      ${snapKV('Atingido período',esc(atingPeriodo),'#f59e0b')}
      ${snapKV('Projetado',esc(proj),'#fb7185')}
      ${snapKV(ent.type==='filial'?'Filial':'Vendedor',esc(salesCell(r, ent.type==='filial'?['Filial']:['Vendedor_2','Vendedor'])))} 
    </div>`;
  }).join('')}</div>`;
}
function snapServices(ent){
  const rows=servicosEntidade(ent).filter(x=>Number(x.real_total||0)>0);
  const total=rows.reduce((a,b)=>a+Number(b.real_total||0),0);
  return `<div class="snap-box"><h3>🛠️ Serviços por tipo</h3><div class="snap-sub">Relatório real de serviços · total oficial ${R(total)}</div><div class="snap-grid3">${rows.slice(0,6).map(r=>snapKV(String(r.servico||'Serviço').slice(0,36),R(r.real_total||0),'#60a5fa')).join('') || '<div class="snap-sub">Sem serviços localizados.</div>'}</div></div>`;
}
function snapCommission(ent){
  if(!(ent.type==='vendedor'||ent.type==='filial')) return '';
  let c={}; try{c=calcCommissionSummary(ent)||{}}catch(e){return ''}
  const totalLiberado = Number(c.totalPrevisto||0)>0;
  const totalExibido = c.totalPrevisto || 0;
  const cell=(t,v,color='')=>snapKV(t, v, color);
  return `<div class="snap-box"><h3>💵 Comissionamento previsto</h3><div class="snap-grid3">
    ${cell('Faixa aplicada',esc(c.faixaTxt||'-'))}
    ${cell('% comissão mercantil',`${String(Number(c.comPerc||0).toFixed(2)).replace('.',',')}%`)}
    ${cell('% serviços',`${String(Number(c.servPct||0).toFixed(2)).replace('.',',')}%`)}
    ${cell('Comissão vendas',R(c.vendasComissao||0),'#34d399')}
    ${cell('Comissão serviços',R(c.servicosComissao||0),'#34d399')}
    ${cell('Comissão caminhão',R(c.caminhaoComissao||0),'#34d399')}
    ${cell('Bônus por meta',R(c.bonusMeta||0),'#fbbf24')}
    ${cell('Rentab 48%',R(c.rent48||0),'#fbbf24')}
    ${cell('Rentab 52,15%',R(c.rent52||0),'#fbbf24')}
    ${cell('Rentab 55,50%',R(c.rent55||0),'#fbbf24')}
    ${cell('Total previsto',R(totalExibido),'#fff')}
  </div><div class="snap-sub">Base mercantil bruta: ${R(c.vendaRealBruto||0)} · Caminhão abatido: ${R(c.camReal||0)} · Serviço: ${R(c.servReal||0)}.</div></div>`;
}
function snapshotEntityHTML(ent){
  try{
    if(ent && (ent.type==='crediarista'||ent.is_crediarista)){
      ent=findEntityBySnapshotRow({key:(typeof _comEntKey==='function'?_comEntKey(ent):`${ent.type||'ent'}::${ent.filial||''}::${ent.login||ent.nome||''}`),nome:ent.nome,filial:ent.filial}) || ent;
    }
    const meta=calcMeta(ent);
    const nome=ent.type==='filial'?filialLabel(ent.filial):esc(ent.nome||'');
    const sub=ent.type==='filial'?'Painel individual da filial':(ent.type==='crediarista'?'Painel de crediarista':'Painel individual do vendedor');
    const bonus=getBonus(meta.cfg,meta.geral);
    const salesBlocks = ent.type==='filial'
      ? [['venda_filial_meta','📈 Venda · Meta Filial'],['servico_filial_ouro_fob','🛠️ Serviço · Ouro / FOB'],['venda_filial_subgrupo_20k','🚚 Venda · Caminhão 20K']]
      : [['venda_filial_vendedor_meta','📈 Venda · Meta Vendedor'],['servico_filial_vendedor_ouro_fob','🛠️ Serviço · Ouro / FOB Vendedor'],['venda_vendedor_subgrupo_20k','🚚 Venda · Caminhão 20K']];
    const vendasHtml=(ent.type==='crediarista'||ent.is_crediarista)?'':salesBlocks.map(([k,l])=>snapSalesRows(ent,k,l)).join('');
    const bonusItems=[[50,meta.cfg.bonus_50||'-'],[75,meta.cfg.bonus_75||'-'],[85,meta.cfg.bonus_85||'-'],[100,meta.cfg.bonus_100||'-']];
    return `<div class="snap-sheet">
      <style>
      .snap-sheet{width:1180px;max-width:100%;margin:0 auto;background:#0d0f14;color:#f3f6ff;font-family:Inter,Arial,sans-serif;padding:22px;border-radius:22px}
      .snap-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:18px;border:1px solid rgba(255,255,255,.12);background:#161922;border-radius:18px;padding:16px 18px}
      .snap-head h1{font-size:28px;margin:0;color:#fff}.snap-head .snap-sub{margin-top:6px}
      .snap-two{display:grid;grid-template-columns:1.04fr .96fr;gap:18px;align-items:start}
      .snap-box,.snap-card,.snap-mini,.snap-kv{border:1px solid rgba(255,255,255,.12);background:#151821;border-radius:16px;padding:14px;box-shadow:0 8px 24px rgba(0,0,0,.22)}
      .snap-box{margin-bottom:16px}.snap-box h2,.snap-box h3{margin:0 0 12px 0;font-size:19px;color:#fff}
      .snap-topmeta{display:grid;grid-template-columns:210px 1fr;gap:18px;align-items:center}.snap-ring{display:flex;align-items:center;justify-content:center}
      .snap-grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}.snap-grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.snap-grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
      .snap-title{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:#8c96ab;font-weight:800}.snap-value{font-size:26px;font-weight:900;margin-top:6px}.snap-sub{color:#aeb7ca;font-size:13px;line-height:1.35}
      .snap-mini{text-align:center}.snap-percent{font-size:30px;font-weight:950;margin:8px 0}
      .snap-kv strong{display:block;font-size:18px;margin-top:6px;color:#fff}.snap-sales-title{font-weight:900;color:#fff;margin-bottom:10px}
      .snap-chart-bars{height:230px;display:flex;align-items:end;gap:36px;justify-content:center;padding:16px 10px}.snap-barwrap{text-align:center}.snap-bar{width:58px;border-radius:12px 12px 8px 8px;background:linear-gradient(180deg,rgba(255,255,255,.25),transparent),var(--c);box-shadow:0 0 22px color-mix(in srgb,var(--c),transparent 65%)}.snap-barlabel{font-size:12px;color:#c7d0e1;margin-top:8px}
      .snap-bonus{display:grid;gap:8px}.snap-bonus-item{display:flex;justify-content:space-between;gap:12px;border:1px solid rgba(255,255,255,.1);background:#10131a;border-radius:12px;padding:10px 12px;font-size:13px}.snap-bonus-item.active{outline:2px solid rgba(245,158,11,.45)}
      @media print{body{background:#0d0f14}.snap-sheet{width:1180px}}
      </style>
      <div class="snap-head"><div><h1>${nome}</h1><div class="snap-sub">${sub} · ${esc(ent.filial||'')} · ${mesAtualComissao()}</div></div><div class="snap-sub">🕒 ${esc(ULTIMA_ATUALIZACAO_DASHBOARD_BR||'')}</div></div>
      <div class="snap-two">
        <div>
          <div class="snap-box"><h2>🎯 Meta do mês · Não acumulativo</h2><div class="snap-topmeta"><div class="snap-ring">${renderPiggyBank(meta.geral)}</div><div><div class="snap-grid2">
            ${snapMetric('Pendente',R(ent.pendente||0),'','#ff5a6a')}
            ${snapMetric('Recebido',R(ent.pago||0),'','#34d399')}
            ${snapMetric('% da filial',pct(ent.perc_filial||100))}
            ${snapMetric('Configuração usada',`${Number(meta.cfg.grave_pct||0)}/${Number(meta.cfg.alerta_pct||0)}/${Number(meta.cfg.atencao_pct||0)}`)}
          </div><div style="height:12px"></div><div class="snap-sub">🔴 Grave alvo ${R(meta.grave.alvo)} · recebido ${R(meta.grave.rec)}<br>🟠 Alerta alvo ${R(meta.alerta.alvo)} · recebido ${R(meta.alerta.rec)}<br>🟡 Atenção alvo ${R(meta.atencao.alvo)} · recebido ${R(meta.atencao.rec)}</div></div></div><div style="height:14px"></div><div class="snap-grid4">
            ${snapMiniBox('Grave',meta.grave.perc,meta.grave.alvo,meta.grave.rec,'#ff5a6a')}
            ${snapMiniBox('Alerta',meta.alerta.perc,meta.alerta.alvo,meta.alerta.rec,'#fb923c')}
            ${snapMiniBox('Atenção',meta.atencao.perc,meta.atencao.alvo,meta.atencao.rec,'#facc15')}
            ${snapMiniBox('Meta geral',meta.geral,meta.grave.alvo+meta.alerta.alvo+meta.atencao.alvo,meta.grave.rec+meta.alerta.rec+meta.atencao.rec,'#60a5fa')}
          </div></div>
          <div class="snap-box"><h3>🌊 Gráfico Geral Contas a Receber</h3>${(()=>{const vals=[['Grave',meta.grave.pend,'#ff5a6a'],['Alerta',meta.alerta.pend,'#fb923c'],['Atenção',meta.atencao.pend,'#facc15'],['Recebido',Number(ent.pago||0),'#34d399']]; const max=Math.max(1,...vals.map(v=>v[1])); return `<div class="snap-chart-bars">${vals.map(v=>`<div class="snap-barwrap"><div class="snap-bar" style="--c:${v[2]};height:${Math.max(24,(v[1]/max)*190)}px"></div><div class="snap-barlabel">${v[0]}<br><strong>${R(v[1])}</strong></div></div>`).join('')}</div>`})()}</div>
          <div class="snap-box"><h3>🏆 Bônus e premiações · Não acumulativo</h3><div class="snap-bonus">${bonusItems.map(([p,t])=>`<div class="snap-bonus-item ${bonus?.perc===p?'active':''}"><strong>🎯 ${p}%</strong><span>${esc(t)}</span></div>`).join('')}</div></div>
        </div>
        <div>
          ${vendasHtml}
          ${snapServices(ent)}
          ${snapCommission(ent)}
        </div>
      </div>
    </div>`;
  }catch(e){console.log('Falha ao montar snapshot compacto',e); return '';}
}

function isUltimoDiaMes23(){
  const now=new Date(); const tomorrow=new Date(now.getFullYear(),now.getMonth(),now.getDate()+1);
  return tomorrow.getDate()===1 && now.getHours()>=23;
}

function snapshotComissaoEntidade(ent){
  const meta=calcMeta(ent); const rec=_recebResumo(ent); let c={};
  try{ if(ent.type==='vendedor'||ent.type==='filial') c=calcCommissionSummary(ent)||{}; }catch(e){c={erro:String(e)}}
  const totalPrev=Number(c.totalPrevisto||0);
  return {
    key:_comEntKey(ent), tipo:ent.type, nome:ent.nome||filialLabel(ent.filial), filial:ent.filial||'', login:ent.login||'',
    pendente:Number(ent.pendente||0), recebido:Number(ent.pago||rec.total||0), recebido_conciliado:Number(rec.total||0), qtd_recebidos:Number(rec.qtd||0),
    meta_geral:Number(meta.geral||0), grave_rec:Number(meta.grave?.rec||0), alerta_rec:Number(meta.alerta?.rec||0), atencao_rec:Number(meta.atencao?.rec||0),
    grave_alvo:Number(meta.grave?.alvo||0), alerta_alvo:Number(meta.alerta?.alvo||0), atencao_alvo:Number(meta.atencao?.alvo||0),
    venda_real:Number(c.vendaReal||0), servico_real:Number(c.servReal||0), caminhao_real:Number(c.camReal||0),
    faixa:String(c.faixaTxt||''), comissao_vendas:Number(c.vendasComissao||0), comissao_servicos:Number(c.servicosComissao||0), comissao_caminhao:Number(c.caminhaoComissao||0), bonus_meta:Number(c.bonusMeta||0), rent48:Number(c.rent48||0), rent52:Number(c.rent52||0), rent55:Number(c.rent55||0), total_previsto:totalPrev,
    elegivel_mercantil:Boolean(c.elegivelMercantil), elegivel_servicos:Boolean(c.elegivelServicos), html_individual:(()=>{try{return snapshotEntityHTML(ent)||''}catch(e){console.error('snapshot individual erro',e);return ''}})(), observacao:(ent.type==='crediarista'?'Crediarista: somente pagos conciliados após cobrança própria.':(ent.type==='terceiro'?'Cobrança terceiro.':''))
  };
}
function buildSnapshotComissionamentoMensal(month=mesAtualComissao()){
  const ents=[...flattenVendedores(),...flattenFiliais(),...crediaristaEntities(),thirdChargeEntity()].filter(Boolean);
  const entidades=ents.map(snapshotComissaoEntidade);
  const total=entidades.reduce((a,b)=>a+Number(b.total_previsto||0),0);
  return {month, gerado_em:new Date().toISOString(), versao_snapshot:'snapshot_visual_compacto_v2', atualizado_em_br:new Date().toLocaleString('pt-BR'), total_previsto:total, entidades};
}
async function salvarSnapshotComissionamentoMensal(auto=false){
  if(usuarioAtual?.tipo!=='master') return;
  const month=document.getElementById('histComMonthSave')?.value||mesAtualComissao();
  const payload=buildSnapshotComissionamentoMensal(month);
  const fd=new FormData(); fd.append('month',month); fd.append('payload',JSON.stringify(payload));
  try{
    const r=await fetch(API_COMIS,{method:'POST',body:fd}); const j=await r.json();
    if(j.ok){HIST_COMISSAO=j.data||{months:{}}; if(!auto) toast('✅ Histórico de comissionamento salvo.'); renderHistoricoComissaoResults();}
    else if(!auto) toast('⚠️ Não consegui salvar histórico de comissionamento.');
  }catch(e){console.log('Erro salvar comissionamento',e); if(!auto) toast('⚠️ Erro ao salvar histórico de comissionamento.');}
}
function baixarComissionamentoXLS(monthOverride){
  try{
    const month=monthOverride || document.getElementById('histComMonth')?.value || _histComMeses()[0] || mesAtualComissao();
    const snap=HIST_COMISSAO?.months?.[month];
    const rows=[...(snap?.entidades||[])];
    if(!rows.length){toast('Nenhum comissionamento salvo para exportar neste mês.'); return;}
    const cols=[
      ['nome','Nome'],['tipo','Tipo'],['filial','Filial'],['login','Login'],
      ['pendente','Pendente'],['recebido','Recebido'],['recebido_conciliado','Recebido conciliado'],['qtd_recebidos','Qtd recebidos'],
      ['meta_geral','Meta cobrança %'],['grave_rec','Recebido grave'],['alerta_rec','Recebido alerta'],['atencao_rec','Recebido atenção'],
      ['grave_alvo','Alvo grave'],['alerta_alvo','Alvo alerta'],['atencao_alvo','Alvo atenção'],
      ['venda_real','Venda real'],['servico_real','Serviço real'],['caminhao_real','Caminhão real'],
      ['faixa','Faixa'],['comissao_vendas','Comissão vendas'],['comissao_servicos','Comissão serviços'],['comissao_caminhao','Comissão caminhão'],
      ['bonus_meta','Bônus meta'],['rent48','Rent. 48'],['rent52','Rent. 52'],['rent55','Rent. 55'],['total_previsto','Total previsto'],['observacao','Observação']
    ];
    const moneyKeys=new Set([
      'pendente','recebido','recebido_conciliado','grave_rec','alerta_rec','atencao_rec',
      'grave_alvo','alerta_alvo','atencao_alvo','venda_real','servico_real','caminhao_real',
      'comissao_vendas','comissao_servicos','comissao_caminhao','bonus_meta','rent48','rent52','rent55','total_previsto'
    ]);
    const percentKeys=new Set(['meta_geral']);
    const fmtMoney=(v)=>'R$ '+Number(v||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});
    const fmtPct=(v)=>Number(v||0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+'%';
    const fmtVal=(key,v)=>{
      if(moneyKeys.has(key)) return fmtMoney(v);
      if(percentKeys.has(key)) return fmtPct(v);
      if(key==='qtd_recebidos') return String(Number(v||0));
      return v==null?'':String(v);
    };
    const td=(v)=>`<td style="border:1px solid #999;padding:4px;mso-number-format:'\@'">${esc(v==null?'':String(v))}</td>`;
    const html=`<html><head><meta charset="utf-8"></head><body><table><thead><tr>${cols.map(c=>`<th style="border:1px solid #999;padding:4px;background:#eee">${esc(c[1])}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>td(fmtVal(c[0],r[c[0]]))).join('')}</tr>`).join('')}</tbody></table></body></html>`;
    const blob=new Blob([html],{type:'application/vnd.ms-excel;charset=utf-8'});
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=`comissionamento_${String(month).replace(/[^0-9-]/g,'')}.xls`;
    document.body.appendChild(a); a.click(); setTimeout(()=>{URL.revokeObjectURL(a.href); a.remove();},500);
  }catch(e){console.error(e); toast('Erro ao gerar XLS de comissionamento.');}
}
function renderLinksRelatoriosCobranca(){
  const r=RELATORIOS_PUBLICOS||{};
  return `<div class="glass panel" style="margin-bottom:14px;border-color:rgba(96,165,250,.35)">
    <div class="section-head" style="margin:0 0 8px"><div><h2 style="font-size:18px">📥 Relatórios XLS da última execução</h2><div class="hint">Use estes arquivos para auditar se houve pagamento nas faixas grave, alerta e atenção. Eles são atualizados automaticamente a cada execução do robô.</div></div></div>
    <div style="display:flex;gap:10px;flex-wrap:wrap">
      <a class="btn primary" href="${esc(r.zip||'#')}?_=${Date.now()}" target="_blank" download>📦 Baixar pacote ZIP</a>
      <a class="btn soft" href="${esc(r.principal_xls||'#')}?_=${Date.now()}" target="_blank" download>Contas a receber principal</a>
      <a class="btn soft" href="${esc(r.quitados_original_xls||'#')}?_=${Date.now()}" target="_blank" download>Quitados original SGI</a>
      <a class="btn soft" href="${esc(r.quitados_processado_xlsx||'#')}?_=${Date.now()}" target="_blank" download>Quitados processado</a>
      <a class="btn soft" href="${esc(r.quitados_json||'#')}?_=${Date.now()}" target="_blank">JSON quitados</a>
    </div>
  </div>`;
}

function renderComissionamentoHistoricoTable(rows){
  if(!rows.length) return '<div class="empty">Nenhum comissionamento salvo para este mês.</div>';
  return `<div class="glass panel"><div class="tableish">${rows.map(r=>`<div class="row-item"><div class="row-top"><div><div class="name">${esc(r.nome||'')}</div><div class="small muted">${esc(r.tipo||'')} · ${esc(r.filial||'')}</div></div><div><strong>${pct(r.meta_geral||0)}</strong><div class="small muted">Meta cobrança</div></div><div><strong>${R(r.recebido||0)}</strong><div class="small muted">Recebido</div></div><div><strong>${R(r.comissao_vendas||0)}</strong><div class="small muted">Vendas</div></div><div><strong>${R(r.comissao_servicos||0)}</strong><div class="small muted">Serviços</div></div><div><strong>${R(r.bonus_meta||0)}</strong><div class="small muted">Bônus</div></div><div><strong>${R(r.total_previsto||0)}</strong><div class="small muted">Total previsto</div></div></div>${r.observacao?`<div class="small muted" style="margin-top:6px">${esc(r.observacao)}</div>`:''}</div>`).join('')}</div></div>`;
}

function findEntityBySnapshotRow(row){
  if(!row) return null;
  const key=String(row.key||'');
  const nome=String(row.nome||'');
  const filial=String(row.filial||'');
  let buckets=[];
  try{buckets=[...buckets,...flattenVendedores()]}catch(e){}
  try{buckets=[...buckets,...flattenFiliais()]}catch(e){}
  try{buckets=[...buckets,...crediaristaEntities()]}catch(e){}
  try{buckets=[...buckets,thirdChargeEntity()]}catch(e){}
  const getKey=(e)=>{try{return (typeof _comEntKey==='function')?_comEntKey(e):`${e.type||'ent'}::${e.filial||''}::${e.login||e.nome||''}`}catch(_){return ''}};
  return buckets.find(e=>String(getKey(e))===key)
      || buckets.find(e=>normName(e.nome)===normName(nome) && String(e.filial||'')===filial)
      || buckets.find(e=>normName(e.nome)===normName(nome))
      || null;
}
function snapshotHtmlFallbackFromRow(row,month){
  try{
    const R2=(v)=>typeof R==='function'?R(Number(v||0)):('R$ '+Number(v||0).toFixed(2).replace('.',','));
    const pct2=(v)=>typeof pct==='function'?pct(Number(v||0)):(Number(v||0).toFixed(0)+'%');
    return `<div class="snap-sheet"><style>
      .snap-sheet{width:1120px;max-width:100%;margin:0 auto;background:#0d0f14;color:#f3f6ff;font-family:Inter,Arial,sans-serif;padding:22px;border-radius:22px}
      .snap-head{border:1px solid rgba(255,255,255,.12);background:#161922;border-radius:18px;padding:16px 18px;margin-bottom:16px}.snap-head h1{margin:0;font-size:28px;color:#fff}.snap-sub{color:#aeb7ca;font-size:13px;margin-top:6px}
      .snap-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.snap-card{border:1px solid rgba(255,255,255,.12);background:#151821;border-radius:16px;padding:16px}.snap-title{font-size:12px;text-transform:uppercase;color:#8c96ab;font-weight:900;letter-spacing:.08em}.snap-value{font-size:25px;font-weight:950;margin-top:8px}.green{color:#34d399}.orange{color:#f59e0b}.blue{color:#60a5fa}.red{color:#fb7185}
      .snap-note{margin-top:14px;border:1px solid rgba(245,158,11,.35);background:rgba(245,158,11,.08);border-radius:16px;padding:14px;color:#fde68a;font-weight:800}
    </style><div class="snap-head"><h1>${esc(row.nome||'')}</h1><div class="snap-sub">${esc(row.tipo||'')} · ${esc(row.filial||'')} · fechamento ${esc(month||'')}</div></div><div class="snap-grid">
      <div class="snap-card"><div class="snap-title">Meta cobrança</div><div class="snap-value blue">${pct2(row.meta_geral||0)}</div></div>
      <div class="snap-card"><div class="snap-title">Recebido</div><div class="snap-value green">${R2(row.recebido||0)}</div></div>
      <div class="snap-card"><div class="snap-title">Vendas</div><div class="snap-value orange">${R2(row.comissao_vendas||0)}</div></div>
      <div class="snap-card"><div class="snap-title">Serviços</div><div class="snap-value orange">${R2(row.comissao_servicos||0)}</div></div>
      <div class="snap-card"><div class="snap-title">Bônus meta</div><div class="snap-value green">${R2(row.bonus_meta||0)}</div></div>
      <div class="snap-card"><div class="snap-title">Comissão caminhão</div><div class="snap-value orange">${R2(row.comissao_caminhao||0)}</div></div>
      <div class="snap-card"><div class="snap-title">Faixa</div><div class="snap-value blue">${esc(row.faixa||'-')}</div></div>
      <div class="snap-card"><div class="snap-title">Total previsto</div><div class="snap-value green">${R2(row.total_previsto||0)}</div></div>
    </div><div class="snap-note">Resumo reconstruído automaticamente porque a tela visual completa não estava salva neste fechamento. Clique em salvar fechamento novamente para gerar o modelo visual completo.</div></div>`;
  }catch(e){return `<div style="padding:20px;background:#111;color:#fff">Resumo indisponível: ${esc(String(e))}</div>`}
}

function getSnapshotHtmlFromSelection(){
  const month=document.getElementById('histComMonth')?.value || _histComMeses()[0] || mesAtualComissao();
  const key=document.getElementById('histComEntityView')?.value||'';
  const snap=HIST_COMISSAO?.months?.[month];
  const row=(snap?.entidades||[]).find(x=>String(x.key)===String(key));
  if(!row) return {ok:false,msg:'Registro não encontrado no histórico.'};

  let html=String(row.html_individual||'');
  let fonte='tela congelada salva no fechamento';
  if(!html){
    const ent=findEntityBySnapshotRow(row);
    if(ent){
      try{html=String(snapshotEntityHTML(ent)||'');}catch(e){console.error('snapshotEntityHTML falhou',e); html='';}
      fonte='gerada agora porque este fechamento antigo não tinha a tela salva';
    }
  }
  if(!html){
    html=snapshotHtmlFallbackFromRow(row,month);
    fonte='resumo reconstruído do histórico salvo';
  }
  return {ok:true,html,row,month,fonte};
}
function abrirTelaComissionamentoCongeladaPorSelect(){
  try{
    const data=getSnapshotHtmlFromSelection();
    if(!data.ok){toast(data.msg); return;}

    let viewer=document.getElementById('snapshotInlineViewer');
    if(!viewer){
      const box=document.getElementById('histComResults') || document.querySelector('.hist-results') || document.body;
      viewer=document.createElement('div');
      viewer.id='snapshotInlineViewer';
      box.prepend(viewer);
    }

    viewer.innerHTML=`<div class="snapshot-inline-toolbar">
      <div><strong>📌 Tela congelada</strong><div class="hint">${esc(data.row.nome||'')} · ${esc(data.row.filial||'')} · ${esc(data.month)} · ${esc(data.fonte)}</div></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn primary" onclick="imprimirSnapshotInline()">🖨️ Imprimir / Salvar PDF</button>
        <button class="btn soft" onclick="abrirSnapshotNovaAba()">Abrir em nova aba</button>
        <button class="btn soft" onclick="fecharSnapshotInline()">Fechar</button>
      </div>
    </div><div class="snapshot-inline-body" id="snapshotInlineBody">${data.html}</div>`;
    viewer.classList.add('show');
    viewer.scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){
    console.error('Erro ao abrir tela congelada inline:', e);
    toast('Erro ao abrir tela congelada: '+(e && e.message ? e.message : 'erro desconhecido'));
  }
}
function fecharSnapshotInline(){
  const v=document.getElementById('snapshotInlineViewer');
  if(v){v.classList.remove('show');v.innerHTML='';}
}
function imprimirSnapshotInline(){
  try{
    const data=getSnapshotHtmlFromSelection();
    if(!data.ok){toast(data.msg);return;}
    const w=window.open('','_blank');
    if(!w){toast('Pop-up bloqueado pelo navegador.');return;}
    w.document.open();
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Comissionamento</title><style>body{margin:0;background:#080a0f;color:#f4f6fb;font-family:Inter,Arial,sans-serif;padding:12px}@media print{body{padding:0}}</style></head><body>${data.html}<script>setTimeout(()=>window.print(),700)<\/script></body></html>`);
    w.document.close();
  }catch(e){console.error(e);toast('Erro ao imprimir tela congelada.');}
}
function abrirSnapshotNovaAba(){
  try{
    const data=getSnapshotHtmlFromSelection();
    if(!data.ok){toast(data.msg);return;}
    const w=window.open('','_blank');
    if(!w){toast('Pop-up bloqueado pelo navegador.');return;}
    w.document.open();
    w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>Comissionamento</title><style>body{margin:0;background:#080a0f;color:#f4f6fb;font-family:Inter,Arial,sans-serif;padding:12px}</style></head><body>${data.html}</body></html>`);
    w.document.close();
  }catch(e){console.error(e);toast('Erro ao abrir nova aba.');}
}

function renderHistoricoComissaoResults(){
  const months=_histComMeses(); const current=document.getElementById('histComMonth')?.value || months[0] || mesAtualComissao();
  const box=document.getElementById('histComResults'); if(!box) return;
  const snap=HIST_COMISSAO?.months?.[current];
  const saveInput=document.getElementById('histComMonthSave'); if(saveInput && !saveInput.value) saveInput.value=mesAtualComissao();
  if(!snap){box.innerHTML=`<div class="empty">Nenhum histórico salvo para ${esc(current)}. Clique em “Salvar fechamento do mês atual” para gravar o resultado visível agora.</div>`; return;}
  const rows=[...(snap.entidades||[])].sort((a,b)=>String(a.tipo).localeCompare(String(b.tipo),'pt-BR')||String(a.nome).localeCompare(String(b.nome),'pt-BR'));
  box.innerHTML=`<div class="kpis">${makeKpi('Mês',esc(snap.month||current),'var(--blue)')}${makeKpi('Total previsto',R(snap.total_previsto||0),'var(--green)')}${makeKpi('Entidades',String(rows.length),'var(--orange)')}${makeKpi('Salvo em',esc((snap.atualizado_em_br||snap.gerado_em||'').replace('T',' ').slice(0,19)),'var(--blue)')}</div>`+`<div class="glass panel"><div class="form-grid"><div class="input-card"><label>Ver tela congelada individual</label><div class="hint">Selecione 2026-05 no mês e escolha o colaborador/filial para abrir a tela congelada salva naquele fechamento.</div><select id="histComEntityView">${rows.map(r=>`<option value="${esc(r.key||'')}">${esc(r.nome||'')} · ${esc(r.filial||'')}</option>`).join('')}</select></div><div style="display:flex;align-items:end;gap:8px;flex-wrap:wrap"><button class="btn primary" onclick="abrirTelaComissionamentoCongeladaPorSelect()">Abrir tela congelada</button><button class="btn soft" onclick="baixarComissionamentoXLS()">📊 Baixar XLS do mês em R$</button></div></div></div>`+renderComissionamentoHistoricoTable(rows);
}

function setHistMode(mode){window._histMode=mode; document.getElementById('histDailyPane')?.classList.toggle('hidden',mode!=='daily'); document.getElementById('histMonthPane')?.classList.toggle('hidden',mode!=='monthly'); document.getElementById('histSalesPane')?.classList.toggle('hidden',mode!=='sales'); document.getElementById('histThirdPane')?.classList.toggle('hidden',mode!=='third'); document.getElementById('histComPane')?.classList.toggle('hidden',mode!=='comissao'); document.getElementById('histTabDaily')?.classList.toggle('active',mode==='daily'); document.getElementById('histTabMonthly')?.classList.toggle('active',mode==='monthly'); document.getElementById('histTabSales')?.classList.toggle('active',mode==='sales'); document.getElementById('histTabThird')?.classList.toggle('active',mode==='third'); document.getElementById('histTabCom')?.classList.toggle('active',mode==='comissao'); if(mode==='daily'){updateHistEntityFilter(); renderHistoricoResults();} else if(mode==='monthly'){updateHistMonthEntityFilter(); renderHistoricoMonthResults();} else if(mode==='third'){renderHistoricoTerceiro();} else if(mode==='comissao'){renderHistoricoComissaoResults();} else {updateHistSalesEntityFilter(); updateHistSalesMonthEntityFilter(); renderHistoricoSalesResults(); renderHistoricoSalesMonthResults();}}
function updateHistEntityFilter(){const dateVal=_histCurrentDate(); const scope=document.getElementById('histScope')?.value||'empresa'; const wrap=document.getElementById('histEntityWrap'); const sel=document.getElementById('histEntity'); if(!wrap||!sel) return; wrap.classList.toggle('hidden',!(scope==='vendedores'||scope==='filiais')); sel.innerHTML=_histEntityOptions(dateVal, scope);}
function updateHistMonthEntityFilter(){const monthVal=_histCurrentMonth(); const scope=document.getElementById('histMonthScope')?.value||'empresa'; const wrap=document.getElementById('histMonthEntityWrap'); const sel=document.getElementById('histMonthEntity'); if(!wrap||!sel) return; wrap.classList.toggle('hidden',!(scope==='vendedores'||scope==='filiais')); sel.innerHTML=_histMonthEntityOptions(monthVal, scope);}
function renderHistoricoTable(rows, scope, title='📋 Histórico'){if(!rows.length) return `<div class="empty">Nenhum registro encontrado para o filtro escolhido.</div>`; return `<div class="glass panel"><div class="section-head" style="margin:0 0 10px"><div><h2 style="font-size:18px">${title}</h2></div></div>${rows.map(r=>`<div class="log-row" style="margin-bottom:10px"><div><strong>${esc(r.nome||r.filial||'Empresa')}</strong><div class="small muted">${esc(r.filial||'Resumo')}</div></div><div><strong>${R(r.pendente||0)}</strong><div class="small muted">Pendente</div></div><div><strong>${R(r.recebido||0)}</strong><div class="small muted">Recebido</div></div><div><strong>${pct(r.perc_meta||0)}</strong><div class="small muted">Meta</div></div><div><strong>${R(r.grave_alvo||0)} / ${R(r.alerta_alvo||0)} / ${R(r.atencao_alvo||0)}</strong><div class="small muted">Alvos G/A/At</div></div></div>`).join('')}</div>`}
function renderHistoricoResults(){const dateVal=_histCurrentDate(); const scope=document.getElementById('histScope')?.value||'empresa'; const entity=document.getElementById('histEntity')?.value||''; const box=document.getElementById('histResults'); const d=HIST_DASH?.dates?.[dateVal]; if(!box){return} if(!d){box.innerHTML='<div class="empty">Nenhum histórico salvo para esta data.</div>'; return} let top=`<div class="kpis">${makeKpi('Pendente do dia',R(d.empresa?.pendente||0),'var(--red)')}${makeKpi('Recebido do dia',R(d.empresa?.recebido||0),'var(--green)')}${makeKpi('Grave do dia',R(d.empresa?.grave||0),'var(--red)')}${makeKpi('Alerta do dia',R(d.empresa?.alerta||0),'var(--orange)')}</div><div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0"><div><h2 style="font-size:18px">⚙️ Meta usada no dia</h2><div class="hint">Global: G ${Number(d.empresa?.config_global?.grave_pct||0)}% · A ${Number(d.empresa?.config_global?.alerta_pct||0)}% · At ${Number(d.empresa?.config_global?.atencao_pct||0)}% · Pesos ${Number(d.empresa?.config_global?.peso_grave||0)}/${Number(d.empresa?.config_global?.peso_alerta||0)}/${Number(d.empresa?.config_global?.peso_atencao||0)}</div></div><div class="small muted">${esc(dateVal)}</div></div></div>`; if(scope==='empresa'){box.innerHTML=top + renderHistoricoTable([{nome:'Empresa',filial:'Resumo geral',pendente:d.empresa?.pendente||0,recebido:d.empresa?.recebido||0,perc_meta:0,grave_alvo:0,alerta_alvo:0,atencao_alvo:0}], 'empresa','📋 Histórico diário da empresa'); return} const source = scope==='filiais' ? Object.entries(d.filiais||{}).map(([k,v])=>({...v,key:k})) : Object.entries(d.vendedores||{}).map(([k,v])=>({...v,key:k})); const rows=entity?source.filter(x=>x.key===entity):source; box.innerHTML=renderLinksRelatoriosCobranca()+top + renderHistoricoTable(rows, scope, `📋 Histórico diário ${scope==='filiais'?'de filiais':'de vendedores'}`);}
function renderHistoricoMonthResults(){const monthVal=_histCurrentMonth(); const scope=document.getElementById('histMonthScope')?.value||'empresa'; const entity=document.getElementById('histMonthEntity')?.value||''; const box=document.getElementById('histMonthResults'); const d=HIST_DASH?.months_closed?.[monthVal]; if(!box){return} if(!d){box.innerHTML=renderLinksRelatoriosCobranca()+'<div class="empty">Nenhum fechamento mensal salvo para este mês.</div>'; return} const cfg=d.config_global_fechamento||{}; let top=`<div class="kpis">${makeKpi('Mês fechado',esc(monthVal),'var(--blue)')}${makeKpi('Último dia',esc(d.ultimo_dia_historico||'-'),'var(--blue)')}${makeKpi('Snapshot final',esc(d.snapshot_final_data||'-'),'var(--blue)')}${makeKpi('Meta mês',esc(d.meta_file||'-'),'var(--blue)')}</div><div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0"><div><h2 style="font-size:18px">📦 Fechamento mensal travado</h2><div class="hint">Global no fechamento: G ${Number(cfg.grave_pct||0)}% · A ${Number(cfg.alerta_pct||0)}% · At ${Number(cfg.atencao_pct||0)}% · Pesos ${Number(cfg.peso_grave||0)}/${Number(cfg.peso_alerta||0)}/${Number(cfg.peso_atencao||0)}</div></div><div class="small muted">Fechado em ${esc((d.fechado_em||'').replace('T',' ').slice(0,16))}</div></div></div>`;
 if(scope==='empresa'){const e=d.empresa_final||{}; box.innerHTML=renderLinksRelatoriosCobranca()+top+renderHistoricoTable([{nome:'Empresa',filial:'Resultado final do mês',pendente:e.pendente||0,recebido:e.recebido||0,perc_meta:e.perc_meta||0,grave_alvo:e.grave_alvo||0,alerta_alvo:e.alerta_alvo||0,atencao_alvo:e.atencao_alvo||0}], 'empresa','📋 Resultado final mensal da empresa'); return}
 const source=scope==='filiais'?Object.entries(d.filiais_finais||{}).map(([k,v])=>({...v,key:k})) : Object.entries(d.vendedores_finais||{}).map(([k,v])=>({...v,key:k}));
 const rows=entity?source.filter(x=>x.key===entity):source; box.innerHTML=renderLinksRelatoriosCobranca()+top + renderHistoricoTable(rows, scope, `📋 Resultado final mensal ${scope==='filiais'?'de filiais':'de vendedores'}`);}
function renderHistoricoTerceiro(){const box=document.getElementById('histThirdResults'); if(!box) return; const logs=(COB_LOGS||[]).filter(x=>String(x.usuario||'').toLowerCase()===COBRANCA10_LOGIN || String(x.usuario||'').toLowerCase()===COBRANCA10_NOME.toLowerCase()).slice().reverse(); const ent=thirdChargeEntity(); const top=`<div class="kpis">${makeKpi('Títulos na carteira',String((CLIENTES_TERCEIRO?.grave?.length||0)+(CLIENTES_TERCEIRO?.alerta?.length||0)+(CLIENTES_TERCEIRO?.atencao?.length||0)),'var(--blue)')}${makeKpi('Pendente',R(ent.pendente||0),'var(--red)')}${makeKpi('Recebido',R(ent.pago||0),'var(--green)')}${makeKpi('Cobranças lançadas',String(logs.length),'var(--orange)')}</div>`; const comm=renderTerceiroCommission(ent); const rows=logs.length?logs.map(x=>`<div class="log-row"><div><strong>${esc(x.cliente||'')}</strong><div class="small muted">${esc(x.titulo||'')} · Parcela ${esc(x.parcela||'')}</div></div><div><strong>${R(x.pendente||0)}</strong><div class="small muted">${esc(x.filial||'')}</div></div><div><strong>${esc((x.server_time||'').replace('T',' ').slice(0,16))}</strong><div class="small muted">Data</div></div><div><strong>${esc(x.telefone||'')}</strong><div class="small muted">Telefone</div></div></div>`).join(''):'<div class="empty">Nenhuma cobrança do Cobrança10 encontrada.</div>'; box.innerHTML=top+comm+`<div class="glass panel"><div class="section-head"><div><h2 style="font-size:18px">🤝 Cobranças Terceiro</h2><div class="hint">Histórico apenas do usuário Cobrança10.</div></div></div><div class="logs-list">${rows}</div></div>`}
function setHistMode(mode){window._histMode=mode; document.getElementById('histDailyPane')?.classList.toggle('hidden',mode!=='daily'); document.getElementById('histMonthPane')?.classList.toggle('hidden',mode!=='monthly'); document.getElementById('histSalesPane')?.classList.toggle('hidden',mode!=='sales'); document.getElementById('histThirdPane')?.classList.toggle('hidden',mode!=='third'); document.getElementById('histTabDaily')?.classList.toggle('active',mode==='daily'); document.getElementById('histTabMonthly')?.classList.toggle('active',mode==='monthly'); document.getElementById('histTabSales')?.classList.toggle('active',mode==='sales'); document.getElementById('histTabThird')?.classList.toggle('active',mode==='third'); if(mode==='daily'){updateHistEntityFilter(); renderHistoricoResults();} else if(mode==='monthly'){updateHistMonthEntityFilter(); renderHistoricoMonthResults();} else if(mode==='sales'){updateHistSalesEntityFilter(); updateHistSalesMonthEntityFilter(); renderHistoricoSalesResults(); renderHistoricoSalesMonthResults();} else {renderHistoricoTerceiro();}}
function renderHistoricoTab(){const dates=_histDates(); const months=_histMonths(); const salesDates=_histSalesDates(); const salesMonths=_histSalesMonths(); histSection.innerHTML=`<div class="section-head"><div><h2>🗂️ Histórico</h2><div class="hint">Consulte o histórico diário, vendas e os fechamentos mensais travados do Master/Diretor.</div></div></div><div class="tabs" style="justify-content:flex-start;margin:0 0 14px"><button id="histTabDaily" class="tab active" onclick="setHistMode('daily')">📅 Diário</button><button id="histTabMonthly" class="tab" onclick="setHistMode('monthly')">📦 Fechamento mensal</button><button id="histTabSales" class="tab" onclick="setHistMode('sales')">🧡 Vendas</button><button id="histTabThird" class="tab" onclick="setHistMode('third')">🤝 Cobranças Terceiro</button></div><div id="histDailyPane"><div class="glass panel" style="margin-bottom:14px"><div class="search-row"><div class="input-card"><label>Data</label><select id="histDate" onchange="updateHistEntityFilter();renderHistoricoResults()">${dates.map(d=>`<option value="${d}">${d}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histScope" onchange="updateHistEntityFilter();renderHistoricoResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histEntity" onchange="renderHistoricoResults()"><option value="">Todos</option></select></div></div></div><div id="histResults"></div></div><div id="histMonthPane" class="hidden"><div class="glass panel" style="margin-bottom:14px"><div class="search-row"><div class="input-card"><label>Mês fechado</label><select id="histMonth" onchange="updateHistMonthEntityFilter();renderHistoricoMonthResults()">${months.map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histMonthScope" onchange="updateHistMonthEntityFilter();renderHistoricoMonthResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histMonthEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histMonthEntity" onchange="renderHistoricoMonthResults()"><option value="">Todos</option></select></div></div></div><div id="histMonthResults"></div></div><div id="histSalesPane" class="hidden"><div class="glass panel" style="margin-bottom:14px"><div class="search-row"><div class="input-card"><label>Data de vendas</label><select id="histSalesDate" onchange="updateHistSalesEntityFilter();renderHistoricoSalesResults()">${salesDates.map(d=>`<option value="${d}">${d}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histSalesScope" onchange="updateHistSalesEntityFilter();renderHistoricoSalesResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histSalesEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histSalesEntity" onchange="renderHistoricoSalesResults()"><option value="">Todos</option></select></div></div></div><div id="histSalesResults"></div><div class="glass panel" style="margin:14px 0"><div class="search-row"><div class="input-card"><label>Mês de vendas</label><select id="histSalesMonth" onchange="updateHistSalesMonthEntityFilter();renderHistoricoSalesMonthResults()">${salesMonths.map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div><div class="input-card"><label>Escopo</label><select id="histSalesMonthScope" onchange="updateHistSalesMonthEntityFilter();renderHistoricoSalesMonthResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div><div id="histSalesMonthEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histSalesMonthEntity" onchange="renderHistoricoSalesMonthResults()"><option value="">Todos</option></select></div></div></div><div id="histSalesMonthResults"></div></div><div id="histThirdPane" class="hidden"><div id="histThirdResults"></div></div>`; if(dates.length){document.getElementById('histDate').value=dates[0]} if(months.length){document.getElementById('histMonth').value=months[0]} if(salesDates.length){document.getElementById('histSalesDate').value=salesDates[0]} if(salesMonths.length){document.getElementById('histSalesMonth').value=salesMonths[0]} setHistMode(window._histMode||'daily');}

// ===== OVERRIDE HISTÓRICO COMISSIONAMENTO VISÍVEL =====

function setHistMode(mode){
  window._histMode=mode;
  document.getElementById('histDailyPane')?.classList.toggle('hidden',mode!=='daily');
  document.getElementById('histMonthPane')?.classList.toggle('hidden',mode!=='monthly');
  document.getElementById('histSalesPane')?.classList.toggle('hidden',mode!=='sales');
  document.getElementById('histThirdPane')?.classList.toggle('hidden',mode!=='third');
  document.getElementById('histComPane')?.classList.toggle('hidden',mode!=='comissao');

  document.getElementById('histTabDaily')?.classList.toggle('active',mode==='daily');
  document.getElementById('histTabMonthly')?.classList.toggle('active',mode==='monthly');
  document.getElementById('histTabSales')?.classList.toggle('active',mode==='sales');
  document.getElementById('histTabThird')?.classList.toggle('active',mode==='third');
  document.getElementById('histTabCom')?.classList.toggle('active',mode==='comissao');

  if(mode==='daily'){
    updateHistEntityFilter(); renderHistoricoResults();
  } else if(mode==='monthly'){
    updateHistMonthEntityFilter(); renderHistoricoMonthResults();
  } else if(mode==='third'){
    renderHistoricoTerceiro();
  } else if(mode==='comissao'){
    try{carregarHistoricoComissaoOnline().then(()=>renderHistoricoComissaoResults())}catch(e){renderHistoricoComissaoResults()}
  } else {
    updateHistSalesEntityFilter(); updateHistSalesMonthEntityFilter(); renderHistoricoSalesResults(); renderHistoricoSalesMonthResults();
  }
}


function renderHistoricoTab(){
  const dates=_histDates();
  const months=_histMonths();
  const salesDates=_histSalesDates();
  const salesMonths=_histSalesMonths();
  const comMonths=_histComMeses();
  const currentComMonth=mesAtualComissao();

  histSection.innerHTML=`
    <div class="section-head">
      <div>
        <h2>🗂️ Histórico</h2>
        <div class="hint">Consulte o histórico diário, vendas, fechamentos mensais e o histórico de comissionamento para folha.</div>
      </div>
    </div>

    <div class="tabs" style="justify-content:flex-start;margin:0 0 14px">
      <button id="histTabDaily" class="tab active" onclick="setHistMode('daily')">📅 Diário</button>
      <button id="histTabMonthly" class="tab" onclick="setHistMode('monthly')">📦 Fechamento mensal</button>
      <button id="histTabSales" class="tab" onclick="setHistMode('sales')">🧡 Vendas</button>
      <button id="histTabThird" class="tab" onclick="setHistMode('third')">🤝 Cobranças Terceiro</button>
      <button id="histTabCom" class="tab" onclick="setHistMode('comissao')">💰 Comissionamento</button>
    </div>

    <div id="histDailyPane">
      <div class="glass panel" style="margin-bottom:14px">
        <div class="search-row">
          <div class="input-card"><label>Data</label><select id="histDate" onchange="updateHistEntityFilter();renderHistoricoResults()">${dates.map(d=>`<option value="${d}">${d}</option>`).join('')}</select></div>
          <div class="input-card"><label>Escopo</label><select id="histScope" onchange="updateHistEntityFilter();renderHistoricoResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div>
          <div id="histEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histEntity" onchange="renderHistoricoResults()"><option value="">Todos</option></select></div>
        </div>
      </div>
      <div id="histResults"></div>
    </div>

    <div id="histMonthPane" class="hidden">
      <div class="glass panel" style="margin-bottom:14px">
        <div class="search-row">
          <div class="input-card"><label>Mês fechado</label><select id="histMonth" onchange="updateHistMonthEntityFilter();renderHistoricoMonthResults()">${months.map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div>
          <div class="input-card"><label>Escopo</label><select id="histMonthScope" onchange="updateHistMonthEntityFilter();renderHistoricoMonthResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div>
          <div id="histMonthEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histMonthEntity" onchange="renderHistoricoMonthResults()"><option value="">Todos</option></select></div>
        </div>
      </div>
      <div id="histMonthResults"></div>
    </div>

    <div id="histSalesPane" class="hidden">
      <div class="glass panel" style="margin-bottom:14px">
        <div class="search-row">
          <div class="input-card"><label>Data de vendas</label><select id="histSalesDate" onchange="updateHistSalesEntityFilter();renderHistoricoSalesResults()">${salesDates.map(d=>`<option value="${d}">${d}</option>`).join('')}</select></div>
          <div class="input-card"><label>Escopo</label><select id="histSalesScope" onchange="updateHistSalesEntityFilter();renderHistoricoSalesResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div>
          <div id="histSalesEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histSalesEntity" onchange="renderHistoricoSalesResults()"><option value="">Todos</option></select></div>
        </div>
      </div>
      <div id="histSalesResults"></div>
      <div class="glass panel" style="margin:14px 0">
        <div class="search-row">
          <div class="input-card"><label>Mês de vendas</label><select id="histSalesMonth" onchange="updateHistSalesMonthEntityFilter();renderHistoricoSalesMonthResults()">${salesMonths.map(m=>`<option value="${m}">${m}</option>`).join('')}</select></div>
          <div class="input-card"><label>Escopo</label><select id="histSalesMonthScope" onchange="updateHistSalesMonthEntityFilter();renderHistoricoSalesMonthResults()"><option value="empresa">Empresa</option><option value="filiais">Filiais</option><option value="vendedores">Vendedores</option></select></div>
          <div id="histSalesMonthEntityWrap" class="input-card hidden"><label>Filtro</label><select id="histSalesMonthEntity" onchange="renderHistoricoSalesMonthResults()"><option value="">Todos</option></select></div>
        </div>
      </div>
      <div id="histSalesMonthResults"></div>
    </div>

    <div id="histThirdPane" class="hidden"><div id="histThirdResults"></div></div>

    <div id="histComPane" class="hidden">
      <div class="glass panel" style="margin-bottom:14px">
        <div class="section-head" style="margin:0 0 10px">
          <div>
            <h2 style="font-size:18px">💰 Histórico mensal de comissionamento</h2>
            <div class="hint">Use para fechar o mês e consultar depois os valores para a folha de pagamento.</div>
          </div>
        </div>
        <div class="search-row">
          <div class="input-card">
            <label>Mês para consultar</label>
            <select id="histComMonth" onchange="renderHistoricoComissaoResults()">
              ${(comMonths.length?comMonths:[currentComMonth]).map(m=>`<option value="${m}">${m}</option>`).join('')}
            </select>
          </div>
          <div class="input-card">
            <label>Mês para salvar/atualizar</label>
            <input id="histComMonthSave" value="${currentComMonth}" placeholder="AAAA-MM">
          </div>
          <div class="input-card" style="display:flex;align-items:end">
            <button class="btn" onclick="salvarSnapshotComissionamentoMensal(false)">💾 Salvar fechamento do mês atual</button>
          </div>
        </div>
      </div>
      <div id="histComResults"></div>
    </div>
  `;

  if(dates.length){document.getElementById('histDate').value=dates[0]}
  if(months.length){document.getElementById('histMonth').value=months[0]}
  if(salesDates.length){document.getElementById('histSalesDate').value=salesDates[0]}
  if(salesMonths.length){document.getElementById('histSalesMonth').value=salesMonths[0]}
  if(comMonths.length){document.getElementById('histComMonth').value=comMonths[0]}
  setHistMode(window._histMode||'daily');
}

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
  <div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0 0 8px"><div><h2 style="font-size:18px">👑 Contas administrativas</h2><div class="hint">O Master visualiza aqui a senha definida para cada acesso. A senha Master é fixa no arquivo do robô.</div></div></div><div class="grid-cards"><div class="glass card" style="cursor:default"><div class="title" style="min-height:auto">Master</div><div class="note" style="margin-top:10px;background:rgba(15,23,42,.04);border:1px solid rgba(15,23,42,.08);border-radius:14px;padding:10px 12px"><div><b>Login:</b> <code>${esc(LOGIN_MASTER)}</code></div><div><b>Senha definida agora:</b> <code style="font-size:14px">${esc(SENHA_MASTER)}</code></div></div></div>${renderSenhaCard(AUTH_STATE?.director||{login:'diretorcomercial',nome:'Diretor Comercial',password:SENHA_DIRETOR,initial_password:SENHA_DIRETOR,must_change_password:true}, true)}</div></div>
  <div class="glass panel" style="margin-bottom:14px"><div class="section-head" style="margin:0 0 8px"><div><h2 style="font-size:18px">➕ Criar usuário de acesso</h2><div class="hint">Aqui você cria apenas o login/senha de acesso. Depois vá em Metas > Crediaristas configuráveis para vincular esse usuário à filial/base e ao percentual.</div></div></div><div class="form-grid bonus"><div class="input-card"><label>Login</label><input id="newUserLogin" placeholder="ex: crediaristaf07"></div><div class="input-card"><label>Nome</label><input id="newUserNome" placeholder="ex: CREDIARISTAF07"></div><div class="input-card"><label>Filial</label><input id="newUserFilial" placeholder="ex: F7"></div><div class="input-card"><label>Senha inicial</label><input id="newUserSenha" placeholder="mín. 4 caracteres"></div></div><div class="form-grid bonus" style="margin-top:10px"><div class="input-card"><label>Tipo</label><select id="newUserTipo"><option value="crediarista">Crediarista</option><option value="cobranca">Cobrança</option></select></div></div><div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px"><button class="btn primary" onclick="adminCriarUsuarioCobranca()">💾 Criar usuário</button></div><div id="newUserMsg" class="note" style="margin-top:10px"></div></div>
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
async function fazerLogin(){
  const u=(document.getElementById('loginUser').value||'').trim().toLowerCase();
  const s=(document.getElementById('loginPass').value||'').trim();
  const msg=document.getElementById('loginMsg');
  msg.textContent='';
  if(!u || !s){msg.textContent='Informe usuário e senha.'; return;}

  // Master abre imediatamente, sem depender de API PHP online.
  if(u===LOGIN_MASTER.toLowerCase() && s===SENHA_MASTER){
    usuarioAtual={tipo:'master',nome:'Master',roleLabel:'Master'};
    saveSession();
    return abrirApp();
  }

  // Demais usuários tentam atualizar credenciais, mas com timeout curto.
  try{await carregarCredenciaisOnline();}catch(e){console.log('Login seguindo com credenciais embutidas',e);}

  if(u===LOGIN_DIRETOR.toLowerCase()){
    const authDir=getAuthUser(u);
    const senhaDir=authDir?.password || SENHA_DIRETOR;
    if(String(senhaDir)===s){
      if(authDir?.must_change_password){
        msg.textContent='Primeiro acesso do Diretor Comercial: defina uma nova senha.';
        return openPrimeiroAcesso(u);
      }
      usuarioAtual={tipo:'master',nome:'Diretor Comercial',roleLabel:'Diretor Comercial'};
      saveSession();
      return abrirApp();
    }
  }

  const auth=getAuthUser(u);
  if(CREDS[u] && auth && String(auth.password)===s){
    if(auth.must_change_password){
      msg.textContent='Primeiro acesso: defina sua nova senha.';
      return openPrimeiroAcesso(u);
    }
    usuarioAtual={tipo:'user',login:u,...CREDS[u]};
    saveSession();
    return abrirApp();
  }

  msg.textContent='Login ou senha inválidos.';
}
async function abrirApp(){
  try{document.body.classList.toggle('master-view', String(usuarioAtual?.tipo||'').toLowerCase()==='master'); document.body.classList.toggle('diretor-view', String(usuarioAtual?.tipo||'').toLowerCase()==='diretor');}catch(e){}
 loginScreen.classList.add('hidden'); app.classList.remove('hidden'); if(usuarioAtual.tipo==='master'){document.getElementById('kpis').classList.remove('hidden'); renderKPIs(); const isDiretor=usuarioAtual?.roleLabel==='Diretor Comercial'; userBadge.textContent=isDiretor?'👑 Diretor Comercial':'👑 Master'; masterTabs.classList.remove('hidden'); document.querySelectorAll('#masterTabs .tab').forEach(btn=>{const t=btn.dataset.tab; btn.classList.toggle('hidden', isDiretor && ['cobrancas','senhas'].includes(t));}); setMainTab('vendedores')} else if(usuarioAtual.is_viewer){document.getElementById('kpis').classList.remove('hidden'); renderKPIs(); userBadge.textContent='📺 Painel'; masterTabs.classList.add('hidden'); mainFilters.classList.add('hidden'); listSection.classList.add('hidden'); metaSection.classList.add('hidden'); logSection.classList.add('hidden'); avisosSection.classList.add('hidden'); senhasSection.classList.add('hidden'); histSection.classList.add('hidden'); document.getElementById('mainScreen').classList.remove('hidden'); detailScreen.classList.add('hidden');} else {document.getElementById('kpis').classList.add('hidden'); userBadge.textContent=usuarioAtual.is_terceiro?`🤝 ${usuarioAtual.nome}`:(usuarioAtual.is_crediarista?`🧾 ${usuarioAtual.nome}`:(usuarioAtual.is_gerente?`🏬 ${usuarioAtual.filial}`:`👤 ${usuarioAtual.nome}`)); masterTabs.classList.add('hidden'); mainFilters.classList.add('hidden'); const ent=usuarioAtual.is_terceiro?findEntity({type:'terceiro',filial:'FTER',nome:COBRANCA10_NOME}):(usuarioAtual.is_crediarista?findEntity({type:'crediarista',filial:usuarioAtual.filial,login:usuarioAtual.login,nome:usuarioAtual.nome}):(usuarioAtual.is_gerente?findEntity({type:'filial',filial:usuarioAtual.filial}):findEntity({type:'vendedor',filial:usuarioAtual.filial,nome:usuarioAtual.nome}))); document.getElementById('mainScreen').classList.add('hidden'); detailScreen.classList.remove('hidden'); if(usuarioAtual.is_terceiro){openThirdChargePanel()} else if(usuarioAtual.is_crediarista){openCrediaristaPanel(usuarioAtual.login,usuarioAtual.filial,usuarioAtual.nome)} else if(ent) openEntity({type:ent.type,filial:ent.filial,nome:ent.nome,login:ent.login}) }
  setTimeout(()=>{tentarAtualizarOnlineDepoisLogin();}, 80);
}
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

_gerar_zip_relatorios_publicos()
js_relatorios_publicos = json.dumps({
    "principal_xls": f"{RELATORIOS_PUBLIC_BASE}/ultimo_contas_receber_principal.xls",
    "quitados_original_xls": f"{RELATORIOS_PUBLIC_BASE}/ultimo_contas_receber_quitados_original.xls",
    "quitados_processado_xlsx": f"{RELATORIOS_PUBLIC_BASE}/quitados_180d_contas_receber.xlsx",
    "quitados_json": f"{RELATORIOS_PUBLIC_BASE}/quitados_180d_contas_receber.json",
    "zip": f"{RELATORIOS_PUBLIC_BASE}/ultimos_relatorios_cobranca.zip",
}, ensure_ascii=False)

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
    '__JS_QUITADOS_180__': js_quitados_180,
    '__JS_RELATORIOS_PUBLICOS__': js_relatorios_publicos,
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

HISTORICO_COMISSIONAMENTO_API_PHP = r"""<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(204); exit; }
$file = __DIR__ . '/historico_comissionamento.json';
if (!file_exists($file)) file_put_contents($file, json_encode(['months'=>new stdClass()], JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT));
$data = json_decode(file_get_contents($file), true);
if (!is_array($data)) $data = ['months'=>[]];
if (!isset($data['months']) || !is_array($data['months'])) $data['months'] = [];
if ($_SERVER['REQUEST_METHOD'] === 'GET') { echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit; }
$month = $_POST['month'] ?? date('Y-m');
$payloadRaw = $_POST['payload'] ?? '';
$payload = json_decode($payloadRaw, true);
if (!is_array($payload)) { echo json_encode(['ok'=>false,'error'=>'payload_invalido'], JSON_UNESCAPED_UNICODE); exit; }
$payload['month'] = $month;
$payload['salvo_em_php'] = date('c');
$data['months'][$month] = $payload;
file_put_contents($file, json_encode($data, JSON_UNESCAPED_UNICODE|JSON_PRETTY_PRINT));
echo json_encode(['ok'=>true,'data'=>$data], JSON_UNESCAPED_UNICODE); exit;
?>"""

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
        ftp.storbinary('STOR historico_comissionamento_api.php', BytesIO(HISTORICO_COMISSIONAMENTO_API_PHP.encode('utf-8')))
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
            if quitados_180_info.get('json_path') and os.path.exists(quitados_180_info['json_path']):
                with open(quitados_180_info['json_path'], 'rb') as f_q_json:
                    ftp.storbinary('STOR quitados_180d_contas_receber.json', f_q_json)
            if quitados_180_info.get('xlsx_path') and os.path.exists(quitados_180_info['xlsx_path']):
                with open(quitados_180_info['xlsx_path'], 'rb') as f_q_xlsx:
                    ftp.storbinary('STOR quitados_180d_contas_receber.xlsx', f_q_xlsx)
        except Exception as e_q_ftp:
            print(f'⚠️ Erro ao enviar quitados 180d ao FTP: {e_q_ftp}')

        try:
            # Publica os relatórios auditáveis em /public_html/colaborador/relatorios
            try:
                ftp.mkd('relatorios')
            except Exception:
                pass
            ftp.cwd('relatorios')
            for _fname in [
                'ultimo_contas_receber_principal.xls',
                'ultimo_contas_receber_quitados_original.xls',
                'quitados_180d_contas_receber.xlsx',
                'quitados_180d_contas_receber.json',
                'ultimos_relatorios_cobranca.zip',
            ]:
                _p_rel = os.path.join(RELATORIOS_DIR, _fname)
                if os.path.exists(_p_rel):
                    with open(_p_rel, 'rb') as _f_rel:
                        ftp.storbinary(f'STOR {_fname}', _f_rel)
                    print(f'📤 Relatório publicado no FTP: /colaborador/relatorios/{_fname}')
            ftp.cwd('..')
        except Exception as e_rel_ftp:
            print(f'⚠️ Erro ao publicar relatórios XLS no FTP: {e_rel_ftp}')

        # Pacote de vendas/margem/rentabilidade/serviços/diária fica exclusivo do dashboard_sales_worker_headless.py.
        # Isso evita o navegador misturar arquivos de horários diferentes.
        print('ℹ️ MAIN: não publica metas_vendas/margens/sales_version; pacote de vendas é exclusivo do sales worker.')
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
            # sales_version.json é exclusivo do dashboard_sales_worker_headless.py para sincronizar vendas/margens/serviços juntos.
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