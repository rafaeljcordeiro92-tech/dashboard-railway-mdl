# VERSAO: SGI_VENDEDORES_MONITOR_V10.127
# Lista diaria de vendedores/gerentes ativos no SGI, enviada ao Telegram por destino configuravel.
from __future__ import annotations

import os, re, sys, json, time, hmac, hashlib, unicodedata, urllib.request, urllib.parse, urllib.error, tempfile, shutil
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BR_TZ = ZoneInfo(os.getenv('APP_TZ','America/Sao_Paulo'))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
URL = os.getenv('SGI_BASE_URL','https://smart.sgisistemas.com.br').rstrip('/')
LOGIN = os.getenv('SGI_LOGIN','administrativo01.moveisdolar')
SENHA = os.getenv('SGI_SENHA','mdladm01')
PUBLIC_BASE = os.getenv('MDL_COLAB_PUBLIC_BASE','https://moveisdolar.com.br/colaborador').rstrip('/')
CONFIG_URL = PUBLIC_BASE + '/config_meta.json'
MONITOR_JSON = os.path.join(BASE_DIR, 'sgi_vendedores_monitor.json')
FILIAIS = ('F1','F2','F3','F4','F5','F6','F7','F8','F9')
MONITOR_BUILD = 'SGI_VENDEDORES_MONITOR_V10.127'
LOGIN_STRATEGY = 'INTERACTABLE_ONLY_NO_CLEAR'



def now_br(): return datetime.now(BR_TZ)

def _norm(s):
    x = unicodedata.normalize('NFKD', str(s or '').strip().upper())
    x = ''.join(c for c in x if not unicodedata.combining(c))
    x = re.sub(r'\*?(ADV\d*|NC|OBT|MEL|COB)\b.*$', '', x).strip()
    x = re.sub(r'\((?:GER)?F0?[1-9]\)\s*$', '', x).strip()
    x = re.sub(r'[^A-Z0-9]+',' ',x)
    return re.sub(r'\s+',' ',x).strip()


def _filial_marker(desc):
    s = str(desc or '').upper()
    m = re.search(r'\((GER)?F0?([1-9])\)\s*$', s)
    if not m: return None, False
    f='F'+m.group(2)
    if f not in FILIAIS: return None, False
    return f, bool(m.group(1))


