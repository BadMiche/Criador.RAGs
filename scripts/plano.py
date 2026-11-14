"""Plano de cada documento (escrito pelo agente planejador Opus) — schema, validação e motor de regras.

  python plano.py validar <plano.json>

Formato (resumo; exemplo completo em docs/exemplo_plano.json):
{
  "versao": 1,
  "perfil": "artigo de revisão em cardiologia",
  "contexto_documento": "fatos que o Jev precisa saber sobre o documento (vai no state)",
  "divisao": {"nivel_heading": 2, "max_tokens": 1500, "min_tokens": 150,
              "unir_pequenas": true, "sobreposicao_paragrafos": 0, "observacoes": "..."},
  "perguntas_triagem": {"<id>": {"type": "noul|choice|score", "instructions": "...", "criteria": ...}},
  "regras": [{"se": [{"q": "<id>", "op": ">", "v": 0.7}], "acao": "descartar|manter|enxugar", "motivo": "..."}],
  "acao_padrao": "manter",
  "enxugamento": {"instrucoes": "...", "fatos_chave": "o que conta como fato-chave neste documento"},
  "perguntas_verificacao": {"<id>": {...}},          # opcional: feitas sobre {original, condensado}
  "exigencias_verificacao": [{"q": "<id>", "op": "<", "v": 0.3, "motivo": "..."}],  # opcional
  "justificativa": "por que essas perguntas/divisão"
}
Condições: noul -> probabilidade; score -> score (0..n-1); choice -> opção escolhida (op "==" / "!=")
ou, com "opcao", a probabilidade daquela opção. Regras: a primeira que casa decide.
"""
from __future__ import annotations

import json
import sys

ACOES = {"descartar", "manter", "enxugar"}
OPS = {">", ">=", "<", "<=", "==", "!="}
TIPOS = {"noul", "choice", "score"}


class PlanoInvalido(ValueError):
    pass


def validar_perguntas(perguntas: dict, onde: str) -> list[str]:
    erros = []
    if not isinstance(perguntas, dict) or not perguntas:
        return [f"{onde}: precisa ser um objeto com ao menos 1 pergunta"]
    for qid, q in perguntas.items():
        p = f"{onde}.{qid}"
        if not isinstance(q, dict):
            erros.append(f"{p}: precisa ser objeto")
            continue
        if q.get("type") not in TIPOS:
            erros.append(f"{p}: type deve ser um de {sorted(TIPOS)}")
        if not q.get("instructions"):
            erros.append(f"{p}: instructions vazio")
        c = q.get("criteria")
        if q.get("type") == "choice":
            if not isinstance(c, dict) or len(c) < 2:
                erros.append(f"{p}: choice precisa de criteria com >= 2 opções")
        elif q.get("type") == "score":
            if not isinstance(c, list) or not 2 <= len(c) <= 10:
                erros.append(f"{p}: score precisa de criteria com 2 a 10 níveis")
        elif q.get("type") == "noul" and c is not None:
            if not isinstance(c, dict) or not set(c) <= {"true", "false"}:
                erros.append(f"{p}: criteria do noul só aceita 'true' e 'false'")
    return erros


def _validar_condicao(cond: dict, perguntas: dict, onde: str) -> list[str]:
    q = perguntas.get(cond.get("q"))
    if q is None:
        return [f"{onde}: pergunta '{cond.get('q')}' não existe"]
    if cond.get("op") not in OPS:
        return [f"{onde}: op deve ser um de {sorted(OPS)}"]
    v = cond.get("v")
    if q["type"] == "choice" and "opcao" not in cond:
        if cond["op"] not in ("==", "!=") or v not in q["criteria"]:
            return [f"{onde}: choice sem 'opcao' exige op ==/!= e v entre {list(q['criteria'])}"]
    elif q["type"] == "choice" and cond["opcao"] not in q["criteria"]:
        return [f"{onde}: opcao '{cond['opcao']}' não existe"]
    elif not isinstance(v, (int, float)):
        return [f"{onde}: v precisa ser número"]
    return []


