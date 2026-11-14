"""Etapas 8–10 — controle do loop enxugar ↔ verificar.

  python verificar.py <projeto> pendentes <doc>
      Gera enxuto/<doc>/_pendentes.json com os trechos que o agente Haiku deve (re)enxugar,
      incluindo o feedback específico da tentativa anterior. Saída do Haiku: enxuto/<doc>/<id>.json
      = {"fatos_chave": [...], "condensado": "..."}
  python verificar.py <projeto> rodar <doc>
      Código (números com unidade) + Jev (1 Noul por fato-chave, invenção, omissão, exigências do plano).
      Status por trecho: aprovado | refazer | esgotado (falhou além de max_voltas).
  python verificar.py <projeto> esgotados <doc>
      Lista os trechos esgotados para o diagnóstico (Opus) e quantos redesenhos já foram feitos.
  python verificar.py <projeto> reiniciar <doc> --ids t0003,t0007
      Depois de um novo plano do Opus: zera o histórico desses trechos (conta 1 redesenho).
  python verificar.py <projeto> manter-original <doc>
      Desiste dos esgotados: o texto original é mantido e isso fica registrado.
"""
from __future__ import annotations

import argparse
import hashlib
import re

import jev_client
import plano as planolib
from comum import Projeto, carregar_config, ler_json, ler_jsonl, salvar_json

UNIDADES = r"(?:%|mg|mcg|µg|ug|g|kg|ml|mL|l|L|mmHg|mEq|mmol|UI|U|bpm|irpm|cm|mm|°C|h|min|dias?|anos?|meses|semanas)"
NUM_UNID = re.compile(rf"(?<![\w.,])(\d+(?:[.,]\d+)?(?:\s*[-–a]\s*\d+(?:[.,]\d+)?)?)\s*({UNIDADES})(?!\w)")
LINK = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def numeros(texto: str) -> set[str]:
    """Números com unidade, normalizados. Faixas ("50 a 74 anos") também contam cada ponta,
    para que "50 anos e 74 anos" e "50 a 74 anos" sejam equivalentes."""
    texto = LINK.sub(" ", texto)
    out = set()
    for n, u in NUM_UNID.findall(texto):
        n, u = re.sub(r"\s+", "", n).replace(",", ".").replace("–", "-"), u.lower()
        pontas = re.split(r"-|a", n)
        out.add(f"{n}{u}" if len(pontas) == 1 else f"{pontas[0]}-{pontas[1]}{u}")
        out.update(f"{p}{u}" for p in pontas if p)
    return out


def _hash(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:12]


def _estado(proj: Projeto, doc: str) -> dict:
    return ler_json(proj.verificacao(doc), {"_redesenhos": 0})


def _para_enxugar(proj: Projeto, doc: str) -> list[dict]:
    triagem = ler_jsonl(proj.triagem(doc))
    if triagem and "acao_final" not in triagem[0]:
        raise SystemExit("rode 'triagem.py aplicar-revisao' antes.")
    return [d for d in triagem if d["acao_final"] == "enxugar"]


def pendentes(proj: Projeto, doc: str) -> dict:
    plano, est = ler_json(proj.plano(doc)), _estado(proj, doc)
    textos = {t["id"]: t for t in ler_jsonl(proj.trechos(doc))}
    lista = []
    for d in _para_enxugar(proj, doc):
        s = est.get(d["id"], {})
        if s.get("status") in ("aprovado", "esgotado", "mantido_original"):
            continue
        item = {"id": d["id"], "secao": d["secao"], "original": textos[d["id"]]["texto"],
                "saida": str(proj.enxuto(doc) / f"{d['id']}.json")}
        if s.get("status") == "refazer":
            ult = s["historico"][-1]
            item["tentativa_anterior"] = ult["condensado"]
            item["fatos_chave_fixos"] = s.get("fatos_chave", [])
            item["feedback"] = ult["falhas"]
        lista.append(item)
    proj.enxuto(doc).mkdir(parents=True, exist_ok=True)
    salvar_json(proj.enxuto(doc) / "_pendentes.json",
                {"instrucoes": plano["enxugamento"]["instrucoes"],
                 "fatos_chave": plano["enxugamento"]["fatos_chave"], "trechos": lista})
    return {"pendentes": len(lista), "arquivo": str(proj.enxuto(doc) / "_pendentes.json")}