def _http_json(url, timeout=20):
    req=urllib.request.Request(url + ('&' if '?' in url else '?') + '_='+str(int(time.time())), headers={'User-Agent':'MDL-SGI-Vendedores-V10.127','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))


def _post_form(url, data, timeout=25):
    body=urllib.parse.urlencode({k:'' if v is None else str(v) for k,v in data.items()}).encode('utf-8')
    req=urllib.request.Request(url, data=body, headers={'User-Agent':'MDL-SGI-Vendedores-V10.127','Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))


def _telegram_token(): return os.getenv('TELEGRAM_BOT_TOKEN','').strip()


def _telegram_api(method, payload=None, timeout=20):
    tok=_telegram_token()
    if not tok: return {'ok':False,'description':'TELEGRAM_BOT_TOKEN ausente'}
    url=f'https://api.telegram.org/bot{tok}/{method}'
    body=urllib.parse.urlencode(payload or {}, doseq=True).encode('utf-8')
    req=urllib.request.Request(url, data=body, headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'MDL-SGI-Vendedores-V10.127'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))


def _telegram_config():
    try:
        cfg=_http_json(CONFIG_URL)
        if isinstance(cfg,dict) and isinstance(cfg.get('global'),dict):
            return cfg.get('global') or {}
        return cfg if isinstance(cfg,dict) else {}
    except Exception as e:
        print(f'⚠️ V10.127 config Telegram indisponível: {type(e).__name__}: {e}', flush=True)
        return {}


def _telegram_chat_ids():
    """Retorna APENAS os chats marcados para a lista diária de ativos SGI.

    Migração segura: enquanto o campo sgi_ativos ainda não foi salvo pela UI,
    seleciona somente o contato ativo cujo nome contenha MASTER. Não usa o
    TELEGRAM_CHAT_ID genérico para evitar duplicar a lista em outros grupos.
    """
    glob=_telegram_config()
    rows=[c for c in (glob.get('telegram_contacts') or []) if isinstance(c,dict) and c.get('ativo')]
    explicit=any('sgi_ativos' in c for c in rows)
    selected=[]
    if explicit:
        selected=[c for c in rows if bool(c.get('sgi_ativos'))]
    else:
        selected=[c for c in rows if 'MASTER' in _norm(c.get('nome') or '')]
    out=[]
    for c in selected:
        cid=str(c.get('chat_id') or '').strip()
        if cid and cid not in out:
            out.append(cid)
    return out

def _send_text(text, keyboard=None):
    results=[]
    for cid in _telegram_chat_ids():
        payload={'chat_id':cid,'text':text,'disable_web_page_preview':'true'}
        if keyboard:
            payload['reply_markup']=json.dumps({'inline_keyboard':keyboard}, ensure_ascii=False, separators=(',',':'))
        try: results.append((cid,_telegram_api('sendMessage',payload)))
        except Exception as e: results.append((cid,{'ok':False,'description':str(e)}))
    return results


def _sig(action, login, day):
    key=(_telegram_token() or 'mdl-v10123').encode('utf-8')
    msg=f'{action}|{login}|{day}'.encode('utf-8')
    return hmac.new(key,msg,hashlib.sha256).hexdigest()[:10]


def _callback_data(action, login, day):
    return f'sgiabs|{action}|{login}|{day}|{_sig(action,login,day)}'


def _verify_callback(data):
    p=str(data or '').split('|')
    if len(p)!=5 or p[0]!='sgiabs': return None
    _,action,login,day,sig=p
    if action not in ('y','n'): return None
    if not hmac.compare_digest(sig,_sig(action,login,day)): return None
    return action,login,day


def _make_driver():
    prof=tempfile.mkdtemp(prefix='sgi_vendedores_')
    opts=Options()
    opts.page_load_strategy='eager'
    opts.add_argument('--headless=new')
    for a in ['--no-sandbox','--disable-dev-shm-usage','--disable-gpu','--window-size=1920,1080','--disable-blink-features=AutomationControlled','--remote-debugging-port=0','--disable-extensions','--no-first-run','--no-default-browser-check','--ignore-certificate-errors']:
        opts.add_argument(a)
    opts.add_argument(f'--user-data-dir={prof}')
    chrome=os.getenv('CHROME_BIN') or os.getenv('GOOGLE_CHROME_BIN')
    if chrome and os.path.exists(chrome): opts.binary_location=chrome
    driver_path=os.getenv('CHROMEDRIVER_PATH') or os.getenv('CHROME_DRIVER')
    try:
        if driver_path and os.path.exists(driver_path):
            d=webdriver.Chrome(service=Service(driver_path), options=opts)
        else:
            d=webdriver.Chrome(options=opts)
        d.set_page_load_timeout(60)
        return d,prof
    except Exception:
        shutil.rmtree(prof,ignore_errors=True)
        raise


def _visible_enabled(el):
    try:
        if not el.is_displayed() or not el.is_enabled():
            return False
        typ=str(el.get_attribute('type') or '').strip().lower()
        if typ == 'hidden':
            return False
        size=el.size or {}
        return float(size.get('width') or 0) > 0 and float(size.get('height') or 0) > 0
    except Exception:
        return False


def _first_interactable(driver, selectors, timeout=30):
    deadline=time.time()+float(timeout)
    last_counts=[]
    while time.time() < deadline:
        for by,sel in selectors:
            try:
                els=driver.find_elements(by,sel)
            except Exception:
                els=[]
            if els:
                last_counts.append(f'{by}:{sel}={len(els)}')
            for el in els:
                if _visible_enabled(el):
                    return el
        time.sleep(.25)
    return None


def _fill_interactable(driver, el, value, label):
    err=[]
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center',inline:'nearest'});", el)
    except Exception:
        pass
    try:
        el.click()
    except Exception as e:
        err.append('click='+type(e).__name__)
    try:
        el.send_keys(Keys.CONTROL,'a')
        el.send_keys(Keys.DELETE)
        el.send_keys(value)
        return
    except Exception as e:
        err.append('keys='+type(e).__name__)
    try:
        driver.execute_script(
            "arguments[0].focus(); arguments[0].value=arguments[1]; "
            "arguments[0].dispatchEvent(new Event('input',{bubbles:true})); "
            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
            el, value
        )
        return
    except Exception as e:
        err.append('js='+type(e).__name__)
    raise RuntimeError(f'nao foi possivel preencher {label}: '+', '.join(err))



def _workplace_diag(driver):
    """Resumo curto da tela de local de trabalho, sem dados sensíveis."""
    try:
        buttons=[]
        for el in driver.find_elements(By.CSS_SELECTOR, 'button,input[type="submit"],input[type="button"]')[:20]:
            try:
                buttons.append({
                    'id': el.get_attribute('id') or '',
                    'name': el.get_attribute('name') or '',
                    'value': el.get_attribute('value') or '',
                    'text': (el.text or '').strip()[:80],
                    'displayed': bool(el.is_displayed()),
                    'enabled': bool(el.is_enabled()),
                })
            except Exception:
                pass
        selects=[]
        for el in driver.find_elements(By.TAG_NAME,'select')[:12]:
            try:
                sel=Select(el)
                selects.append({
                    'id':el.get_attribute('id') or '',
                    'name':el.get_attribute('name') or '',
                    'value':el.get_attribute('value') or '',
                    'options':[{'value':o.get_attribute('value') or '', 'text':(o.text or '').strip()[:80]} for o in sel.options[:12]],
                })
            except Exception:
                pass
        radios=[]
        for el in driver.find_elements(By.CSS_SELECTOR,'input[type="radio"]')[:20]:
            try:
                radios.append({
                    'id':el.get_attribute('id') or '',
                    'name':el.get_attribute('name') or '',
                    'value':el.get_attribute('value') or '',
                    'checked':bool(el.is_selected()),
                    'displayed':bool(el.is_displayed()),
                    'enabled':bool(el.is_enabled()),
                })
            except Exception:
                pass
        return {'url':str(driver.current_url or ''),'title':str(driver.title or ''),'buttons':buttons,'selects':selects,'radios':radios}
    except Exception as e:
        return {'url':str(getattr(driver,'current_url','') or ''),'error':type(e).__name__}


def _resolve_workplace(driver, timeout=35):
    """Conclui /login/informa_local_de_trabalho de forma tolerante.

    O SGI varia entre botão normal, botão encoberto por máscara e formulário com
    seleção de local. Primeiro respeita qualquer seleção já existente; só escolhe
    automaticamente uma opção quando nenhuma estiver selecionada.
    """
    deadline=time.time()+max(5,int(timeout))
    last_action='nenhuma'
    while time.time() < deadline:
        cur=str(driver.current_url or '')
        if 'informa_local_de_trabalho' not in cur:
            return True

        # Se existir select de local e estiver sem valor, escolhe a primeira opção válida.
        try:
            for el in driver.find_elements(By.TAG_NAME,'select'):
                try:
                    if not el.is_enabled():
                        continue
                    sel=Select(el)
                    current=str(el.get_attribute('value') or '').strip()
                    valid=[]
                    for opt in sel.options:
                        val=str(opt.get_attribute('value') or '').strip()
                        disabled=opt.get_attribute('disabled')
                        if val and disabled is None:
                            valid.append((val,(opt.text or '').strip()))
                    if not current and valid:
                        sel.select_by_value(valid[0][0])
                        driver.execute_script(
                            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));", el
                        )
                        last_action=f"select:{el.get_attribute('id') or el.get_attribute('name')}={valid[0][1]}"
                except Exception:
                    continue
        except Exception:
            pass

        # Se a tela usa radio e nenhum está marcado, escolhe o primeiro habilitado.
        try:
            radios=[r for r in driver.find_elements(By.CSS_SELECTOR,'input[type="radio"]') if r.is_enabled()]
            if radios and not any(r.is_selected() for r in radios):
                driver.execute_script('arguments[0].click();', radios[0])
                last_action=f"radio:{radios[0].get_attribute('value') or radios[0].get_attribute('id') or 'primeiro'}"
        except Exception:
            pass

        # Tenta o ID conhecido e depois botões por texto/tipo. JS evita overlay/máscara.
        candidates=[]
        selectors=[
            (By.ID,'botao_prosseguir_informa_local_trabalho'),
            (By.XPATH,"//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'prosseguir')]"),
            (By.XPATH,"//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'continuar')]"),
            (By.XPATH,"//button[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'entrar')]"),
            (By.CSS_SELECTOR,"button[type='submit']"),
            (By.CSS_SELECTOR,"input[type='submit']"),
        ]
        for by,sel in selectors:
            try:
                for el in driver.find_elements(by,sel):
                    if el not in candidates:
                        candidates.append(el)
            except Exception:
                pass
        for el in candidates:
            try:
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                driver.execute_script('arguments[0].click();', el)
                last_action='click:'+(el.get_attribute('id') or el.get_attribute('value') or (el.text or '').strip()[:40] or 'submit')
                time.sleep(1.2)
                if 'informa_local_de_trabalho' not in str(driver.current_url or ''):
                    print(f'✅ V10.127 local de trabalho confirmado | {last_action}', flush=True)
                    return True
            except Exception:
                continue

        # Último fallback: requestSubmit()/submit() do primeiro form da tela.
        try:
            forms=driver.find_elements(By.TAG_NAME,'form')
            if forms:
                driver.execute_script("if(arguments[0].requestSubmit){arguments[0].requestSubmit()}else{arguments[0].submit()}", forms[0])
                last_action='form.requestSubmit'
                time.sleep(1.2)
                if 'informa_local_de_trabalho' not in str(driver.current_url or ''):
                    print(f'✅ V10.127 local de trabalho confirmado | {last_action}', flush=True)
                    return True
        except Exception:
            pass
        time.sleep(.7)

    print('⚠️ V10.127 local de trabalho não concluído | '+json.dumps(_workplace_diag(driver),ensure_ascii=False)[:3500], flush=True)
    return False

def _login(driver):
    driver.get(URL)
    wait=WebDriverWait(driver,30)
    time.sleep(.8)

    # Se o SGI reaproveitar sessão, não exige login.
    try:
        if '/home' in str(driver.current_url or '') or driver.find_elements(By.ID,'barra_superior'):
            return
    except Exception:
        pass

    user_selectors=[
        (By.NAME,'usuario'),
        (By.ID,'usuario'),
        (By.CSS_SELECTOR,"input[name='usuario']"),
        (By.CSS_SELECTOR,"input[id='usuario']"),
        (By.XPATH,"//input[(contains(@name,'usuario') or contains(@id,'usuario')) and not(@type='hidden')]") ,
        (By.XPATH,"//input[@type='text' or @type='email']"),
    ]
    user=_first_interactable(driver,user_selectors,30)
    if user is None:
        raise RuntimeError(f'campo usuario SGI visível/interagível não encontrado | url={driver.current_url} | title={driver.title}')
    _fill_interactable(driver,user,LOGIN,'usuario SGI')

    pwd=_first_interactable(driver,[(By.CSS_SELECTOR,"input[type='password']"),(By.XPATH,"//input[@type='password']")],20)
    if pwd is None:
        raise RuntimeError(f'campo senha SGI visível/interagível não encontrado | url={driver.current_url} | title={driver.title}')
    _fill_interactable(driver,pwd,SENHA,'senha SGI')

    submitted=False
    for by,sel in [
        (By.CSS_SELECTOR,"button[type='submit']"),
        (By.CSS_SELECTOR,"input[type='submit']"),
        (By.XPATH,"//button[contains(.,'Entrar') or contains(.,'Login') or contains(.,'Acessar')]")
    ]:
        btn=_first_interactable(driver,[(by,sel)],2)
        if btn is not None:
            try:
                btn.click(); submitted=True; break
            except Exception:
                pass
    if not submitted:
        try:
            pwd.send_keys(Keys.ENTER)
        except Exception:
            driver.execute_script("arguments[0].form && arguments[0].form.submit();", pwd)

    # SGI pode exigir a confirmação do local de trabalho após autenticação.
    # Espera a navegação do POST e trata explicitamente essa etapa antes de /vendedores.
    try:
        WebDriverWait(driver,20).until(lambda d: ('informa_local_de_trabalho' in str(d.current_url or '')) or ('/home' in str(d.current_url or '')) or bool(d.find_elements(By.ID,'barra_superior')))
    except Exception:
        pass
    if 'informa_local_de_trabalho' in str(driver.current_url or ''):
        if not _resolve_workplace(driver,35):
            raise RuntimeError('login SGI autenticou, mas não concluiu local de trabalho | '+json.dumps(_workplace_diag(driver),ensure_ascii=False)[:2500])

    # Confirma autenticação acessando diretamente a tela que será usada.
    driver.get(URL+'/vendedores')
    if 'informa_local_de_trabalho' in str(driver.current_url or ''):
        if not _resolve_workplace(driver,25):
            raise RuntimeError('SGI redirecionou /vendedores para local de trabalho e não foi possível prosseguir | '+json.dumps(_workplace_diag(driver),ensure_ascii=False)[:2500])
        driver.get(URL+'/vendedores')
    try:
        WebDriverWait(driver,30).until(EC.presence_of_element_located((By.ID,'vendedores.descricao_ilike')))
    except Exception as e:
        raise RuntimeError(
            f'login SGI não confirmado após local de trabalho | url={driver.current_url} | title={driver.title} | {type(e).__name__}'
        )


def _collect_sgi_roster():
    driver,prof=_make_driver()
    try:
        _login(driver)
        out=[]
        for f in FILIAIS:
            driver.get(URL+'/vendedores')
            wait=WebDriverWait(driver,25)
            inp=wait.until(EC.presence_of_element_located((By.ID,'vendedores.descricao_ilike')))
            try:
                ativo=driver.find_element(By.ID,'ativo')
                Select(ativo).select_by_value('true')
            except Exception: pass
            _fill_interactable(driver,inp,f,f'filtro {f}')
            btn=driver.find_element(By.XPATH,"//button[@type='submit'][contains(.,'Filtrar')]")
            try:
                btn.click()
            except Exception:
                driver.execute_script('arguments[0].click();', btn)
            wait.until(EC.presence_of_element_located((By.ID,'lista_padrao_vendedor')))
            time.sleep(.8)
            rows=driver.find_elements(By.CSS_SELECTOR,'#lista_padrao_vendedor tbody tr')
            for tr in rows:
                try:
                    td_desc=tr.find_element(By.CSS_SELECTOR,'td.campo_descricao')
                    desc=(td_desc.get_attribute('data-value') or td_desc.text or '').strip()
                    ff,isg=_filial_marker(desc)
                    if ff!=f: continue
                    td_p=tr.find_element(By.CSS_SELECTOR,'td.campo_nome_pessoa')
                    pessoa=(td_p.get_attribute('data-value') or td_p.text or '').strip()
                    td_a=tr.find_element(By.CSS_SELECTOR,'td.campo__ativo')
                    ativo_txt=(td_a.get_attribute('data-value') or td_a.text or '').strip().lower()
                    if ativo_txt not in ('sim','true','1','ativo'): continue
                    nome=_norm(pessoa or desc)
                    href=''
                    try: href=td_desc.find_element(By.TAG_NAME,'a').get_attribute('href') or ''
                    except Exception: pass
                    out.append({'filial':ff,'is_gerente':isg,'tipo':'Gerente' if isg else 'Vendedor','descricao':desc,'pessoa':pessoa,'nome_norm':nome,'href':href,'ativo':True})
                except Exception:
                    continue
        # dedupe
        uniq={}
        for x in out: uniq[(x['nome_norm'],x['filial'],x['is_gerente'])]=x
        return list(uniq.values())
    finally:
        try: driver.quit()
        except Exception: pass
        shutil.rmtree(prof,ignore_errors=True)



def _display_name(x):
    # Prefere Pessoa; remove marcadores administrativos e mantém acentuação do nome.
    raw=str(x.get('pessoa') or x.get('descricao') or '').strip()
    raw=re.sub(r'\s+\*?(ADV\d*|NC|OBT|MEL|COB)\b.*$', '', raw, flags=re.I).strip()
    raw=re.sub(r'\s*\((?:GER)?F0?[1-9]\)\s*$', '', raw, flags=re.I).strip()
    return re.sub(r'\s+',' ',raw).strip() or str(x.get('nome_norm') or '').title()


def _format_roster(roster):
    order={f:i for i,f in enumerate(FILIAIS)}
    rows=sorted(roster, key=lambda x:(order.get(x.get('filial'),99), 0 if x.get('is_gerente') else 1, _norm(_display_name(x))))
    total_g=sum(1 for x in rows if x.get('is_gerente'))
    total_v=len(rows)-total_g
    parts=[
        '👥 VENDEDORES E GERENTES ATIVOS — SGI',
        f"📅 {now_br().strftime('%d/%m/%Y')} · consulta automática diária",
        '',
    ]
    for f in FILIAIS:
        fr=[x for x in rows if x.get('filial')==f]
        parts.append(f'📍 {f} — {len(fr)} ativo(s)')
        if not fr:
            parts.append('• — nenhum ativo com tag da filial')
        else:
            for x in fr:
                icon='👔' if x.get('is_gerente') else '🧑‍💼'
                parts.append(f"• {icon} {x.get('tipo')}: {_display_name(x)}")
        parts.append('')
    parts += [
        f'✅ TOTAL: {len(rows)} ativo(s) · {total_v} vendedor(es) · {total_g} gerente(s)',
        'Fonte: SGI → Cadastro de Vendedores → Ativo = Sim + tag (F#)/(GERF#).',
    ]
    return '\n'.join(parts).strip()


def _split_telegram(text, limit=3900):
    if len(text)<=limit:
        return [text]
    chunks=[]; cur=[]; n=0
    for line in text.splitlines():
        add=len(line)+1
        if cur and n+add>limit:
            chunks.append('\n'.join(cur)); cur=[]; n=0
        cur.append(line); n+=add
    if cur: chunks.append('\n'.join(cur))
    return chunks


def _send_roster(text):
    ids=_telegram_chat_ids()
    if not ids:
        print('⚠️ V10.127 lista SGI coletada, mas nenhum grupo Telegram está marcado em “Ativos SGI”.', flush=True)
        return []
    results=[]
    chunks=_split_telegram(text)
    for cid in ids:
        ok_all=True
        details=[]
        for i,ch in enumerate(chunks,1):
            payload={'chat_id':cid,'text':ch,'disable_web_page_preview':'true'}
            try:
                r=_telegram_api('sendMessage',payload)
            except Exception as e:
                r={'ok':False,'description':str(e)}
            details.append(r)
            ok_all=ok_all and bool(r.get('ok'))
        results.append((cid,{'ok':ok_all,'chunks':len(chunks),'details':details}))
    return results


def run_monitor():
    print(f'👥 V10.127 monitor SGI ativos iniciado | arquivo={__file__} | modo=LISTA_SGI_SEM_CONCILIACAO | destino=telegram_sgi_ativos', flush=True)
    roster=_collect_sgi_roster()
    roster=sorted(roster,key=lambda x:(FILIAIS.index(x['filial']) if x.get('filial') in FILIAIS else 99, 0 if x.get('is_gerente') else 1, x.get('nome_norm') or ''))
    print(f'✅ V10.127 SGI /vendedores: {len(roster)} ativo(s) com tag F#/GERF#', flush=True)
    for f in FILIAIS:
        fr=[x for x in roster if x.get('filial')==f]
        nomes=' | '.join(f"{x.get('tipo')}={_display_name(x)}" for x in fr) or 'nenhum'
        print(f'   ↳ {f}: {len(fr)} ativo(s) | {nomes}', flush=True)

    text=_format_roster(roster)
    sent=_send_roster(text)
    ok=sum(1 for _,r in sent if r.get('ok'))
    print(f'📲 V10.127 Telegram ativos SGI: destinos selecionados={len(sent)} | enviados_ok={ok}', flush=True)

    snap={
        'version':'V10.127',
        'generated_at':now_br().isoformat(),
        'modo':'lista_sgi_sem_conciliacao',
        'filiais':list(FILIAIS),
        'sgi_ativos':roster,
        'telegram_destinos':[cid for cid,_ in sent],
        'telegram_ok':ok,
        'texto':text,
    }
    with open(MONITOR_JSON,'w',encoding='utf-8') as f:
        json.dump(snap,f,ensure_ascii=False,indent=2)
    print(f'✅ V10.127 final: lista diária concluída | ativos={len(roster)} | destinos={len(sent)} | SEM comparação Dashboard/metas | SEM alteração de status', flush=True)
    return 0


def poll_telegram_callbacks_v10123(base_dir=None, offset=0):
    # Compatibilidade temporária com schedulers antigos: V10.127 não usa mais botões
    # de férias nem altera status de vendedor/gerente automaticamente.
    return {'offset':int(offset or 0),'processed':0,'force_main':False}


if __name__=='__main__':
    try:
        raise SystemExit(run_monitor())
    except Exception as e:
        print('❌ V10.127 monitor SGI ativos:',repr(e), flush=True)
        try:
            _send_roster('🚨 ERRO NA LISTA DIÁRIA DE VENDEDORES/GERENTES ATIVOS DO SGI\n\n'+str(e)[:1200])
        except Exception:
            pass
        raise
