# V10.113 — WORKER LEVE DE AUDITORIA IA + INTENÇÃO RENEGOCIAÇÃO
import os
import sys
import re
import json
import time
import ssl
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("PYTHONIOENCODING","utf-8")
os.environ.setdefault("PYTHONUTF8","1")
try:
    sys.stdout.reconfigure(encoding="utf-8",errors="replace")
    sys.stderr.reconfigure(encoding="utf-8",errors="replace")
except Exception:
    pass

BR_TZ=ZoneInfo(os.getenv("APP_TZ","America/Sao_Paulo"))
def now_brasilia():
    return datetime.now(BR_TZ)

COBRANCA_AUDITORIA_API_URL=os.getenv(
    "COBRANCA_AUDITORIA_API_URL",
    "https://moveisdolar.com.br/colaborador/cobranca_auditoria_api.php"
).strip()
COBRANCA_AUDITORIA_IA_ENABLED=os.getenv("COBRANCA_AUDITORIA_IA_ENABLED","1")=="1"
COBRANCA_AUDITORIA_IA_MODEL=os.getenv("COBRANCA_AUDITORIA_IA_MODEL","gpt-4.1-mini").strip()
COBRANCA_AUDITORIA_IA_MIN_CONFIDENCE=float(os.getenv("COBRANCA_AUDITORIA_IA_MIN_CONFIDENCE","0.82"))
COBRANCA_AUDITORIA_IA_MAX_PER_RUN=max(1,int(os.getenv("COBRANCA_AUDITORIA_IA_MAX_PER_RUN","20")))
COBRANCA_AUDITORIA_IA_MAX_PER_DAY=max(1,int(os.getenv("COBRANCA_AUDITORIA_IA_MAX_PER_DAY","300")))
COBRANCA_AUDITORIA_IA_MAX_USD_PER_DAY=float(os.getenv("COBRANCA_AUDITORIA_IA_MAX_USD_PER_DAY","3.00"))
COBRANCA_AUDITORIA_IA_MAX_USD_PER_MONTH=float(os.getenv("COBRANCA_AUDITORIA_IA_MAX_USD_PER_MONTH","30.00"))
COBRANCA_AUDITORIA_IMAGE_MAX_WIDTH=max(640,int(os.getenv("COBRANCA_AUDITORIA_IMAGE_MAX_WIDTH","1600")))
COBRANCA_AUDITORIA_IMAGE_QUALITY=min(95,max(55,int(os.getenv("COBRANCA_AUDITORIA_IMAGE_QUALITY","82"))))
COBRANCA_AUDITORIA_PRICE_INPUT_PER_M=float(os.getenv("COBRANCA_AUDITORIA_PRICE_INPUT_PER_M","0.40"))
COBRANCA_AUDITORIA_PRICE_OUTPUT_PER_M=float(os.getenv("COBRANCA_AUDITORIA_PRICE_OUTPUT_PER_M","1.60"))
COBRANCA_AUDITORIA_AUDIO_MODEL=os.getenv("COBRANCA_AUDITORIA_AUDIO_MODEL","gpt-4o-mini-transcribe").strip()
COBRANCA_AUDITORIA_DHASH_DISTANCE=max(0,int(os.getenv("COBRANCA_AUDITORIA_DHASH_DISTANCE","6")))

def _urlopen_ssl_v1068(req, *, timeout=90, allow_unverified_for_mdl=True):
    """Abre HTTPS com validação normal e usa fallback apenas no domínio MDL.

    O Railway apresentou CERTIFICATE_VERIFY_FAILED para moveisdolar.com.br,
    embora outras rotinas do mesmo projeto já usem fallback equivalente.
    A API da OpenAI continua obrigatoriamente com SSL validado.
    """
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())
    except urllib.error.URLError as exc:
        host = (urllib.parse.urlparse(getattr(req, "full_url", str(req))).hostname or "").lower()
        ssl_error = "CERTIFICATE_VERIFY_FAILED" in str(exc).upper() or isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError)
        mdl_host = host == "moveisdolar.com.br" or host.endswith(".moveisdolar.com.br")
        if not (allow_unverified_for_mdl and ssl_error and mdl_host):
            raise
        print(f"⚠️ V10.68 SSL normal falhou em {host}; repetindo com contexto sem verificação somente para o servidor MDL.")
        return urllib.request.urlopen(req, timeout=timeout, context=ssl._create_unverified_context())


