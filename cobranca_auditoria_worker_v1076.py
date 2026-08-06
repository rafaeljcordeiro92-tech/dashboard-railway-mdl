#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Worker leve V10.76 para auditoria imediata de evidências de cobrança.

Executar em um serviço Railway separado:
    python cobranca_auditoria_worker_v1069.py

Variáveis obrigatórias:
    OPENAI_API_KEY
    COBRANCA_AUDITORIA_WEBHOOK_SECRET

Variáveis recomendadas:
    COBRANCA_AUDITORIA_API_URL
    COBRANCA_AUDITORIA_IA_MODEL
    COBRANCA_AUDITORIA_AUDIO_MODEL
    COBRANCA_AUDITORIA_IA_MIN_CONFIDENCE
    COBRANCA_AUDITORIA_IA_MAX_PER_DAY
    COBRANCA_AUDITORIA_IA_MAX_USD_PER_DAY
    COBRANCA_AUDITORIA_IA_MAX_USD_PER_MONTH
"""
from __future__ import annotations

import base64
import difflib
import hashlib
import io
import json
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

VERSION = "V10.76"
API_URL = os.getenv("COBRANCA_AUDITORIA_API_URL", "https://moveisdolar.com.br/colaborador/cobranca_auditoria_api.php").strip()
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
SECRET = os.getenv("COBRANCA_AUDITORIA_WEBHOOK_SECRET", "").strip()
MODEL = os.getenv("COBRANCA_AUDITORIA_IA_MODEL", "gpt-4.1-mini").strip()
AUDIO_MODEL = os.getenv("COBRANCA_AUDITORIA_AUDIO_MODEL", "gpt-4o-mini-transcribe").strip()
MIN_CONF = float(os.getenv("COBRANCA_AUDITORIA_IA_MIN_CONFIDENCE", "0.82"))
MAX_PER_DAY = max(1, int(os.getenv("COBRANCA_AUDITORIA_IA_MAX_PER_DAY", "300")))
MAX_USD_DAY = float(os.getenv("COBRANCA_AUDITORIA_IA_MAX_USD_PER_DAY", "3.00"))
MAX_USD_MONTH = float(os.getenv("COBRANCA_AUDITORIA_IA_MAX_USD_PER_MONTH", "30.00"))
MAX_WIDTH = max(640, int(os.getenv("COBRANCA_AUDITORIA_IMAGE_MAX_WIDTH", "1600")))
IMG_QUALITY = min(95, max(55, int(os.getenv("COBRANCA_AUDITORIA_IMAGE_QUALITY", "82"))))
PRICE_INPUT_M = float(os.getenv("COBRANCA_AUDITORIA_PRICE_INPUT_PER_M", "0.40"))
PRICE_OUTPUT_M = float(os.getenv("COBRANCA_AUDITORIA_PRICE_OUTPUT_PER_M", "1.60"))
POLL_SECONDS = max(10, int(os.getenv("COBRANCA_AUDITORIA_FALLBACK_SECONDS", "60")))
PORT = int(os.getenv("PORT", "8080"))
DHASH_DISTANCE = max(0, int(os.getenv("COBRANCA_AUDITORIA_DHASH_DISTANCE", "4")))

_LOCKS: set[str] = set()
_LOCK = threading.Lock()


def _ctx_for(url: str):
    host = urllib.parse.urlparse(url).hostname or ""
    if host.lower() == "moveisdolar.com.br":
        return ssl._create_unverified_context()
    return ssl.create_default_context()


def http_json(url: str, data: bytes | None = None, headers: dict[str, str] | None = None, timeout: int = 120) -> dict[str, Any]:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx_for(url)) as r:
        raw = r.read()
    obj = json.loads(raw.decode("utf-8", "replace"))
    return obj if isinstance(obj, dict) else {"data": obj}


def list_items() -> list[dict[str, Any]]:
    obj = http_json(API_URL + "?_=" + str(int(time.time())))
    return obj.get("data") if isinstance(obj.get("data"), list) else []


def post_form(fields: dict[str, Any]) -> dict[str, Any]:
    payload = urllib.parse.urlencode({k: str(v) for k, v in fields.items()}).encode("utf-8")
    return http_json(API_URL, payload, {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}, 90)


def claim(item_id: str) -> bool:
    return bool(post_form({"action": "claim", "id": item_id}).get("claimed"))


def download(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": f"MDL-Audit/{VERSION}"})
    with urllib.request.urlopen(req, timeout=120, context=_ctx_for(url)) as r:
        return r.read(), (r.headers.get_content_type() or "application/octet-stream")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dhash(data: bytes) -> str:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("L").resize((9, 8))
        pix = list(im.getdata())
        bits = []
        for y in range(8):
            row = pix[y * 9 : (y + 1) * 9]
            bits.extend(row[x] > row[x + 1] for x in range(8))
        n = 0
        for b in bits:
            n = (n << 1) | int(b)
        return f"{n:016x}"
    except Exception:
        return ""


def hamming(a: str, b: str) -> int:
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except Exception:
        return 999


def optimize_image(data: bytes) -> tuple[bytes, str]:
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        if im.width > MAX_WIDTH:
            nh = max(1, round(im.height * MAX_WIDTH / im.width))
            im = im.resize((MAX_WIDTH, nh))
        out = io.BytesIO()
        im.save(out, "JPEG", quality=IMG_QUALITY, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:
        return data, "image/jpeg"


def normalize_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "").strip().lower())
    return re.sub(r"[^a-z0-9áàâãéêíóôõúç ]", "", text)


def attachments(item: dict[str, Any]) -> list[dict[str, Any]]:
    arr = item.get("attachments")
    return arr if isinstance(arr, list) else []


def previous_attachments(items: list[dict[str, Any]], current_id: str):
    for prev in items:
        if str(prev.get("id")) == str(current_id):
            continue
        for att in attachments(prev):
            yield prev, att


def duplicate(item: dict[str, Any], items: list[dict[str, Any]], sh: str = "", dh: str = "", transcript: str = ""):
    for prev, att in previous_attachments(items, str(item.get("id") or "")):
        psh = str(att.get("sha256") or "")
        if sh and psh and sh == psh:
            return "exact_duplicate", prev
        pdh = str(att.get("dhash") or "")
        if dh and pdh and hamming(dh, pdh) <= DHASH_DISTANCE:
            return "visual_duplicate", prev
        pt = str(att.get("transcript_normalized") or "")
        if transcript and pt and len(transcript) >= 8 and difflib.SequenceMatcher(None, transcript, pt).ratio() >= 0.96:
            return "audio_transcript_duplicate", prev
    return None


def transcribe(name: str, mime: str, data: bytes) -> str:
    boundary = "----MDL" + hashlib.md5(os.urandom(16)).hexdigest()
    chunks: list[bytes] = []
    for k, v in {"model": AUDIO_MODEL, "response_format": "json", "language": "pt"}.items():
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
    chunks.extend([data, f"\r\n--{boundary}--\r\n".encode()])
    obj = http_json("https://api.openai.com/v1/audio/transcriptions", b"".join(chunks), {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, 240)
    return str(obj.get("text") or "").strip()


def output_text(raw: dict[str, Any]) -> str:
    if raw.get("output_text"):
        return str(raw["output_text"])
    parts: list[str] = []
    for out in raw.get("output") or []:
        for c in out.get("content") or []:
            if c.get("text"):
                parts.append(str(c["text"]))
    return "\n".join(parts)


def parse_json_text(text: str) -> dict[str, Any]:
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise ValueError("resposta_sem_json")
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else {}


def usage_cost(raw: dict[str, Any]) -> dict[str, Any]:
    u = raw.get("usage") if isinstance(raw.get("usage"), dict) else {}
    inp = int(u.get("input_tokens") or 0)
    out = int(u.get("output_tokens") or 0)
    cost = inp / 1_000_000 * PRICE_INPUT_M + out / 1_000_000 * PRICE_OUTPUT_M
    return {"input_tokens": inp, "output_tokens": out, "cost_total_usd": round(cost, 8)}


def limits_ok(items: list[dict[str, Any]]) -> tuple[bool, str]:
    now = datetime.now()
    day, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    today = [x for x in items if str(x.get("ia_analisado_em") or x.get("updated_at") or "").startswith(day)]
    day_cost = sum(float(x.get("custo_total_usd") or 0) for x in today)
    month_cost = sum(float(x.get("custo_total_usd") or 0) for x in items if str(x.get("ia_analisado_em") or x.get("updated_at") or "").startswith(month))
    if len(today) >= MAX_PER_DAY:
        return False, f"limite_diario_quantidade_{len(today)}"
    if day_cost >= MAX_USD_DAY:
        return False, f"limite_diario_usd_{day_cost:.4f}"
    if month_cost >= MAX_USD_MONTH:
        return False, f"limite_mensal_usd_{month_cost:.4f}"
    return True, "ok"


def analyze(item: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    processed, images, transcripts = [], [], []
    has_image = has_audio = False
    for idx, att in enumerate(attachments(item), 1):
        url = str(att.get("url") or "")
        data, detected = download(url)
        mime = str(att.get("mime") or detected or "").lower()
        sh = sha256(data)
        rec: dict[str, Any] = {"url": url, "mime": mime, "name": att.get("name") or url.rsplit("/", 1)[-1], "sha256": sh}
        if mime.startswith("image/"):
            has_image = True
            dh = dhash(data)
            rec["dhash"] = dh
            dup = duplicate(item, items, sh=sh, dh=dh)
            if dup:
                typ, prev = dup
                exact = typ == "exact_duplicate"
                return {"status": "revisao_master", "confidence": 0.98 if exact else 0.70, "fraude_suspeita": True, "requer_decisao_master": True, "ia_recomendacao": "recusar", "duplicate_type": typ, "motivo": f"{'Arquivo idêntico' if exact else 'Imagem visualmente semelhante'} já usado em {prev.get('cliente','')}, título {prev.get('titulo','')}.", "attachments": processed + [rec], "cost_total_usd": 0.0}
            data, mime = optimize_image(data)
            rec["optimized_bytes"] = len(data)
            images.append({"type": "input_image", "image_url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", "detail": "high"})
        elif mime.startswith("audio/"):
            has_audio = True
            text = transcribe(rec["name"], mime, data)
            norm = normalize_text(text)
            rec.update({"transcript": text, "transcript_normalized": norm})
            dup = duplicate(item, items, sh=sh, transcript=norm)
            if dup:
                typ, prev = dup
                exact = typ == "exact_duplicate"
                return {"status": "revisao_master", "confidence": 0.98 if exact else 0.70, "fraude_suspeita": True, "requer_decisao_master": True, "ia_recomendacao": "recusar", "duplicate_type": typ, "motivo": f"{'Arquivo de áudio idêntico' if exact else 'Transcrição muito semelhante'} já usado em {prev.get('cliente','')}, título {prev.get('titulo','')}.", "attachments": processed + [rec], "cost_total_usd": 0.0}
            transcripts.append(f"Áudio {idx}: {text}")
        processed.append(rec)
    if has_audio and not has_image:
        return {"status": "revisao_master", "confidence": 0.0, "motivo": "Resposta em áudio sem print da conversa.", "attachments": processed, "cost_total_usd": 0.0}
    prompt = f"""Você audita evidências de cobrança das Lojas MDL.