def validar(plano: dict) -> None:
    erros = []
    for campo in ("perfil", "contexto_documento", "divisao", "perguntas_triagem", "regras",
                  "acao_padrao", "enxugamento"):
        if campo not in plano:
            erros.append(f"falta '{campo}'")
    if erros:
        raise PlanoInvalido("; ".join(erros))

    d = plano["divisao"]
    if not 1 <= int(d.get("nivel_heading", 0)) <= 6:
        erros.append("divisao.nivel_heading deve ser 1..6")
    if not 200 <= int(d.get("max_tokens", 0)) <= 8000:
        erros.append("divisao.max_tokens deve ser 200..8000")
    if int(d.get("min_tokens", 0)) >= int(d.get("max_tokens", 1)):
        erros.append("divisao.min_tokens deve ser menor que max_tokens")

    pt = plano["perguntas_triagem"]
    erros += validar_perguntas(pt, "perguntas_triagem")
    if plano["acao_padrao"] not in ACOES:
        erros.append(f"acao_padrao deve ser um de {sorted(ACOES)}")
    for i, r in enumerate(plano["regras"]):
        if r.get("acao") not in ACOES:
            erros.append(f"regras[{i}].acao inválida")
        if not r.get("se"):
            erros.append(f"regras[{i}].se vazio")
        for j, c in enumerate(r.get("se", [])):
            if isinstance(pt, dict):
                erros += _validar_condicao(c, pt, f"regras[{i}].se[{j}]")

    e = plano["enxugamento"]
    if not e.get("instrucoes") or not e.get("fatos_chave"):
        erros.append("enxugamento precisa de 'instrucoes' e 'fatos_chave'")

    pv = plano.get("perguntas_verificacao")
    if pv:
        erros += validar_perguntas(pv, "perguntas_verificacao")
        for j, c in enumerate(plano.get("exigencias_verificacao", [])):
            erros += _validar_condicao(c, pv, f"exigencias_verificacao[{j}]")
    elif plano.get("exigencias_verificacao"):
        erros.append("exigencias_verificacao sem perguntas_verificacao")
    if erros:
        raise PlanoInvalido("; ".join(erros))


# ---- motor de regras ----

def _valor(cond: dict, resposta: dict) -> float | str:
    if resposta["type"] == "choice":
        return resposta["probabilities"][cond["opcao"]] if "opcao" in cond else resposta["choice"]
    return resposta["noul"] if resposta["type"] == "noul" else resposta["score"]


def _compara(a, op: str, b) -> bool:
    if op == "==":
        return a == b
    if op == "!=":
        return a != b
    return {">": a > b, ">=": a >= b, "<": a < b, "<=": a <= b}[op]


def condicao_ok(cond: dict, respostas: dict) -> bool:
    return _compara(_valor(cond, respostas[cond["q"]]), cond["op"], cond["v"])


def _incerta(cond: dict, respostas: dict, faixa: tuple[float, float]) -> bool:
    r = respostas[cond["q"]]
    if r["type"] == "noul" or (r["type"] == "choice" and "opcao" in cond):
        return faixa[0] < _valor(cond, r) < faixa[1]
    return False


def decidir(plano: dict, respostas: dict, faixa: tuple[float, float]) -> dict:
    """Aplica as regras (a primeira que casa decide) e marca se a decisão é incerta."""
    acao, motivo, regra = plano["acao_padrao"], "padrão", None
    for i, r in enumerate(plano["regras"]):
        if all(condicao_ok(c, respostas) for c in r["se"]):
            acao, motivo, regra = r["acao"], r.get("motivo", ""), i
            break
    # incerta = alguma resposta usada pelas regras está na faixa "não decidido": a decisão poderia virar
    incerta = any(_incerta(c, respostas, faixa) for r in plano["regras"] for c in r["se"])
    return {"acao": acao, "motivo": motivo, "regra": regra, "incerta": incerta,
            "revisar": incerta or acao == "descartar"}


def exigencias_falhas(plano: dict, respostas: dict) -> list[str]:
    return [c.get("motivo", f"{c['q']} {c['op']} {c['v']}")
            for c in plano.get("exigencias_verificacao", []) if not condicao_ok(c, respostas)]


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "validar":
        sys.exit("uso: python plano.py validar <plano.json>")
    with open(sys.argv[2], encoding="utf-8") as f:
        try:
            validar(json.load(f))
        except PlanoInvalido as e:
            sys.exit(f"PLANO INVÁLIDO: {e}")
    print("plano válido")