def _http_json_v1067(url, *, data=None, headers=None, timeout=90):
    try:
        req = urllib.request.Request(url, data=data, headers=headers or {})
        with _urlopen_ssl_v1068(req, timeout=timeout, allow_unverified_for_mdl=True) as resp:
            raw = resp.read()
        return json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {exc.code} em {url}: {body}") from exc


def _response_output_text_v1067(payload):
    if isinstance(payload, dict) and isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts=[]
    for item in (payload.get("output") or []) if isinstance(payload, dict) else []:
        for content in item.get("content") or []:
            txt=content.get("text")
            if isinstance(txt,str): parts.append(txt)
    return "\n".join(parts).strip()


def _parse_json_text_v1067(text):
    text=(text or "").strip()
    text=re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I|re.S).strip()
    try: return json.loads(text)
    except Exception:
        m=re.search(r"\{.*\}", text, flags=re.S)
        if not m: raise ValueError(f"Resposta da IA sem JSON: {text[:500]}")
        return json.loads(m.group(0))


def _download_media_v1067(url, timeout=120):
    req=urllib.request.Request(url,headers={"User-Agent":"MDL-Auditoria/10.68"})
    with _urlopen_ssl_v1068(req,timeout=timeout,allow_unverified_for_mdl=True) as resp:
        return resp.read(),str(resp.headers.get("Content-Type") or "").split(";")[0].lower()


