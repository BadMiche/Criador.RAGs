"""Cliente mínimo da API System One (Jev/TypeSafe) via HTTP.

Envia as perguntas no formato nativo da API (o mesmo JSON que o planejador Opus escreve):
    {"id": {"type": "noul"|"choice"|"score", "instructions": ..., "criteria": ...}}

Regras:
- Falha da API levanta JevErro (nunca vira "não").
- Cada chamada é registrada (payload exato + resposta) no log do documento.
- TYPESAFE_API_KEY vem do ambiente.
"""
from __future__ import annotations

import base64
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import requests

from comum import anexar_jsonl, carregar_config


class JevErro(RuntimeError):
    pass


def _cfg() -> dict:
    return carregar_config()["jev"]


IMG_MIN, IMG_MAX = 280, 1568  # limites do Jev por lado (px); fora disso a API rejeita


def preparar_imagem(caminho: Path) -> bytes:
    """Cópia PNG dentro dos limites do Jev: reduz se passar de 1568 px, completa com branco se tiver menos de 280."""
    import io

    from PIL import Image

    img = Image.open(caminho).convert("RGB")
    escala = min(1.0, IMG_MAX / max(img.size))
    if escala < 1:
        img = img.resize((max(1, round(img.width * escala)), max(1, round(img.height * escala))))
    if min(img.size) < IMG_MIN:
        fundo = Image.new("RGB", (max(img.width, IMG_MIN), max(img.height, IMG_MIN)), "white")
        fundo.paste(img, ((fundo.width - img.width) // 2, (fundo.height - img.height) // 2))
        img = fundo
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def imagem_asset(caminho: Path) -> tuple[str, dict]:
    """Retorna (placeholder, asset) para colocar a imagem no state ou nas instructions."""
    ref = f"img-{uuid.uuid4().hex}"
    dados = base64.b64encode(preparar_imagem(Path(caminho))).decode()
    return ref, {"type": "image", "format": "png", "data_base64": dados}


def perguntar(state, questions: dict, *, assets: dict | None = None,
              log: Path | None = None, contexto: dict | None = None) -> dict:
    """Uma chamada ao Jev. Retorna {id: resposta} no formato da API."""
    cfg = _cfg()
    chave = os.environ.get("TYPESAFE_API_KEY")
    if not chave and os.environ.get("CLAUDE_CODE_REMOTE") == "true":
        chave = "proxy-injected"  # nuvem: o proxy do ambiente injeta a chave salva
    if not chave:
        raise JevErro("TYPESAFE_API_KEY não definida. No Mac: adicione `export TYPESAFE_API_KEY=...` ao ~/.zshrc "
                      "(crie a chave em https://console.typesafe.ai) e abra um terminal novo.")
    payload = {"model": cfg["modelo"], "state": state, "questions": questions}
    headers = {"Authorization": f"Bearer {chave}", "Content-Type": "application/json"}
    if assets:
        payload["assets"] = assets
        headers["TypeSafe-Danger-Zone-Images"] = "true"

    ultimo = None
    for tentativa in range(cfg["tentativas"]):
        try:
            r = requests.post(cfg["url"], json=payload, headers=headers, timeout=cfg["timeout_s"])
        except requests.RequestException as e:
            ultimo = f"rede: {e}"
        else:
            if r.status_code == 200:
                corpo = r.json()
                if log:
                    reg = {"contexto": contexto or {}, "request": _sem_base64(payload), "response": corpo}
                    anexar_jsonl(log, reg)
                return corpo["answers"]
            if r.status_code not in (429, 529, 500, 502, 503, 504):
                raise JevErro(f"HTTP {r.status_code}: {r.text[:500]}")
            ultimo = f"HTTP {r.status_code}"
            espera = float(r.headers.get("retry-after", 0) or 0)
            if espera:
                time.sleep(espera)
                continue
        time.sleep(2 ** tentativa)
    raise JevErro(f"Jev indisponível após {cfg['tentativas']} tentativas ({ultimo}).")


def perguntar_varios(tarefas: list[dict], fn: Callable | None = None) -> list[dict]:
    """Executa várias chamadas em paralelo. Cada tarefa = kwargs de perguntar()."""
    fn = fn or perguntar
    with ThreadPoolExecutor(max_workers=_cfg()["concorrencia"]) as ex:
        return list(ex.map(lambda t: fn(**t), tarefas))


def _sem_base64(payload: dict) -> dict:
    if "assets" not in payload:
        return payload
    p = dict(payload)
    p["assets"] = {k: {**v, "data_base64": f"<{len(v['data_base64'])} chars>"} for k, v in payload["assets"].items()}
    return p


# ---- leitura das respostas ----

def valor(resposta: dict) -> float | str:
    """Valor principal de uma resposta: noul -> prob, choice -> opção, score -> score."""
    t = resposta["type"]
    return {"noul": resposta.get("noul"), "choice": resposta.get("choice"), "score": resposta.get("score")}[t]


def resumir(respostas: dict) -> dict:
    """Versão compacta para os logs de decisão."""
    out = {}
    for k, r in respostas.items():
        if r["type"] == "noul":
            out[k] = round(r["noul"], 3)
        elif r["type"] == "choice":
            out[k] = {"choice": r["choice"], "p": {o: round(p, 3) for o, p in r["probabilities"].items()}}
        elif r["type"] == "score":
            out[k] = {"score": round(r["score"], 3), "p": {o: round(p, 3) for o, p in r["probabilities"].items()}}
    return out