def perguntas_verificacao(fatos: list[str], plano: dict) -> dict:
    q = {
        "inventa": {"type": "noul",
                    "instructions": "Does `condensado` state any fact, number or recommendation that `original` does not state?",
                    "criteria": {"true": "condensado adds or changes information",
                                 "false": "everything in condensado is stated in original"}},
        "omite": {"type": "noul",
                  "instructions": "Does `original` state a recommendation, criterion, dose or result that `condensado` leaves out?",
                  "criteria": {"true": "a piece of practical or technical information from original is missing",
                               "false": "condensado keeps every recommendation, criterion, dose and result"}},
    }
    for i, f in enumerate(fatos):
        q[f"fato_{i:02d}"] = {"type": "noul",
                              "instructions": f"Does `condensado` state this fact from `original`: «{f}»?",
                              "criteria": {"true": "condensado states this fact, possibly in other words",
                                           "false": "the fact is missing from condensado or was changed"}}
    q.update(plano.get("perguntas_verificacao") or {})
    return q


def rodar(proj: Projeto, doc: str) -> dict:
    cfg = carregar_config()
    vc = cfg["verificacao"]
    plano, est = ler_json(proj.plano(doc)), _estado(proj, doc)
    textos = {t["id"]: t for t in ler_jsonl(proj.trechos(doc))}

    alvos = []
    for d in _para_enxugar(proj, doc):
        s = est.get(d["id"], {})
        saida = ler_json(proj.enxuto(doc) / f"{d['id']}.json")
        if s.get("status") in ("aprovado", "esgotado", "mantido_original") or not saida:
            continue
        if s.get("historico") and s["historico"][-1]["hash"] == _hash(saida["condensado"]):
            continue  # o Haiku ainda não reescreveu
        alvos.append((d["id"], saida))

    # Fatos-chave congelados na 1ª tentativa: o Haiku não pode encurtar a própria checklist depois.
    for i, s in alvos:
        st = est.setdefault(i, {"tentativas": 0, "historico": []})
        st.setdefault("fatos_chave", list(s.get("fatos_chave", [])))
        s["fatos_chave"] = st["fatos_chave"]

    tarefas = [{"state": {"original": textos[i]["texto"], "condensado": s["condensado"]},
                "questions": perguntas_verificacao(s["fatos_chave"], plano),
                "log": proj.log_jev(doc), "contexto": {"etapa": "verificacao", "id": i}} for i, s in alvos]
    respostas = jev_client.perguntar_varios(tarefas) if tarefas else []

    resumo = {"aprovado": 0, "refazer": 0, "esgotado": 0}
    for (tid, saida), r in zip(alvos, respostas):
        falhas = []
        orig, cond = textos[tid]["texto"], saida["condensado"]
        for n in sorted(n for n in numeros(orig) - numeros(cond) if "-" not in n):
            falhas.append(f"número/dose ausente: {n}")
        for i, f in enumerate(saida["fatos_chave"]):
            p = r[f"fato_{i:02d}"]["noul"]
            if p < vc["fato_min"]:
                falhas.append(f"fato-chave ausente ou alterado (p={p:.2f}): {f}")
        if r["inventa"]["noul"] > vc["inventa_max"]:
            falhas.append(f"o condensado afirma algo que o original não diz (p={r['inventa']['noul']:.2f})")
        if r["omite"]["noul"] > vc["omite_max"]:
            falhas.append(f"o condensado deixou de fora recomendação/critério/dose/resultado (p={r['omite']['noul']:.2f})")
        falhas += [f"exigência do plano: {m}" for m in planolib.exigencias_falhas(plano, r)]
        if len(cond) >= len(orig) and len(orig) > 200:  # um título solto não tem como encolher
            falhas.append("o condensado não ficou menor que o original")

        s = est[tid]
        s["historico"].append({"hash": _hash(cond), "condensado": cond, "falhas": falhas,
                               "respostas": jev_client.resumir(r), "versao_plano": plano.get("versao", 1)})
        if not falhas:
            s["status"] = "aprovado"
        else:
            s["tentativas"] += 1
            s["status"] = "esgotado" if s["tentativas"] > vc["max_voltas"] else "refazer"
        resumo[s["status"]] += 1
    salvar_json(proj.verificacao(doc), est)
    return {"verificados": len(alvos), **resumo}


