# VERSAO: WHATSAPP_MASTER_PREVENTIVA_V1_DRY_RUN
# MDL COB+VENDAS -> WhatsApp Master
# Regras: D-5, D-1, D0, D+1, D+3, D+7, D+10, D+14. D+15+ bloqueia automatico.

import os, re, json, time, urllib.request, urllib.error
from pathlib import Path
from datetime import datetime, date
from zoneinfo import ZoneInfo

try:
    import pandas as pd
except Exception:
    pd = None

APP_TZ = ZoneInfo(os.getenv('APP_TZ', 'America/Sao_Paulo'))
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / 'monitor_logs'
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / 'whatsapp_master_preventiva.log'
PREVIEW_PATH = BASE_DIR / 'whatsapp_master_preventiva_preview.json'
STATE_PATH = BASE_DIR / 'whatsapp_master_preventiva_enviados.json'

MARCOS = {-5:'D-5', -1:'D-1', 0:'D0', 1:'D+1', 3:'D+3', 7:'D+7', 10:'D+10', 14:'D+14'}

ENABLED = os.getenv('WHATSAPP_MASTER_PREVENTIVA_ENABLED', '0') == '1'
DRY_RUN = os.getenv('WHATSAPP_MASTER_PREVENTIVA_DRY_RUN', '1') != '0'
ONLY_PHONES = {re.sub(r'\D+', '', x) for x in os.getenv('WHATSAPP_MASTER_PREVENTIVA_ALLOWED_PHONES', '').split(',') if x.strip()}
WHATSAPP_BASE = os.getenv('WHATSAPP_MASTER_BASE_URL', os.getenv('MDL_WHATSAPP_MASTER_BASE_URL', 'https://mdl-whatsapp-ia-f1-piloto-production.up.railway.app')).rstrip('/')
WHATSAPP_TOKEN = os.getenv('WHATSAPP_MASTER_INTERNAL_TOKEN', os.getenv('INTERNAL_API_TOKEN', '')).strip()
SEND_ENDPOINT = os.getenv('WHATSAPP_MASTER_SEND_ENDPOINT', '/api/internal/interacoes/enviar')


def now_br(): return datetime.now(APP_TZ)
def hoje_br(): return now_br().date()

def log(msg):
    line = f"[{now_br().isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def norm_key(s):
    import unicodedata
    s = unicodedata.normalize('NFD', str(s or '')).encode('ascii','ignore').decode('ascii')
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')

def pick_col(cols, names):
    ncols = {norm_key(c): c for c in cols}
    for n in names:
        if n in ncols: return ncols[n]
    for nk, orig in ncols.items():
        if any(n in nk for n in names): return orig
    return None

def norm_doc(v): return re.sub(r'\D+', '', str(v or ''))

def norm_phone(v):
    d = re.sub(r'\D+', '', str(v or ''))
    if not d: return ''
    if d.startswith('55') and len(d) in (12,13): return d
    if len(d) in (10,11): return '55' + d
    return d

def parse_money(v):
    if v is None: return 0.0
    s = str(v).strip()
    if not s: return 0.0
    s = s.replace('R$', '').replace(' ', '')
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try: return float(s)
    except Exception: return 0.0

def parse_date(v):
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    s = str(v or '').strip()
    if not s: return None
    for fmt in ('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y','%d/%m/%y'):
        try: return datetime.strptime(s[:10], fmt).date()
        except Exception: pass
    if pd is not None:
        try:
            x = pd.to_datetime(s, dayfirst=True, errors='coerce')
            if not pd.isna(x): return x.date()
        except Exception: pass
    return None

def find_input_file():
    env = os.getenv('WHATSAPP_MASTER_PREVENTIVA_INPUT_FILE', '').strip()
    if env and Path(env).exists(): return Path(env)
    pats = ['*contas*receber*.xls*', '*relatorio*contas*.xls*', '*preventiva*.xls*', '*preventiva*.csv']
    found = []
    for pat in pats:
        found += [p for p in BASE_DIR.glob(pat) if 'quitados' not in p.name.lower()]
    if not found: return None
    return max(found, key=lambda p: p.stat().st_mtime)