Registro: cliente {item.get('cliente','')}; telefone {re.sub(r'\D','',str(item.get('telefone') or ''))}; CPF {item.get('cpf_cnpj','')}; título {item.get('titulo','')}; parcela {item.get('parcela','')}; faixa {item.get('faixa','')}.
Transcrições: {transcripts if transcripts else 'nenhuma'}.
Analise todos os arquivos juntos. Aprove somente quando houver mensagem de cobrança e resposta posterior do cliente. O nome salvo no WhatsApp pode ser apelido, nome de familiar, empresa ou descrição diferente do cadastro; divergência de nome ou telefone, sozinha, NUNCA deve causar recusa automática. Quando houver divergência de contato, falta de clareza, possível manipulação, recorte, simulador ou qualquer suspeita, encaminhe para revisao_master. Uma resposta consciente valida a cobrança mesmo sem promessa de pagamento. A IA não dá veredito final negativo: qualquer recomendação de recusa deve ir para revisao_master para decisão humana.
Retorne somente JSON: {{"status":"aprovado|revisao_master|recusado","confidence":0.0,"contato_compativel":true,"contexto_cobranca":true,"resposta_cliente":true,"audio_visivel_no_print":true,"ordem_temporal_coerente":true,"sinais_manipulacao":[],"suspeita_app_gerador":false,"resposta_cliente_resumida":"...","tipo_resposta":"promessa_pagamento|pedido_boleto_pix|data_pagamento|negativa|duvida|responsavel_terceiro|ciente_sem_promessa|outro","motivo":"..."}}"""
    body = {"model": MODEL, "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}, *images]}], "store": False}
    raw = http_json("https://api.openai.com/v1/responses", json.dumps(body, ensure_ascii=False).encode(), {"Authorization": f"Bearer {OPENAI_KEY}", "Content-Type": "application/json"}, 240)
    result = parse_json_text(output_text(raw))
    conf = float(result.get("confidence") or 0.0)
    status = str(result.get("status") or "revisao_master").lower()
    if result.get("suspeita_app_gerador") or result.get("sinais_manipulacao"):
        status = "revisao_master"
    elif status == "aprovado":
        status = "aprovado_ia" if conf >= MIN_CONF else "revisao_master"
    elif status == "recusado":
        result["ia_recomendacao"] = "recusar"
        result["requer_decisao_master"] = True
        status = "revisao_master"
    else:
        status = "revisao_master"
    if status == "revisao_master":
        result["requer_decisao_master"] = True
    result.update(usage_cost(raw))
    result.update({"status": status, "confidence": conf, "attachments": processed, "has_audio": has_audio, "has_image": has_image})
    return result


def save_result(item: dict[str, Any], result: dict[str, Any]) -> None:
    post_form({
        "action": "set_status", "id": item.get("id", ""), "status": result.get("status", "revisao_master"),
        "motivo": str(result.get("motivo") or "Auditoria concluída.")[:1800], "ia_confidence": f"{float(result.get('confidence') or 0):.4f}",
        "ia_model": MODEL, "ia_json": json.dumps(result, ensure_ascii=False), "attachments_json": json.dumps(result.get("attachments") or [], ensure_ascii=False),
        "fraude_suspeita": "1" if result.get("fraude_suspeita") else "0", "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0), "custo_total_usd": f"{float(result.get('cost_total_usd') or 0):.8f}",
    })


def process_id(item_id: str) -> dict[str, Any]:
    if not OPENAI_KEY:
        return {"ok": False, "error": "OPENAI_API_KEY_ausente"}
    with _LOCK:
        if item_id in _LOCKS:
            return {"ok": True, "status": "ja_processando"}
        _LOCKS.add(item_id)
    try:
        items = list_items()
        ok, why = limits_ok(items)
        if not ok:
            return {"ok": False, "error": why}
        item = next((x for x in items if str(x.get("id")) == str(item_id)), None)
        if not item:
            return {"ok": False, "error": "id_nao_encontrado"}
        if str(item.get("status") or "") not in {"aguardando_ia", "processando_ia"}:
            return {"ok": True, "status": "ja_concluido"}
        if str(item.get("status") or "") == "aguardando_ia" and not claim(item_id):
            return {"ok": True, "status": "nao_reivindicado"}
        result = analyze(item, items)
        save_result(item, result)
        print(f"[{VERSION}] {item.get('cliente','')} título {item.get('titulo','')} => {result.get('status')} {float(result.get('confidence') or 0):.0%} US$ {float(result.get('cost_total_usd') or 0):.6f}", flush=True)
        return {"ok": True, "status": result.get("status"), "confidence": result.get("confidence"), "cost_usd": result.get("cost_total_usd", 0)}
    except Exception as exc:
        print(f"[{VERSION}] falha {item_id}: {type(exc).__name__}: {exc}", flush=True)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        with _LOCK:
            _LOCKS.discard(item_id)


def fallback_loop() -> None:
    while True:
        try:
            items = list_items()
            pending = [x for x in items if str(x.get("status") or "") == "aguardando_ia"][:5]
            for item in pending:
                process_id(str(item.get("id") or ""))
        except Exception as exc:
            print(f"[{VERSION}] fallback: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


class Handler(BaseHTTPRequestHandler):
    server_version = f"MDLAudit/{VERSION}"
    def log_message(self, fmt, *args):
        print(f"[{VERSION}] {self.address_string()} {fmt % args}", flush=True)
    def send_json(self, code: int, obj: dict[str, Any]):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        if self.path.startswith("/health"):
            self.send_json(200, {"ok": True, "version": VERSION, "openai": bool(OPENAI_KEY), "secret": bool(SECRET)})
        else:
            self.send_json(404, {"ok": False, "error": "not_found"})
    def do_POST(self):
        if self.path.rstrip("/") != "/trigger":
            return self.send_json(404, {"ok": False, "error": "not_found"})
        if not SECRET or self.headers.get("X-Audit-Secret", "") != SECRET:
            return self.send_json(403, {"ok": False, "error": "forbidden"})
        try:
            n = int(self.headers.get("Content-Length", "0")); body = json.loads(self.rfile.read(n) or b"{}")
            item_id = str(body.get("id") or "")
        except Exception:
            return self.send_json(400, {"ok": False, "error": "json_invalido"})
        if not item_id:
            return self.send_json(400, {"ok": False, "error": "id_obrigatorio"})
        threading.Thread(target=process_id, args=(item_id,), daemon=True).start()
        self.send_json(202, {"ok": True, "queued": True, "id": item_id, "version": VERSION})


def main() -> None:
    print(f"[{VERSION}] worker iniciando na porta {PORT}; fallback={POLL_SECONDS}s", flush=True)
    threading.Thread(target=fallback_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
