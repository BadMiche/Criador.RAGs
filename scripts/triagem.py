"""Etapas 7 e 7b — triagem de cada trecho pelo Jev + revisão (Sonnet) das decisões arriscadas.

  python triagem.py <projeto> rodar <doc> [--ids t0003,t0007]
      1 request ao Jev por trecho com todas as perguntas do plano; código aplica as regras.
  python triagem.py <projeto> pendentes <doc>
      Gera revisao/<doc>.pendentes.json: trechos incertos + todos os "descartar" (para o agente Sonnet).
  python triagem.py <projeto> aplicar-revisao <doc>
      Lê revisao/<doc>.json ({id: {acao, motivo}}) e define a acao_final de cada trecho.
"""
from __future__ import annotations

import argparse

import jev_client
import plano as planolib
from comum import Projeto, carregar_config, ler_json, ler_jsonl, salvar_json, salvar_jsonl


def estado_trecho(trecho: dict, plano: dict, meta: dict) -> dict:
    doc = {k: meta[k]["valor"] for k in ("titulo", "autores", "ano", "revista")
           if isinstance(meta.get(k), dict) and meta[k].get("valor")}
    doc["descricao"] = plano["contexto_documento"]
    st = {"documento": doc, "secao": trecho["secao"],
          "paginas": f"{trecho['paginas'][0]}–{trecho['paginas'][1]}"}
    if trecho.get("contexto_anterior"):
        st["texto_imediatamente_anterior"] = trecho["contexto_anterior"]
    st["trecho"] = trecho["texto"]
    return st


def rodar(proj: Projeto, doc: str, ids: set[str] | None = None) -> dict:
    cfg = carregar_config()
    plano = ler_json(proj.plano(doc))
    planolib.validar(plano)
    meta = ler_json(proj.metadados(doc), {})
    trechos = [t for t in ler_jsonl(proj.trechos(doc)) if not ids or t["id"] in ids]
    tarefas = [{"state": estado_trecho(t, plano, meta), "questions": plano["perguntas_triagem"],
                "log": proj.log_jev(doc), "contexto": {"etapa": "triagem", "id": t["id"]}} for t in trechos]
    respostas = jev_client.perguntar_varios(tarefas)

    faixa = tuple(cfg["faixa_incerta"])
    novos = {}
    for t, r in zip(trechos, respostas):
        d = planolib.decidir(plano, r, faixa)
        novos[t["id"]] = {"id": t["id"], "secao": t["secao"], "respostas": jev_client.resumir(r),
                          "versao_plano": plano.get("versao", 1), **d}
    rev = ler_json(proj.revisao(doc), {})
    if any(i in rev for i in novos):  # revisões antigas não valem para a nova triagem
        salvar_json(proj.revisao(doc), {k: v for k, v in rev.items() if k not in novos})
    existentes = {x["id"]: x for x in ler_jsonl(proj.triagem(doc))}
    existentes.update(novos)
    ordem = [t["id"] for t in ler_jsonl(proj.trechos(doc))]
    salvar_jsonl(proj.triagem(doc), [existentes[i] for i in ordem if i in existentes])

    contagem: dict[str, int] = {}
    for d in novos.values():
        contagem[d["acao"]] = contagem.get(d["acao"], 0) + 1
    return {"trechos": len(novos), "acoes": contagem, "revisar": sum(d["revisar"] for d in novos.values())}


def pendentes(proj: Projeto, doc: str) -> dict:
    textos = {t["id"]: t for t in ler_jsonl(proj.trechos(doc))}
    feitas = ler_json(proj.revisao(doc), {})
    lista = [{"id": d["id"], "secao": d["secao"], "acao_proposta": d["acao"], "motivo": d["motivo"],
              "incerta": d["incerta"], "respostas_jev": d["respostas"], "texto": textos[d["id"]]["texto"]}
             for d in ler_jsonl(proj.triagem(doc)) if d["revisar"] and d["id"] not in feitas]
    caminho = proj.pasta("revisao") / f"{doc}.pendentes.json"
    salvar_json(caminho, lista)
    return {"pendentes": len(lista), "arquivo": str(caminho), "saida_esperada": str(proj.revisao(doc))}


def aplicar_revisao(proj: Projeto, doc: str) -> dict:
    rev = ler_json(proj.revisao(doc), {})
    triagem, faltam, mudou = ler_jsonl(proj.triagem(doc)), [], 0
    for d in triagem:
        if d["revisar"]:
            r = rev.get(d["id"])
            if not r:
                faltam.append(d["id"])
                continue
            if r["acao"] not in planolib.ACOES:
                raise SystemExit(f"revisão de {d['id']}: ação inválida '{r['acao']}'")
            d["acao_final"], d["motivo_final"], d["revisado"] = r["acao"], r.get("motivo", ""), True
            mudou += r["acao"] != d["acao"]
        else:
            d["acao_final"], d["motivo_final"], d["revisado"] = d["acao"], d["motivo"], False
    salvar_jsonl(proj.triagem(doc), triagem)
    if faltam:
        raise SystemExit(f"faltam revisões para: {', '.join(faltam)}")
    return {"revisados": sum(d["revisado"] for d in triagem), "decisoes_alteradas": mudou}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("acao", choices=["rodar", "pendentes", "aplicar-revisao"])
    ap.add_argument("doc")
    ap.add_argument("--ids")
    a = ap.parse_args()
    proj = Projeto(a.projeto)
    if a.acao == "rodar":
        print(rodar(proj, a.doc, set(a.ids.split(",")) if a.ids else None))
    elif a.acao == "pendentes":
        print(pendentes(proj, a.doc))
    else:
        print(aplicar_revisao(proj, a.doc))


if __name__ == "__main__":
    main()
