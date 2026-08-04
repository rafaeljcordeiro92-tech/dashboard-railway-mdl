#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V10.39 - Rateio proporcional por data de entrada de cobrança.
Uso: python aplicar_v10_39_rateio_data_entrada.py dashboard_railway_main_headless.py
"""
from __future__ import annotations
import argparse, re, shutil
from pathlib import Path

MARKER = "V10.39: rateio proporcional por data_entrada"

PY_RATEIO_BLOCK = r'''
# =========================================
# V10.39 — RATEIO PROPORCIONAL POR DATA DE ENTRADA DE COBRANÇA
# Vazio = mantém peso 100% e não mexe no rateio atual.
# Data no mês atual = peso proporcional aos dias ativos no mês.
# Mês anterior = peso 100%.
# =========================================
try:
    import calendar as _cal_v1039
    from datetime import date as _date_v1039, datetime as _dt_v1039
    import urllib.request as _urlreq_v1039
    import unicodedata as _ud_v1039

    def _v1039_norm_key(v):
        s = str(v or "").strip().upper()
        s = _ud_v1039.normalize("NFKD", s)
        s = "".join(ch for ch in s if not _ud_v1039.combining(ch))
        s = re.sub(r"[^A-Z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()

    def _v1039_parse_date(v):
        s = str(v or "").strip()
        if not s: return None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try: return _dt_v1039.strptime(s[:10], fmt).date()
            except Exception: pass
        try: return _dt_v1039.fromisoformat(s[:10]).date()
        except Exception: return None

    def _v1039_period_month():
        for _var in ("data_fim", "DATA_FIM", "fim_mes", "data_final"):
            try:
                d = _v1039_parse_date(globals().get(_var))
                if d: return d.year, d.month
            except Exception: pass
        try: return now_brasilia().year, now_brasilia().month
        except Exception: return _date_v1039.today().year, _date_v1039.today().month

    def _v1039_load_cred_state():
        data = {}
        try:
            _path = os.path.join(pasta, "credenciais_dashboard.json")
            if os.path.exists(_path):
                with open(_path, "r", encoding="utf-8") as f: data = json.load(f)
        except Exception: data = {}
        try:
            if not isinstance(data, dict) or not data.get("users"):
                url = "https://moveisdolar.com.br/colaborador/credenciais_dashboard.json?_v=1039"
                with _urlreq_v1039.urlopen(url, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        except Exception: pass
        return data if isinstance(data, dict) else {}

    def _v1039_data_entrada_maps():
        state = _v1039_load_cred_state()
        users = state.get("users") if isinstance(state.get("users"), dict) else {}
        colabs = state.get("colaborador_status") if isinstance(state.get("colaborador_status"), dict) else {}
        by_login, by_nome_filial = {}, {}
        def add(login, nome, filial, data):
            data = str(data or "").strip()
            if not data: return
            fil = str(filial or "").strip().upper()
            if fil and not fil.startswith("F"):
                m = re.search(r"(\d{1,2})", fil)
                fil = f"F{int(m.group(1))}" if m else fil
            if login:
                by_login[_v1039_norm_key(login)] = data
                if fil: by_login[_v1039_norm_key(f"{login}_{fil}")] = data
            if nome and fil:
                by_nome_filial[(_v1039_norm_key(nome), fil)] = data
        for login, u in users.items():
            if isinstance(u, dict):
                add(login or u.get("login"), u.get("nome") or login, u.get("filial"), u.get("data_entrada") or u.get("data_entrada_cobranca"))
        for k, st in colabs.items():
            if isinstance(st, dict):
                parts = str(k or "").split("|")
                add(st.get("login"), st.get("nome") or (parts[0] if parts else ""), st.get("filial") or (parts[1] if len(parts)>1 else ""), st.get("data_entrada") or st.get("data_entrada_cobranca"))
        return by_login, by_nome_filial

    def _v1039_entry_date_for_row(row, by_login, by_nome_filial):
        nome = row.get("vendedor") if hasattr(row, "get") else row["vendedor"]
        filial = str(row.get("filial_vendedor") if hasattr(row, "get") else row["filial_vendedor"]).strip().upper()
        keys = [_v1039_norm_key(str(nome or "")), _v1039_norm_key(f"{nome}_{filial}")]
        for k in ("login", "usuario", "user"):
            try:
                if k in row and str(row[k] or "").strip():
                    login = str(row[k] or "").strip()
                    keys += [_v1039_norm_key(login), _v1039_norm_key(f"{login}_{filial}")]
            except Exception: pass
        for k in keys:
            if k in by_login: return _v1039_parse_date(by_login[k])
        return _v1039_parse_date(by_nome_filial.get((_v1039_norm_key(nome), filial)))

    def _v1039_weight(data_entrada, ano, mes):
        if not data_entrada: return 1.0
        first = _date_v1039(ano, mes, 1)
        last_day = _cal_v1039.monthrange(ano, mes)[1]
        last = _date_v1039(ano, mes, last_day)
        if data_entrada <= first: return 1.0
        if data_entrada > last: return 0.0
        return max(0.0, min(1.0, ((last - data_entrada).days + 1) / float(last_day)))

    _by_login_v1039, _by_nome_filial_v1039 = _v1039_data_entrada_maps()
    _ano_v1039, _mes_v1039 = _v1039_period_month()
    _ajustes_v1039 = []
    for _fil_v1039 in sorted(set(str(x) for x in df_vend.get("filial_vendedor", []).dropna().tolist())):
        _mask_v1039 = (df_vend["filial_vendedor"].astype(str).str.upper() == _fil_v1039.upper()) & (~df_vend["is_gerente"].astype(bool))
        _idxs_v1039 = list(df_vend[_mask_v1039].index)
        if len(_idxs_v1039) <= 1: continue
        _tot_p_v1039 = round(float(df_vend.loc[_idxs_v1039, "pendente"].astype(float).sum()), 2)
        _tot_pg_v1039 = round(float(df_vend.loc[_idxs_v1039, "pago"].astype(float).sum()), 2)
        if abs(_tot_p_v1039) < 0.01 and abs(_tot_pg_v1039) < 0.01: continue
        _weights_v1039, _datas_v1039 = [], []
        for _idx_v1039 in _idxs_v1039:
            _row_v1039 = df_vend.loc[_idx_v1039]
            _dt_ent_v1039 = _v1039_entry_date_for_row(_row_v1039, _by_login_v1039, _by_nome_filial_v1039)
            _weights_v1039.append(float(_v1039_weight(_dt_ent_v1039, _ano_v1039, _mes_v1039)))
            _datas_v1039.append(_dt_ent_v1039)
        if not any(d is not None for d in _datas_v1039): continue
        if sum(_weights_v1039) <= 0: _weights_v1039 = [1.0 for _ in _idxs_v1039]
        _sum_w_v1039 = sum(_weights_v1039)
        if _sum_w_v1039 <= 0: continue
        for _idx_v1039, _w_v1039 in zip(_idxs_v1039, _weights_v1039):
            df_vend.loc[_idx_v1039, "pendente"] = round(_tot_p_v1039 * (_w_v1039 / _sum_w_v1039), 2)
            df_vend.loc[_idx_v1039, "pago"] = round(_tot_pg_v1039 * (_w_v1039 / _sum_w_v1039), 2)
        _last_v1039 = _idxs_v1039[-1]
        df_vend.loc[_last_v1039, "pendente"] += round(_tot_p_v1039 - float(df_vend.loc[_idxs_v1039, "pendente"].astype(float).sum()), 2)
        df_vend.loc[_last_v1039, "pago"] += round(_tot_pg_v1039 - float(df_vend.loc[_idxs_v1039, "pago"].astype(float).sum()), 2)
        _nomes_v1039 = []
        for _idx_v1039, _w_v1039, _dt_ent_v1039 in zip(_idxs_v1039, _weights_v1039, _datas_v1039):
            _nomes_v1039.append(f"{df_vend.loc[_idx_v1039, 'vendedor']}={_w_v1039:.2f}" + (f" entrada={_dt_ent_v1039}" if _dt_ent_v1039 else ""))
        _ajustes_v1039.append(f"{_fil_v1039}: " + "; ".join(_nomes_v1039))
    if _ajustes_v1039:
        print("✅ V10.39 rateio proporcional por data_entrada aplicado:")
        for _l_v1039 in _ajustes_v1039: print("   - " + _l_v1039)
    else:
        print("ℹ️ V10.39 rateio proporcional: nenhuma data_entrada no mês atual; rateio antigo preservado.")
except Exception as _e_v1039:
    print(f"⚠️ V10.39 rateio proporcional por data_entrada falhou; mantendo rateio atual: {_e_v1039}")
'''

JS_HELPER = r'''
<script>
// ===== V10.39: salvar data entrada cobrança =====
async function adminSalvarEntradaCobrancaV1039(login){
  try{
    const dom = (typeof _senhaDomKey === 'function') ? _senhaDomKey(login) : String(login||'').replace(/[^a-zA-Z0-9_-]/g,'_');
    const entrada = document.getElementById(`colab_entrada_${dom}`)?.value || '';
    const fd = new FormData();
    fd.append('action','admin_update_user_entry_date');
    fd.append('login', login);
    fd.append('data_entrada', entrada);
    const r = await fetch(API_CRED,{method:'POST',body:fd});
    const j = await r.json();
    return !!j.ok;
  }catch(e){console.warn('V10.39 entrada cobrança não salva pela API', e); return false;}
}
</script>
'''

PHP_ACTION = r'''
if ($action === 'admin_update_user_entry_date') {
  ensure_colab_status($data);
  $login = strtolower(trim((string)($_POST['login'] ?? '')));
  $entrada = trim((string)($_POST['data_entrada'] ?? ''));
  if (!$login) { echo json_encode(['ok'=>false,'error'=>'login_obrigatorio']); exit; }
  $ref = resolve_login_ref($data, $login);
  if (!$ref || $ref['type'] !== 'user') { echo json_encode(['ok'=>false,'error'=>'login_nao_encontrado']); exit; }
  $key = $ref['key'];
  if (!isset($data['users'][$key]) || !is_array($data['users'][$key])) { echo json_encode(['ok'=>false,'error'=>'usuario_invalido']); exit; }
  $data['users'][$key]['data_entrada'] = $entrada;
  $data['users'][$key]['data_entrada_cobranca'] = $entrada;
  $u = $data['users'][$key];
  $nome = $u['nome'] ?? $login; $filial = $u['filial'] ?? ''; $isGer = !empty($u['is_gerente']);
  $ck = colab_status_key($nome, $filial, $isGer);
  if (!isset($data['colaborador_status'][$ck]) || !is_array($data['colaborador_status'][$ck])) {
    $data['colaborador_status'][$ck] = ['login'=>$login, 'nome'=>$nome, 'filial'=>$filial, 'tipo'=>$isGer ? 'Gerente' : 'Vendedor', 'status'=>'ativo', 'participa_cobrancas'=>true, 'participa_sem_movimento'=>true, 'participa_aniversariantes'=>true, 'participa_murais'=>true, 'data_saida'=>'', 'substituto'=>'', 'obs'=>''];
  }
  $data['colaborador_status'][$ck]['data_entrada'] = $entrada;
  $data['colaborador_status'][$ck]['data_entrada_cobranca'] = $entrada;
  save_all($file, $data); echo json_encode(['ok'=>true], JSON_UNESCAPED_UNICODE); exit;
}
'''

def replace_once(text, old, new, label, required=False):
    if old in text:
        return text.replace(old, new, 1), True
    if required:
        raise RuntimeError(f"Não encontrei trecho obrigatório: {label}")
    print(f"⚠️ Não encontrei trecho para patch: {label}")
    return text, False

def patch_file(path: Path):
    text = path.read_text(encoding='utf-8', errors='ignore')
    original = text
    if MARKER not in text:
        marker = 'df_vend["total"] = df_vend["pendente"].astype(float) + df_vend["pago"].astype(float)'
        if marker not in text:
            marker = "df_vend['total'] = df_vend['pendente'].astype(float) + df_vend['pago'].astype(float)"
        if marker not in text:
            raise RuntimeError('Não encontrei ponto de inserção df_vend[total]; parei para não quebrar o arquivo.')
        text = text.replace(marker, PY_RATEIO_BLOCK + '\n' + marker, 1)

        text, _ = replace_once(text, '<th>Data saída</th>', '<th>Data entrada cobrança</th><th>Data saída</th>', 'header Data saída')
        text, _ = replace_once(text, '<th>Saída</th>', '<th>Data entrada cobrança</th><th>Saída</th>', 'header Saída')
        saida = '<td><input id="colab_saida_${dom}" type="date" value="${esc(u.data_saida||\'\')}" style="min-width:130px"></td>'
        entrada = '<td><input id="colab_entrada_${dom}" type="date" value="${esc(u.data_entrada||u.data_entrada_cobranca||\'\')}" style="min-width:130px"><div class="small muted">vazio = normal</div></td>'
        text, ok = replace_once(text, saida, entrada + saida, 'célula data saída')
        if not ok:
            pat = r'(<td>\s*<input id="colab_saida_\$\{dom\}" type="date" value="\$\{esc\(u\.data_saida\|\|\'\'\)\}" style="min-width:130px"\s*>\s*</td>)'
            text2, n = re.subn(pat, entrada + r'\1', text, count=1, flags=re.S)
            text = text2
            if not n: print('⚠️ Não consegui inserir campo visual de data entrada por regex.')

        old = "fd.append('data_saida',document.getElementById(`colab_saida_${dom}`)?.value||'');"
        new = "fd.append('data_entrada',document.getElementById(`colab_entrada_${dom}`)?.value||'');\n  " + old
        text, _ = replace_once(text, old, new, 'fd.append data_saida')
        text, _ = replace_once(text, "u.data_saida=fd.get('data_saida');", "u.data_entrada=fd.get('data_entrada'); u.data_entrada_cobranca=fd.get('data_entrada'); u.data_saida=fd.get('data_saida');", 'fallback local')
        text, _ = replace_once(text, "if(j.ok){ if(msg) msg.textContent='✅ Salvo online. Rode o dashboard novamente para recalcular rateio/listas.';", "if(j.ok){ await adminSalvarEntradaCobrancaV1039(login); if(msg) msg.textContent='✅ Salvo online. Rode o dashboard novamente para recalcular rateio/listas.';", 'chamada API extra')

        if 'adminSalvarEntradaCobrancaV1039' not in text:
            text = text.replace('</body>', JS_HELPER + '\n</body>', 1) if '</body>' in text else text + '\n' + JS_HELPER
        if 'admin_update_user_entry_date' not in text:
            anchor = "if ($action === 'resolve_reset') {"
            if anchor in text:
                text = text.replace(anchor, PHP_ACTION + '\n' + anchor, 1)
            else:
                print('⚠️ Não encontrei resolve_reset para inserir action PHP admin_update_user_entry_date.')

    text = re.sub(r'DASHBOARD_BUILD_VERSION\s*=\s*[\'\"]V10\.\d+[\'\"]', 'DASHBOARD_BUILD_VERSION = "V10.39"', text, count=1)
    text = re.sub(r'DASHBOARD_BUILD_TAG\s*=\s*[\'\"][^\'\"]*[\'\"]', 'DASHBOARD_BUILD_TAG = "rateio_data_entrada"', text, count=1)
    if 'V10.39' not in text:
        text = re.sub(r'V10\.\d+', 'V10.39', text, count=1)
    if text != original:
        path.write_text(text, encoding='utf-8', newline='')
        print(f'✅ Arquivo atualizado: {path}')
    else:
        print('ℹ️ Nenhuma alteração nova foi necessária.')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('arquivo', nargs='?', default='dashboard_railway_main_headless.py')
    args = ap.parse_args()
    target = Path(args.arquivo).resolve()
    if not target.exists():
        raise SystemExit(f'Arquivo não encontrado: {target}')
    backup = target.with_name('BACKUP_dashboard_railway_main_headless_antes_v10_39.py')
    if not backup.exists():
        shutil.copy2(target, backup)
        print(f'📦 Backup criado: {backup.name}')
    patch_file(target)
    print('✅ V10.39 aplicada. Agora preencha Data entrada cobrança só para vendedor novo e rode cobrança novamente.')

if __name__ == '__main__':
    main()