def esgotados(proj: Projeto, doc: str) -> dict:
    est, vc = _estado(proj, doc), carregar_config()["verificacao"]
    ids = [k for k, v in est.items() if isinstance(v, dict) and v.get("status") == "esgotado"]
    return {"esgotados": ids, "redesenhos_feitos": est.get("_redesenhos", 0),
            "pode_redesenhar": est.get("_redesenhos", 0) < vc["max_redesenhos"]}


def reiniciar(proj: Projeto, doc: str, ids: list[str], tudo: bool = False) -> dict:
    """ids: só esses trechos (plano mudou perguntas/enxugamento). tudo: a divisão mudou e os ids
    deixam de valer — arquiva triagem/revisão/verificação/enxuto do documento para refazer do passo 6."""
    est, vc = _estado(proj, doc), carregar_config()["verificacao"]
    if est.get("_redesenhos", 0) >= vc["max_redesenhos"]:
        raise SystemExit("limite de redesenhos atingido — use 'manter-original'.")
    est["_redesenhos"] = est.get("_redesenhos", 0) + 1
    if tudo:
        import shutil
        arq = proj.pasta(f"arquivo/{doc}_v{est['_redesenhos']}")
        for p in (proj.triagem(doc), proj.revisao(doc), proj.verificacao(doc), proj.trechos(doc)):
            if p.exists():
                shutil.move(str(p), arq / p.name)
        if proj.enxuto(doc).exists():
            shutil.move(str(proj.enxuto(doc)), arq / "enxuto")
        salvar_json(proj.verificacao(doc), {"_redesenhos": est["_redesenhos"]})
        return {"reiniciado": "documento inteiro", "arquivado_em": str(arq), "redesenhos": est["_redesenhos"]}
    for i in ids:
        if i in est:
            est.setdefault("_arquivo", {})[i] = est.pop(i)  # guarda histórico antigo para auditoria
        (proj.enxuto(doc) / f"{i}.json").unlink(missing_ok=True)
    salvar_json(proj.verificacao(doc), est)
    return {"reiniciados": ids, "redesenhos": est["_redesenhos"]}


def manter_original(proj: Projeto, doc: str) -> dict:
    est = _estado(proj, doc)
    ids = [k for k, v in est.items() if isinstance(v, dict) and v.get("status") == "esgotado"]
    for i in ids:
        est[i]["status"] = "mantido_original"
    salvar_json(proj.verificacao(doc), est)
    return {"mantidos_originais": ids}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("acao", choices=["pendentes", "rodar", "esgotados", "reiniciar", "manter-original"])
    ap.add_argument("doc")
    ap.add_argument("--ids", default="")
    ap.add_argument("--tudo", action="store_true")
    a = ap.parse_args()
    proj = Projeto(a.projeto)
    fn = {"pendentes": pendentes, "rodar": rodar, "esgotados": esgotados, "manter-original": manter_original}
    if a.acao == "reiniciar":
        ids = [i for i in a.ids.split(",") if i]
        if not ids and not a.tudo:
            raise SystemExit("informe --ids ou --tudo")
        print(reiniciar(proj, a.doc, ids, a.tudo))
    else:
        print(fn[a.acao](proj, a.doc))


if __name__ == "__main__":
    main()
