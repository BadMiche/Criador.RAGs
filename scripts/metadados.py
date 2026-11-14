"""Etapa 4 — metadados de origem: código coleta candidatos, Jev seleciona, Haiku completa o resto.

  python metadados.py <projeto> selecionar <doc>
      Gera metadados/<doc>.json com cada campo: {valor, fonte: pdf|regex|jev|pendente, p}.
      Campos 'pendente' ficam para o agente metadados-haiku.
  python metadados.py <projeto> aplicar <doc>
      Grava os metadados como frontmatter YAML no topo de fontes/<doc>.md.
"""
from __future__ import annotations

import argparse
import re

import jev_client
from comum import (Projeto, carregar_config, juntar_frontmatter, ler_json, salvar_json,
                   separar_frontmatter)

DOI = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+", re.I)
ANO = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
ISSN = re.compile(r"\bISSN[:\s]*([0-9]{4}-[0-9]{3}[0-9Xx])\b")
EDICAO = re.compile(r"\b(\d{1,2})\s*(ª|a\.?|º)?\s*(ed\.?|edi[çc][ãa]o|edition)\b", re.I)
LIMPA = re.compile(r"<!--.*?-->|!\[[^\]]*\]\([^)]*\)|[#*_`>|]")

# Campo -> (o que o Jev deve encontrar entre as linhas candidatas)
CAMPOS_TEXTO = {
    "titulo": "the title of this document",
    "autores": "the names of the authors of this document",
    "revista": "the name of the journal, book or publisher this document comes from",
}


def linhas_candidatas(md: str, n: int) -> list[str]:
    vistas, out = set(), []
    for l in md.splitlines():
        l = " ".join(LIMPA.sub(" ", l).split())
        if 3 <= len(l) <= 300 and l.lower() not in vistas:
            vistas.add(l.lower())
            out.append(l)
        if len(out) >= n:
            break
    return out


def nomes_opcoes(linhas: list[str]) -> dict[str, str]:
    """Nome de opção descritivo (o Jev lê o nome): início da própria linha, único."""
    out: dict[str, str] = {}
    for l in linhas:
        base = re.sub(r"\W+", "_", " ".join(l.split()[:8]), flags=re.U).strip("_")[:60] or "linha"
        nome, n = base, 2
        while nome in out:
            nome, n = f"{base}_{n}", n + 1
        out[nome] = l
    return out


def selecionar(proj: Projeto, doc: str) -> dict:
    cfg = carregar_config()["metadados"]
    _, md = separar_frontmatter(proj.fonte(doc).read_text(encoding="utf-8"))
    pdf = ler_json(proj.pasta("metadados") / f"{doc}.pdf.json", {}).get("metadados_pdf", {})
    origem = ler_json(proj.pasta("metadados") / f"{doc}.origem.json", {})
    inicio = md[:8000]
    linhas = linhas_candidatas(inicio, cfg["linhas_candidatas"])

    meta: dict[str, dict] = {"arquivo": {"valor": origem.get("arquivo_original", doc), "fonte": "arquivo"}}

    # regex: DOI, ISSN, edição (valores exatos -> código)
    for campo, rx in (("doi", DOI), ("issn", ISSN), ("edicao", EDICAO)):
        m = rx.search(inicio)
        meta[campo] = ({"valor": (m.group(1) if campo != "doi" else m.group(0)).rstrip(".,;"), "fonte": "regex"}
                       if m else {"valor": None, "fonte": "pendente"})

    # Jev: escolher entre linhas candidatas (selecionar em vez de gerar) + Noul companheiro
    questions = {}
    opcoes = nomes_opcoes(linhas)
    for campo, alvo in CAMPOS_TEXTO.items():
        questions[f"{campo}_qual"] = {
            "type": "choice",
            "instructions": f"Which line of `inicio_documento` states {alvo}?",
            "criteria": opcoes,
        }
        questions[f"{campo}_existe"] = {
            "type": "noul",
            "instructions": f"Does any line of `inicio_documento` state {alvo}?",
        }
    anos = sorted(set(ANO.findall(inicio)))
    if len(anos) > 1:
        questions["ano_qual"] = {
            "type": "choice",
            "instructions": "Which year is the publication year of this document?",
            "criteria": {f"ano_{a}": f"published in {a}" for a in anos},
        }

    if linhas:
        state = {"arquivo": meta["arquivo"]["valor"], "metadados_pdf": pdf or "(vazio)",
                 "inicio_documento": opcoes}
        r = jev_client.perguntar(state, questions, log=proj.log_jev(doc), contexto={"etapa": "metadados"})
        for campo in CAMPOS_TEXTO:
            existe = r[f"{campo}_existe"]["noul"]
            escolha = r[f"{campo}_qual"]
            if existe >= cfg["aceitar_min"]:
                meta[campo] = {"valor": opcoes[escolha["choice"]], "fonte": "jev", "p": round(existe, 3),
                               "confianca": round(escolha["confidence"], 3)}
            else:
                meta[campo] = {"valor": None, "fonte": "pendente", "p": round(existe, 3)}
        if "ano_qual" in r:
            meta["ano"] = {"valor": int(r["ano_qual"]["choice"].split("_")[1]), "fonte": "jev",
                           "confianca": round(r["ano_qual"]["confidence"], 3)}
    for campo in CAMPOS_TEXTO:
        meta.setdefault(campo, {"valor": None, "fonte": "pendente"})
    if "ano" not in meta:
        meta["ano"] = {"valor": int(anos[0]), "fonte": "regex"} if anos else {"valor": None, "fonte": "pendente"}

    # metadados internos do PDF completam lacunas
    for campo, chave in (("titulo", "title"), ("autores", "author")):
        if meta[campo]["fonte"] == "pendente" and pdf.get(chave):
            meta[campo] = {"valor": pdf[chave], "fonte": "pdf"}

    meta["pendentes"] = [k for k, v in meta.items() if isinstance(v, dict) and v.get("fonte") == "pendente"]
    salvar_json(proj.metadados(doc), meta)
    return {"pendentes": meta["pendentes"]}


def aplicar(proj: Projeto, doc: str) -> dict:
    meta = ler_json(proj.metadados(doc), {})
    front = {k: v["valor"] for k, v in meta.items() if isinstance(v, dict) and v.get("valor") not in (None, "")}
    caminho = proj.fonte(doc)
    _, corpo = separar_frontmatter(caminho.read_text(encoding="utf-8"))
    caminho.write_text(juntar_frontmatter(front, corpo), encoding="utf-8")
    return front


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("acao", choices=["selecionar", "aplicar"])
    ap.add_argument("doc")
    a = ap.parse_args()
    proj = Projeto(a.projeto)
    print((selecionar if a.acao == "selecionar" else aplicar)(proj, a.doc))


if __name__ == "__main__":
    main()