def _sha256_v1067(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()


def _dhash_v1067(data):
    try:
        from PIL import Image
        import io
        im=Image.open(io.BytesIO(data)).convert("L").resize((9,8))
        px=list(im.getdata()); value=0
        for y in range(8):
            row=px[y*9:(y+1)*9]
            for x in range(8): value=(value<<1)|(1 if row[x]>row[x+1] else 0)
        return f"{value:016x}"
    except Exception:
        return ""


def _hamming_v1067(a,b):
    try: return (int(a,16)^int(b,16)).bit_count()
    except Exception: return 999


def _normalize_transcript_v1067(text):
    import unicodedata
    t=unicodedata.normalize("NFKD",str(text or "")).encode("ascii","ignore").decode("ascii").lower()
    t=re.sub(r"\b(boa|bom)\s+(dia|tarde|noite)\b"," ",t)
    return re.sub(r"\s+"," ",re.sub(r"\W+"," ",t)).strip()


def _multipart_audio_v1067(api_key,filename,media_type,data):
    import uuid
    boundary="----MDL"+uuid.uuid4().hex
    parts=[]
    for k,v in {"model":COBRANCA_AUDITORIA_AUDIO_MODEL,"response_format":"json","language":"pt"}.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {media_type or "application/octet-stream"}\r\n\r\n').encode())
    parts.extend([data,f"\r\n--{boundary}--\r\n".encode()])
    return _http_json_v1067("https://api.openai.com/v1/audio/transcriptions",data=b"".join(parts),headers={"Authorization":f"Bearer {api_key}","Content-Type":f"multipart/form-data; boundary={boundary}"},timeout=240).get("text","").strip()


def _iter_previous_attachments_v1067(items,current_id):
    for prev in items or []:
        if str(prev.get("id") or "")==str(current_id): continue
        arr=prev.get("attachments") if isinstance(prev.get("attachments"),list) else []
        if not arr and prev.get("media_url"):
            arr=[{"url":prev.get("media_url"),"sha256":prev.get("file_sha256") or prev.get("upload_sha256"),"dhash":prev.get("image_dhash"),"transcript_normalized":prev.get("audio_transcript_normalized")}]
        for att in arr: yield prev,att


def _find_duplicate_v1067(item,items,sha256="",dhash="",transcript_norm=""):
    import difflib
    for prev,att in _iter_previous_attachments_v1067(items,item.get("id")):
        psha=str(att.get("sha256") or att.get("file_sha256") or att.get("upload_sha256") or "")
        if sha256 and psha and sha256==psha: return "exact_duplicate",prev,0
        pdh=str(att.get("dhash") or att.get("image_dhash") or "")
        if dhash and pdh:
            d=_hamming_v1067(dhash,pdh)
            if d<=COBRANCA_AUDITORIA_DHASH_DISTANCE: return "visual_duplicate",prev,d
        pt=str(att.get("transcript_normalized") or att.get("audio_transcript_normalized") or "")
        if transcript_norm and pt and len(transcript_norm)>=8:
            ratio=difflib.SequenceMatcher(None,transcript_norm,pt).ratio()
            if ratio>=0.96: return "audio_transcript_duplicate",prev,ratio
    return None


def _attachments_v1067(item):
    arr=item.get("attachments") if isinstance(item.get("attachments"),list) else []
    if arr: return arr
    if item.get("media_url"):
        return [{"url":item.get("media_url"),"mime":item.get("media_type") or "","evidence_type":item.get("evidence_type") or ""}]
    return []


def _optimizar_imagem_v1069(data, mime):
    try:
        from PIL import Image
        from io import BytesIO
        im=Image.open(BytesIO(data)).convert("RGB")
        if im.width>COBRANCA_AUDITORIA_IMAGE_MAX_WIDTH:
            nh=max(1,round(im.height*COBRANCA_AUDITORIA_IMAGE_MAX_WIDTH/im.width)); im=im.resize((COBRANCA_AUDITORIA_IMAGE_MAX_WIDTH,nh))
        out=BytesIO(); im.save(out,format="JPEG",quality=COBRANCA_AUDITORIA_IMAGE_QUALITY,optimize=True)
        return out.getvalue(),"image/jpeg"
    except Exception:
        return data,mime or "image/jpeg"


def _usage_cost_v1069(raw):
    usage=raw.get("usage") if isinstance(raw,dict) else {}
    usage=usage if isinstance(usage,dict) else {}
    inp=int(usage.get("input_tokens") or 0); out=int(usage.get("output_tokens") or 0)
    cost=(inp/1_000_000)*COBRANCA_AUDITORIA_PRICE_INPUT_PER_M+(out/1_000_000)*COBRANCA_AUDITORIA_PRICE_OUTPUT_PER_M
    return {"input_tokens":inp,"output_tokens":out,"cost_total_usd":round(cost,8)}


def _analisar_bundle_v1067(item,api_key,all_items):
    import base64
    attachments=_attachments_v1067(item)
    if not attachments: return {"status":"revisao_master","confidence":0.0,"motivo":"Cobrança sem anexos."}
    processed=[]; image_contents=[]; transcripts=[]; has_image=False; has_audio=False
    for idx,att in enumerate(attachments,1):
        url=str(att.get("url") or att.get("media_url") or "").strip()
        data,mime=_download_media_v1067(url)
        mime=str(att.get("mime") or att.get("media_type") or mime or "").lower()
        sha=_sha256_v1067(data)
        rec={"url":url,"mime":mime,"sha256":sha,"name":att.get("name") or url.rsplit('/',1)[-1]}
        if mime.startswith("image/"):
            has_image=True; dh=_dhash_v1067(data); rec["dhash"]=dh
            dup=_find_duplicate_v1067(item,all_items,sha256=sha,dhash=dh)
            if dup:
                typ,prev,metric=dup
                auto = typ=="exact_duplicate"
                return {"status":"revisao_master","confidence":0.98 if auto else 0.70,"fraude_suspeita":True,"requer_decisao_master":True,"ia_recomendacao":"recusar","duplicate_type":typ,"motivo":f"{'Arquivo idêntico' if auto else 'Imagem visualmente semelhante'} já usado em {prev.get('cliente','')}, título {prev.get('titulo','')}, usuário {prev.get('usuario_login','')}.","attachments":processed+[rec]}
            data,mime=_optimizar_imagem_v1069(data,mime)
            rec["optimized_bytes"]=len(data)
            data_url=f"data:{mime or 'image/jpeg'};base64,{base64.b64encode(data).decode('ascii')}"
            image_contents.append({"type":"input_image","image_url":data_url,"detail":"high"})
        elif mime.startswith("audio/"):
            has_audio=True
            transcript=_multipart_audio_v1067(api_key,rec["name"],mime,data)
            norm=_normalize_transcript_v1067(transcript)
            rec.update({"transcript":transcript,"transcript_normalized":norm})
            dup=_find_duplicate_v1067(item,all_items,sha256=sha,transcript_norm=norm)
            if dup:
                typ,prev,metric=dup
                auto = typ=="exact_duplicate"
                return {"status":"revisao_master","confidence":0.98 if auto else 0.70,"fraude_suspeita":True,"requer_decisao_master":True,"ia_recomendacao":"recusar","duplicate_type":typ,"motivo":f"{'Arquivo de áudio idêntico' if auto else 'Transcrição de áudio muito semelhante'} já usado em {prev.get('cliente','')}, título {prev.get('titulo','')}, usuário {prev.get('usuario_login','')}.","attachments":processed+[rec]}
            transcripts.append(f"Áudio {idx}: {transcript}")
        processed.append(rec)
    if has_audio and not has_image:
        return {"status":"revisao_master","confidence":0.0,"motivo":"Resposta em áudio sem print da conversa. Print + áudio são obrigatórios.","attachments":processed}
    cliente=str(item.get("cliente") or ""); telefone=re.sub(r"\D","",str(item.get("telefone") or "")); titulo=str(item.get("titulo") or ""); parcela=str(item.get("parcela") or ""); faixa=str(item.get("faixa") or "")
    prompt=f"""Você audita um CONJUNTO de evidências de uma cobrança das Lojas MDL.
Registro esperado: cliente {cliente}; telefone {telefone}; título {titulo}; parcela {parcela}; faixa {faixa}.
Há {sum(1 for x in processed if x['mime'].startswith('image/'))} print(s) e {sum(1 for x in processed if x['mime'].startswith('audio/'))} áudio(s).
Transcrições: {transcripts if transcripts else 'nenhuma'}.
Analise os arquivos em conjunto. Aprove somente quando os prints mostram contexto da cobrança e resposta recebida depois da mensagem. Quando houver áudio, confirme que o print mostra mensagem de áudio recebida e que a transcrição é coerente com a conversa. O contato do WhatsApp pode estar salvo com apelido, nome de familiar, empresa ou descrição diferente do cadastro; divergência de nome ou telefone, sozinha, NUNCA deve causar recusa automática. Procure inconsistências de horários, fontes, bolhas, recortes, aplicativos simuladores, manipulação, arquivos de clientes diferentes e sequência temporal impossível.
A resposta pode validar a cobrança mesmo sem promessa de pagamento, desde que demonstre que o cliente recebeu e compreendeu a cobrança. Qualquer recomendação negativa, duplicidade ou suspeita deve usar revisao_master, pois o veredito final de recusa é exclusivo do MASTER. Classifique também o tipo de resposta. Se o cliente pedir para renegociar, fazer acordo, parcelar novamente, quitar/acertar todos os títulos ou toda a dívida, classifique tipo_resposta como renegociacao_acordo e intencao_renegociacao=true.
Retorne somente JSON: {{"status":"aprovado|revisao_master|recusado","confidence":0.0,"contato_compativel":true,"contexto_cobranca":true,"resposta_cliente":true,"audio_visivel_no_print":true,"ordem_temporal_coerente":true,"sinais_manipulacao":[],"suspeita_app_gerador":false,"resposta_cliente_resumida":"...","tipo_resposta":"promessa_pagamento|pedido_boleto_pix|data_pagamento|renegociacao_acordo|negativa|duvida|responsavel_terceiro|ciente_sem_promessa|outro","intencao_renegociacao":false,"motivo":"..."}}"""
    content=[{"type":"input_text","text":prompt},*image_contents]
    body={"model":COBRANCA_AUDITORIA_IA_MODEL,"input":[{"role":"user","content":content}],"store":False}
    raw=_http_json_v1067("https://api.openai.com/v1/responses",data=json.dumps(body,ensure_ascii=False).encode("utf-8"),headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json; charset=utf-8"},timeout=240)
    result=_parse_json_text_v1067(_response_output_text_v1067(raw))
    status=str(result.get("status") or "revisao_master").lower().strip(); confidence=float(result.get("confidence") or 0.0)
    if result.get("suspeita_app_gerador") or result.get("sinais_manipulacao"): status="revisao_master"
    if status=="aprovado": status="aprovado_ia" if confidence>=COBRANCA_AUDITORIA_IA_MIN_CONFIDENCE else "revisao_master"
    elif status=="recusado":
        result["ia_recomendacao"]="recusar"; result["requer_decisao_master"]=True; status="revisao_master"
    if status not in {"aprovado_ia","revisao_master"}: status="revisao_master"
    if status=="revisao_master": result["requer_decisao_master"]=True
    result.update(_usage_cost_v1069(raw))
    result.update({"status":status,"confidence":confidence,"attachments":processed,"has_audio":has_audio,"has_image":has_image})
    return result


def _atualizar_status_v1067(item,result):
    payload=urllib.parse.urlencode({"action":"set_status","id":str(item.get("id") or ""),"status":str(result.get("status") or "revisao_master"),"motivo":str(result.get("motivo") or "Auditoria concluída.")[:1800],"ia_confidence":f"{float(result.get('confidence') or 0):.4f}","ia_model":COBRANCA_AUDITORIA_IA_MODEL,"ia_json":json.dumps(result,ensure_ascii=False),"attachments_json":json.dumps(result.get("attachments") or [],ensure_ascii=False),"fraude_suspeita":"1" if result.get("fraude_suspeita") else "0","input_tokens":str(result.get("input_tokens") or 0),"output_tokens":str(result.get("output_tokens") or 0),"custo_total_usd":f"{float(result.get('cost_total_usd') or 0):.8f}"}).encode("utf-8")
    return _http_json_v1067(COBRANCA_AUDITORIA_API_URL,data=payload,headers={"Content-Type":"application/x-www-form-urlencoded; charset=utf-8"},timeout=90)



def _post_action_v1105(**kwargs):
    payload=urllib.parse.urlencode({k:str(v) for k,v in kwargs.items()}).encode("utf-8")
    return _http_json_v1067(
        COBRANCA_AUDITORIA_API_URL,
        data=payload,
        headers={"Content-Type":"application/x-www-form-urlencoded; charset=utf-8"},
        timeout=90
    )

def _claim_v1105(item):
    try:
        r=_post_action_v1105(action="claim",id=str(item.get("id") or ""))
        return bool(r.get("ok") and r.get("claimed"))
    except Exception as e:
        print(f"⚠️ claim falhou {item.get('id','')}: {e}")
        return False

def _requeue_failure_v1105(item, exc):
    try:
        _post_action_v1105(
            action="set_status",
            id=str(item.get("id") or ""),
            status="aguardando_ia",
            motivo=("Falha temporária no worker IA; será tentado novamente. "+str(exc))[:1200],
            ia_confidence="0",
            ia_model=COBRANCA_AUDITORIA_IA_MODEL,
            fraude_suspeita="0",
            input_tokens="0",
            output_tokens="0",
            custo_total_usd="0"
        )
    except Exception as e:
        print(f"⚠️ não consegui recolocar na fila: {e}")

def _requeue_stale_v1105(items):
    now=now_brasilia()
    qtd=0
    for x in items or []:
        if str(x.get("status") or "").lower()!="processando_ia":
            continue
        raw=str(x.get("process_started_at") or "")
        try:
            dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
            if dt.tzinfo is None:
                dt=dt.replace(tzinfo=BR_TZ)
            dt=dt.astimezone(BR_TZ)
        except Exception:
            continue
        if (now-dt).total_seconds() < 600:
            continue
        try:
            _post_action_v1105(
                action="set_status",
                id=str(x.get("id") or ""),
                status="aguardando_ia",
                motivo="Processamento anterior excedeu 10 minutos; worker V10.113 recolocou na fila.",
                ia_confidence="0",ia_model=COBRANCA_AUDITORIA_IA_MODEL,
                fraude_suspeita="0",input_tokens="0",output_tokens="0",custo_total_usd="0"
            )
            qtd+=1
        except Exception:
            pass
    return qtd

def processar_v1105():
    print("⚡ V10.113 worker auditoria iniciado", flush=True)
    if not COBRANCA_AUDITORIA_IA_ENABLED:
        print("ℹ️ COBRANCA_AUDITORIA_IA_ENABLED=0")
        return 0
    api_key=os.getenv("OPENAI_API_KEY","").strip()
    if not api_key:
        print("⚠️ OPENAI_API_KEY ausente; fila permanecerá aguardando IA.")
        return 2

    listing=_http_json_v1067(COBRANCA_AUDITORIA_API_URL+"?_="+str(int(time.time())),timeout=90)
    items=listing.get("data") if isinstance(listing,dict) else []
    if not isinstance(items,list):
        items=[]

    stale=_requeue_stale_v1105(items)
    if stale:
        print(f"♻️ {stale} caso(s) processando há >10min foram recolocados na fila.")
        listing=_http_json_v1067(COBRANCA_AUDITORIA_API_URL+"?_="+str(int(time.time())),timeout=90)
        items=listing.get("data") if isinstance(listing,dict) else []

    hoje=now_brasilia().strftime("%Y-%m-%d")
    mes=hoje[:7]
    terminal={"aprovado","aprovado_ia","revisao_master","aprovado_manual","recusado_manual","recusado","recusado_ia"}
    completed=[x for x in items if str(x.get("status") or "").lower() in terminal]
    qtd_hoje=sum(1 for x in completed if str(x.get("ia_analisado_em") or x.get("updated_at") or "").startswith(hoje))
    custo_hoje=sum(float(x.get("custo_total_usd") or 0) for x in completed if str(x.get("ia_analisado_em") or x.get("updated_at") or "").startswith(hoje))
    custo_mes=sum(float(x.get("custo_total_usd") or 0) for x in completed if str(x.get("ia_analisado_em") or x.get("updated_at") or "").startswith(mes))

    if qtd_hoje>=COBRANCA_AUDITORIA_IA_MAX_PER_DAY or custo_hoje>=COBRANCA_AUDITORIA_IA_MAX_USD_PER_DAY or custo_mes>=COBRANCA_AUDITORIA_IA_MAX_USD_PER_MONTH:
        print(f"🛑 Limite auditoria atingido: hoje={qtd_hoje}, US$ hoje={custo_hoje:.4f}, US$ mês={custo_mes:.4f}")
        return 0

    pend=[x for x in items if str(x.get("status") or "aguardando_ia").lower()=="aguardando_ia"][:COBRANCA_AUDITORIA_IA_MAX_PER_RUN]
    print(f"🛡️ fila pendente: {len(pend)} caso(s)")
    if not pend:
        return 0

    processed=0
    for item in pend:
        if not _claim_v1105(item):
            continue
        try:
            print(f"🤖 analisando {item.get('usuario_login','')} · {item.get('cliente','')} · título {item.get('titulo','')}", flush=True)
            result=_analisar_bundle_v1067(item,api_key,items)
            _atualizar_status_v1067(item,result)
            processed+=1
            icon="✅" if result.get("status")=="aprovado_ia" else "🧑‍⚖️"
            print(f"{icon} {item.get('cliente','')} · {result.get('status')} · confiança {float(result.get('confidence') or 0):.0%}", flush=True)
        except Exception as exc:
            print(f"⚠️ falha {item.get('id','')}: {type(exc).__name__}: {exc}", flush=True)
            _requeue_failure_v1105(item,exc)

    print(f"✅ worker V10.113 concluído: {processed} processado(s)", flush=True)
    return 0

if __name__=="__main__":
    try:
        raise SystemExit(processar_v1105())
    except SystemExit:
        raise
    except Exception as e:
        print(f"🚨 worker V10.113 erro fatal: {type(e).__name__}: {e}", flush=True)
        raise

# V10.113_RENEGOCIACAO_INTENCAO