def read_rows(path):
    if pd is None:
        raise RuntimeError('pandas não disponível no ambiente')
    if path.suffix.lower() == '.csv':
        df = pd.read_csv(path, dtype=str, sep=None, engine='python')
    else:
        df = pd.read_excel(path, dtype=str)
    cols = list(df.columns)
    c_doc = pick_col(cols, ['cpf_cnpj','cpfcnpj','cpf','cnpj','documento'])
    c_cliente = pick_col(cols, ['cliente','nome','nome_cliente','razao_social'])
    c_tel = pick_col(cols, ['telefone','celular','fone','whatsapp','contato'])
    c_venc = pick_col(cols, ['vencimento','data_vencimento','dt_vencimento','vencto'])
    c_valor = pick_col(cols, ['valor','valor_titulo','nominal','valor_nominal','pendente'])
    c_titulo = pick_col(cols, ['titulo','numero_titulo','documento_titulo','duplicata','lancamento','lancto'])
    c_parcela = pick_col(cols, ['parcela','prestacao','nparcela'])
    c_filial = pick_col(cols, ['filial','loja','empresa'])
    missing = [n for n,c in [('cpf/cnpj',c_doc),('cliente',c_cliente),('vencimento',c_venc)] if not c]
    if missing:
        raise RuntimeError('Colunas obrigatórias não encontradas: ' + ', '.join(missing) + f'. Colunas: {cols}')
    rows=[]
    for _, r in df.iterrows():
        venc = parse_date(r.get(c_venc))
        doc = norm_doc(r.get(c_doc))
        if not doc or not venc: continue
        rows.append({
            'cpf_cnpj': doc,
            'cliente': str(r.get(c_cliente) or '').strip(),
            'telefone': norm_phone(r.get(c_tel)) if c_tel else '',
            'vencimento': venc.isoformat(),
            'dias': (hoje_br() - venc).days,
            'valor': parse_money(r.get(c_valor)) if c_valor else 0.0,
            'titulo': str(r.get(c_titulo) or '').strip() if c_titulo else '',
            'parcela': str(r.get(c_parcela) or '').strip() if c_parcela else '',
            'filial': str(r.get(c_filial) or '').strip() if c_filial else '',
        })
    return rows

def primeiro_nome(nome):
    parts = re.sub(r'\s+',' ',str(nome or '').strip()).split(' ')
    return parts[0].title() if parts else 'cliente'

def marco_label(dias): return MARCOS.get(int(dias))

def money_br(v):
    return ('R$ %.2f' % float(v or 0)).replace('.', ',')

def montar_msg(row):
    d = int(row['dias']); marco = marco_label(d); nome = primeiro_nome(row.get('cliente'))
    valor = money_br(row.get('valor')) if row.get('valor') else 'o valor da parcela'
    venc = datetime.strptime(row['vencimento'], '%Y-%m-%d').strftime('%d/%m/%Y')
    if d < 0:
        return f"Olá, {nome}! Passando para lembrar que você tem uma parcela da LOJAS MDL / Móveis do Lar com vencimento em {venc}. Valor: {valor}. Qualquer dúvida, responda esta mensagem."
    if d == 0:
        return f"Olá, {nome}! Sua parcela da LOJAS MDL / Móveis do Lar vence hoje ({venc}). Valor: {valor}. Se já pagou, desconsidere."
    if d <= 3:
        return f"Olá, {nome}! Identificamos uma parcela da LOJAS MDL / Móveis do Lar vencida desde {venc}. Valor: {valor}. Podemos te ajudar a regularizar?"
    if d <= 10:
        return f"Olá, {nome}! Consta uma parcela em aberto na LOJAS MDL / Móveis do Lar vencida em {venc}. Valor: {valor}. Responda esta mensagem para receber atendimento."
    return f"Olá, {nome}! Este é um aviso da LOJAS MDL / Móveis do Lar sobre parcela em aberto vencida em {venc}. Valor: {valor}. Para evitar encaminhamento à cobrança humana, responda esta mensagem."

def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {'sent': {}}

def save_state(st):
    STATE_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding='utf-8')

