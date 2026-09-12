# VERSAO: SGI_VENDEDORES_MONITOR_V10.126
# Auditoria diaria de vendedores/gerentes ativos no SGI + confirmacao de ferias via Telegram.
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
CRED_API = PUBLIC_BASE + '/credenciais_api.php'
METAS_URL = PUBLIC_BASE + '/metas_vendas_mes_atual.json'
CONFIG_URL = PUBLIC_BASE + '/config_meta.json'
MONITOR_JSON = os.path.join(BASE_DIR, 'sgi_vendedores_monitor.json')
FORCE_MAIN_FLAG = os.path.join(BASE_DIR, 'sgi_vendedores_force_main.flag')
FILIAIS = ('F1','F2','F3','F4','F5','F6','F8','F9')
MONITOR_BUILD = 'SGI_VENDEDORES_MONITOR_V10.126'
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
    req=urllib.request.Request(url + ('&' if '?' in url else '?') + '_='+str(int(time.time())), headers={'User-Agent':'MDL-SGI-Vendedores-V10.126','Cache-Control':'no-cache'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))


def _post_form(url, data, timeout=25):
    body=urllib.parse.urlencode({k:'' if v is None else str(v) for k,v in data.items()}).encode('utf-8')
    req=urllib.request.Request(url, data=body, headers={'User-Agent':'MDL-SGI-Vendedores-V10.126','Content-Type':'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))


def _telegram_token(): return os.getenv('TELEGRAM_BOT_TOKEN','').strip()


def _telegram_api(method, payload=None, timeout=20):
    tok=_telegram_token()
    if not tok: return {'ok':False,'description':'TELEGRAM_BOT_TOKEN ausente'}
    url=f'https://api.telegram.org/bot{tok}/{method}'
    body=urllib.parse.urlencode(payload or {}, doseq=True).encode('utf-8')
    req=urllib.request.Request(url, data=body, headers={'Content-Type':'application/x-www-form-urlencoded','User-Agent':'MDL-SGI-Vendedores-V10.126'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8','replace'))


def _telegram_chat_ids():
    out=[]
    try:
        cfg=_http_json(CONFIG_URL)
        glob=(cfg.get('global') if isinstance(cfg,dict) else {}) or {}
        for c in (glob.get('telegram_contacts') or []):
            if not isinstance(c,dict) or not c.get('ativo'): continue
            cid=str(c.get('chat_id') or '').strip()
            if cid and (c.get('avisos',True) or c.get('erros',True)):
                out.append(cid)
    except Exception:
        pass
    env=str(os.getenv('TELEGRAM_CHAT_ID','')).strip()
    if env and env not in out: out.append(env)
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
                    print(f'✅ V10.126 local de trabalho confirmado | {last_action}', flush=True)
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
                    print(f'✅ V10.126 local de trabalho confirmado | {last_action}', flush=True)
                    return True
        except Exception:
            pass
        time.sleep(.7)

    print('⚠️ V10.126 local de trabalho não concluído | '+json.dumps(_workplace_diag(driver),ensure_ascii=False)[:3500], flush=True)
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


def _load_creds():
    j=_http_json(CRED_API)
    return (j.get('data') if isinstance(j,dict) and isinstance(j.get('data'),dict) else j) or {}


def _load_meta_names():
    try: j=_http_json(METAS_URL)
    except Exception: return set(),False
    if isinstance(j,dict) and isinstance(j.get('dados'),dict): j=j['dados']
    metas=(j.get('metas') if isinstance(j,dict) else {}) or {}
    names=set()
    for key in ('venda_filial_vendedor_meta','servico_filial_vendedor_ouro_fob','venda_vendedor_subgrupo_20k'):
        obj=metas.get(key) or {}
        for r in (obj.get('linhas') or []):
            if not isinstance(r,dict): continue
            nm=r.get('Vendedor_2') or r.get('Vendedor 2') or r.get('Vendedor') or ''
            if nm: names.add(_norm(nm))
    return names,True


def _commercial_dashboard_users(creds):
    out=[]
    for login,u in (creds.get('users') or {}).items():
        if not isinstance(u,dict): continue
        f=str(u.get('filial') or '').upper().strip()
        if f not in FILIAIS: continue
        if u.get('is_terceiro') or u.get('is_crediarista') or u.get('is_cob_externa') or u.get('is_viewer'): continue
        nome=str(u.get('nome') or '').strip()
        if not nome: continue
        isg=bool(u.get('is_gerente'))
        out.append({'login':str(login).lower(),'nome':nome,'nome_norm':_norm(nome),'filial':f,'is_gerente':isg,'tipo':'Gerente' if isg else 'Vendedor','status':str(u.get('status_operacional') or 'ativo').lower(),'raw':u})
    return out


def _date_suppressed(u):
    s=str((u.get('raw') or {}).get('sgi_ausencia_nao_ferias_ate') or '').strip()
    if not s: return False
    try: return datetime.strptime(s[:10],'%Y-%m-%d').date() >= now_br().date()
    except Exception: return False


def _mark_prompt(login, motivo):
    return _post_form(CRED_API,{'action':'admin_sgi_absence','login':login,'decision':'prompt','motivo':motivo})


def _set_decision(login, decision):
    return _post_form(CRED_API,{'action':'admin_sgi_absence','login':login,'decision':decision})


def _touch_force_main(reason='status_sgi'):
    with open(FORCE_MAIN_FLAG,'w',encoding='utf-8') as f: f.write(reason+'\n'+now_br().isoformat())


def _send_question(u):
    day=now_br().strftime('%Y%m%d')
    text=(f"🏖️ POSSÍVEL FÉRIAS / AUSÊNCIA\n\n"
          f"{u['nome']} · {u['filial']} · {u['tipo']}\n"
          f"Está ATIVO no cadastro de vendedores do SGI, mas não apareceu nas metas/vendas do mês.\n\n"
          f"Esse colaborador está de férias/ausente?\n"
          f"Se SIM, o Dashboard retira das filas e redistribui a carteira automaticamente.")
    kb=[[{'text':'🏖️ SIM · Férias','callback_data':_callback_data('y',u['login'],day)},
         {'text':'✅ NÃO · Manter ativo','callback_data':_callback_data('n',u['login'],day)}]]
    res=_send_text(text,kb)
    if any(bool((r or {}).get('ok')) for _,r in res):
        _mark_prompt(u['login'],'Ativo no SGI, ausente das metas/vendas do mês')
        return True
    return False


def run_monitor():
    print(f'👥 V10.126 monitor SGI vendedores/gerentes iniciado | arquivo={__file__} | login_fix=interactable_no_clear | local_fix=robust_workplace', flush=True)
    roster=_collect_sgi_roster()
    print(f'✅ SGI /vendedores: {len(roster)} ativo(s) com tag F#/GERF#')
    creds=_load_creds(); dash=_commercial_dashboard_users(creds)
    metas,metas_ok=_load_meta_names()
    print(f"✅ Dashboard comercial: {len(dash)} usuário(s) | metas/vendas legíveis={metas_ok} | nomes em meta={len(metas)}")
    sgi_map={(x['nome_norm'],x['filial'],x['is_gerente']):x for x in roster}
    dash_map={(x['nome_norm'],x['filial'],x['is_gerente']):x for x in dash}
    sgi_only=[x for k,x in sgi_map.items() if k not in dash_map]
    dash_only=[x for k,x in dash_map.items() if k not in sgi_map and x['status']!='inativo']
    if sgi_only or dash_only:
        parts=['⚠️ AUDITORIA DIÁRIA SGI × DASHBOARD']
        if sgi_only:
            parts.append('\nATIVOS NO SGI SEM CORRESPONDENTE NO DASHBOARD:')
            parts += [f"• {x['nome_norm']} · {x['filial']} · {x['tipo']}" for x in sgi_only[:25]]
        if dash_only:
            parts.append('\nNO DASHBOARD, MAS SEM TAG ATIVA NO SGI:')
            parts += [f"• {x['nome']} · {x['filial']} · {x['tipo']} · status {x['status']}" for x in dash_only[:25]]
        parts.append('\nNenhuma alteração foi feita automaticamente por divergência de quadro.')
        _send_text('\n'.join(parts))
    # auto retorno: férias que voltaram a ter meta/venda
    reativados=[]
    for u in dash:
        # V10.124: ausência de venda/meta é sinal confiável somente para vendedor.
        # Gerente continua auditado pelo roster SGI (GERF#), mas não é inferido como férias por falta de venda.
        if u['is_gerente']:
            continue
        k=(u['nome_norm'],u['filial'],u['is_gerente'])
        if u['status']=='ferias' and k in sgi_map and metas_ok and u['nome_norm'] in metas:
            try:
                r=_set_decision(u['login'],'return')
                if r.get('ok'):
                    reativados.append(u); _touch_force_main('retorno_'+u['login'])
            except Exception as e: print('⚠️ retorno',u['login'],e)
    for u in reativados:
        _send_text(f"✅ RETORNO DETECTADO\n\n{u['nome']} · {u['filial']} voltou a aparecer nas metas/vendas do SGI.\nStatus alterado automaticamente de FÉRIAS para ATIVO e a carteira será recomposta.")
    # perguntas de possível férias: somente ativo + presente no SGI + sem meta/venda
    perguntas=[]
    if metas_ok:
        for u in dash:
            if u['status']!='ativo': continue
            # V10.124: não perguntar férias de gerente apenas por ausência em metas/vendas.
            if u['is_gerente']: continue
            k=(u['nome_norm'],u['filial'],u['is_gerente'])
            if k not in sgi_map: continue
            if u['nome_norm'] in metas: continue
            if _date_suppressed(u): continue
            asked=str((u.get('raw') or {}).get('sgi_ausencia_pergunta_em') or '')[:10]
            if asked==now_br().strftime('%Y-%m-%d'): continue
            if _send_question(u): perguntas.append(u)
            time.sleep(.25)
    snap={'version':'V10.126','generated_at':now_br().isoformat(),'sgi_ativos':roster,'dashboard':[{k:v for k,v in u.items() if k!='raw'} for u in dash], 'sgi_only':sgi_only,'dashboard_only':[{k:v for k,v in u.items() if k!='raw'} for u in dash_only], 'meta_names':sorted(metas), 'perguntas_ferias':[u['login'] for u in perguntas], 'reativados':[u['login'] for u in reativados]}
    with open(MONITOR_JSON,'w',encoding='utf-8') as f: json.dump(snap,f,ensure_ascii=False,indent=2)
    print(f"✅ V10.126 final: divergências SGI→Dash={len(sgi_only)} Dash→SGI={len(dash_only)} | perguntas férias={len(perguntas)} | retornos={len(reativados)}")
    return 0


def poll_telegram_callbacks_v10123(base_dir=None, offset=0):
    tok=_telegram_token()
    if not tok: return {'offset':int(offset or 0),'processed':0,'force_main':False}
    payload={'offset':str(int(offset or 0)),'timeout':'0','allowed_updates':json.dumps(['callback_query'])}
    try: j=_telegram_api('getUpdates',payload,timeout=8)
    except Exception as e: return {'offset':int(offset or 0),'processed':0,'force_main':False,'error':str(e)}
    if not j.get('ok'): return {'offset':int(offset or 0),'processed':0,'force_main':False,'error':j.get('description')}
    newoff=int(offset or 0); processed=0; force=False
    for upd in (j.get('result') or []):
        uid=int(upd.get('update_id') or 0); newoff=max(newoff,uid+1)
        cq=upd.get('callback_query') or {}; parsed=_verify_callback(cq.get('data'))
        if not parsed: continue
        action,login,day=parsed
        # aceita até 7 dias, evitando botão muito antigo
        try:
            d=datetime.strptime(day,'%Y%m%d').date()
            if abs((now_br().date()-d).days)>7: continue
        except Exception: continue
        decision='yes' if action=='y' else 'no'
        try:
            r=_set_decision(login,decision)
            ok=bool(r.get('ok'))
        except Exception as e:
            ok=False; r={'error':str(e)}
        ans='Status atualizado.' if ok else ('Falha: '+str(r.get('error') or 'erro'))
        try: _telegram_api('answerCallbackQuery',{'callback_query_id':cq.get('id'),'text':ans,'show_alert':'false'})
        except Exception: pass
        if ok:
            processed+=1
            user=cq.get('from') or {}; who=(user.get('username') and '@'+user['username']) or user.get('first_name') or 'Telegram'
            status='🏖️ FÉRIAS' if action=='y' else '✅ ATIVO'
            oldmsg=(cq.get('message') or {}).get('text') or ''
            final=oldmsg+f"\n\nResposta: {status} · confirmado por {who} em {now_br().strftime('%d/%m/%Y %H:%M')}"
            try:
                msg=cq.get('message') or {}
                _telegram_api('editMessageText',{'chat_id':msg.get('chat',{}).get('id'),'message_id':msg.get('message_id'),'text':final,'disable_web_page_preview':'true'})
            except Exception: pass
            if action=='y':
                force=True; _touch_force_main('ferias_'+login)
    return {'offset':newoff,'processed':processed,'force_main':force}


if __name__=='__main__':
    try: raise SystemExit(run_monitor())
    except Exception as e:
        print('❌ V10.126 monitor SGI vendedores:',repr(e), flush=True)
        try: _send_text('🚨 ERRO MONITOR SGI VENDEDORES\n'+str(e)[:1200])
        except Exception: pass
        raise