def send_message(phone, text, ref):
    if not WHATSAPP_TOKEN:
        return False, 'WHATSAPP_MASTER_INTERNAL_TOKEN/INTERNAL_API_TOKEN não configurado'
    payload = {'telefone': phone, 'mensagem': text, 'texto': text, 'origem': 'cobranca_preventiva_mdl', 'referencia': ref}
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(WHATSAPP_BASE + SEND_ENDPOINT, data=data, method='POST')
    req.add_header('Authorization', 'Bearer ' + WHATSAPP_TOKEN)
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = resp.read().decode('utf-8', errors='replace')
            return 200 <= resp.status < 300, body[:1000]
    except urllib.error.HTTPError as e:
        return False, e.read().decode('utf-8', errors='replace')[:1000]
    except Exception as e:
        return False, str(e)

def main():
    log('🚀 Iniciando WhatsApp Master Preventiva/Cobrança V1')
    log(f'Config: ENABLED={ENABLED} DRY_RUN={DRY_RUN} MARCOS={list(MARCOS.values())}')
    path = find_input_file()
    if not path:
        out = {'ok': False, 'erro': 'Nenhum arquivo de entrada encontrado. Configure WHATSAPP_MASTER_PREVENTIVA_INPUT_FILE ou coloque XLS/CSV contas_receber/preventiva na pasta.', 'gerado_em': now_br().isoformat()}
        PREVIEW_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        log('⚠️ ' + out['erro'])
        return 0
    log(f'📄 Arquivo de entrada: {path.name}')
    rows = read_rows(path)
    by_doc = {}
    for r in rows:
        by_doc.setdefault(r['cpf_cnpj'], []).append(r)
    blocked_docs = {doc for doc, arr in by_doc.items() if any(int(x['dias']) >= 15 for x in arr)}
    st = load_state(); sent = st.setdefault('sent', {})
    candidates=[]; skipped=[]; sent_now=[]; errors=[]
    for r in rows:
        d = int(r['dias']); marco = marco_label(d)
        if not marco: continue
        key = '|'.join([r['cpf_cnpj'], r.get('titulo',''), r.get('parcela',''), r['vencimento'], marco])
        if r['cpf_cnpj'] in blocked_docs:
            skipped.append({**r, 'marco': marco, 'motivo': 'bloqueado_d15_ou_mais_no_cpf'}); continue
        if key in sent:
            skipped.append({**r, 'marco': marco, 'motivo': 'ja_enviado'}); continue
        if not r.get('telefone'):
            skipped.append({**r, 'marco': marco, 'motivo': 'sem_telefone'}); continue
        if ONLY_PHONES and r['telefone'] not in ONLY_PHONES:
            skipped.append({**r, 'marco': marco, 'motivo': 'fora_piloto_allowed_phones'}); continue
        item = {**r, 'marco': marco, 'dedupe_key': key, 'mensagem': montar_msg(r)}
        candidates.append(item)
        if ENABLED and not DRY_RUN:
            ok, resp = send_message(r['telefone'], item['mensagem'], key)
            if ok:
                sent[key] = {'quando': now_br().isoformat(), 'telefone': r['telefone'], 'marco': marco, 'resp': resp[:500]}
                sent_now.append(item)
                time.sleep(float(os.getenv('WHATSAPP_MASTER_PREVENTIVA_SEND_GAP_SECONDS','2')))
            else:
                errors.append({**item, 'erro': resp})
    save_state(st)
    out = {
        'ok': True, 'gerado_em': now_br().isoformat(), 'arquivo': path.name,
        'enabled': ENABLED, 'dry_run': DRY_RUN, 'marcos': list(MARCOS.values()),
        'total_linhas_lidas': len(rows), 'total_cpfs': len(by_doc), 'cpfs_bloqueados_d15_mais': len(blocked_docs),
        'candidatos': len(candidates), 'enviados_agora': len(sent_now), 'pulados': len(skipped), 'erros': len(errors),
        'preview': candidates[:500], 'skipped_amostra': skipped[:300], 'errors': errors[:100]
    }
    PREVIEW_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    log(f"✅ Finalizado | candidatos={len(candidates)} enviados={len(sent_now)} pulados={len(skipped)} erros={len(errors)} preview={PREVIEW_PATH.name}")
    return 0 if not errors else 2

if __name__ == '__main__':
    raise SystemExit(main())
