"""Etapas 2 e 3 — filtra imagens com o Jev e aplica as descrições do Haiku.

  python imagens.py <projeto> filtrar <doc>
      Jev decide quais imagens são informativas. Descartadas vão para imagens/<doc>/descartadas/
      e o link sai do .md. Gera imagens/<doc>/indice.json.
  python imagens.py <projeto> aplicar <doc>
      Lê imagens/<doc>/descricoes.json ({arquivo: descrição}) escrito pelo agente Haiku,
      atualiza o texto alternativo dos links no .md e gera imagens/<doc>/indice.md.
"""
from __future__ import annotations

import argparse
import re
import shutil

import jev_client
from comum import Projeto, carregar_config, ler_json, salvar_json

PERGUNTAS_IMAGEM = {
    "informativa": {
        "type": "noul",
        "instructions": "Does `imagem` carry technical content a reader would study, such as a chart, table, "
                        "diagram, flowchart, anatomical drawing, clinical photo or exam image?",
        "criteria": {
            "true": "the image shows data, a process, a structure or a clinical finding",
            "false": "the image is a logo, icon, ornament, author photo, cover art or a blank/cut fragment",
        },
    },
    "decorativa": {
        "type": "noul",
        "instructions": "Is `imagem` a logo, icon, banner, ornament, advertisement or author portrait?",
    },
}


def filtrar(proj: Projeto, doc: str) -> dict:
    cfg = carregar_config()["imagens"]
    pasta = proj.imagens(doc)
    candidatas = ler_json(pasta / "candidatas.json", [])
    if not candidatas:
        salvar_json(pasta / "indice.json", [])
        return {"mantidas": 0, "descartadas": 0}

    tarefas = []
    for c in candidatas:
        ref, asset = jev_client.imagem_asset(pasta / c["arquivo"])
        tarefas.append({
            "state": {"documento": doc, "pagina": c["pagina"], "legenda": c["legenda"] or "(sem legenda)",
                      "imagem": ref},
            "questions": PERGUNTAS_IMAGEM, "assets": {ref: asset},
            "log": proj.log_jev(doc), "contexto": {"etapa": "imagens", "arquivo": c["arquivo"]},
        })
    respostas = jev_client.perguntar_varios(tarefas)

    md_path = proj.fonte(doc)
    md = md_path.read_text(encoding="utf-8")
    indice, descartadas = [], 0
    for c, r in zip(candidatas, respostas):
        inf, dec = r["informativa"]["noul"], r["decorativa"]["noul"]
        manter = inf >= cfg["informativa_min"] and dec <= cfg["decorativa_max"]
        c = {**c, "informativa": round(inf, 3), "decorativa": round(dec, 3), "mantida": manter, "descricao": ""}
        if not manter:
            descartadas += 1
            destino = pasta / "descartadas"
            destino.mkdir(exist_ok=True)
            shutil.move(str(pasta / c["arquivo"]), destino / c["arquivo"])
            md = re.sub(rf"!\[[^\]]*\]\(\.\./imagens/{re.escape(doc)}/{re.escape(c['arquivo'])}\)\n?", "", md)
        indice.append(c)
    md_path.write_text(md, encoding="utf-8")
    salvar_json(pasta / "indice.json", indice)
    return {"mantidas": len(indice) - descartadas, "descartadas": descartadas}


def aplicar(proj: Projeto, doc: str) -> dict:
    pasta = proj.imagens(doc)
    indice = ler_json(pasta / "indice.json", [])
    descricoes = ler_json(pasta / "descricoes.json", {})
    md_path = proj.fonte(doc)
    md = md_path.read_text(encoding="utf-8")
    linhas = ["# Imagens — " + doc, "", "| Arquivo | Página | Legenda original | Descrição |", "|---|---|---|---|"]
    for c in indice:
        if not c["mantida"]:
            continue
        desc = " ".join(descricoes.get(c["arquivo"], "").split())
        c["descricao"] = desc
        alt = f"{c['id']} — {desc}" if desc else c["id"]
        alt = alt.replace("[", "(").replace("]", ")")
        md = re.sub(rf"!\[[^\]]*\]\((\.\./imagens/{re.escape(doc)}/{re.escape(c['arquivo'])})\)",
                    lambda m: f"![{alt}]({m.group(1)})", md)
        linhas.append(f"| [{c['arquivo']}]({c['arquivo']}) | {c['pagina']} | {c['legenda']} | {desc} |")
    md_path.write_text(md, encoding="utf-8")
    salvar_json(pasta / "indice.json", indice)
    (pasta / "indice.md").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    sem = [c["arquivo"] for c in indice if c["mantida"] and not c["descricao"]]
    return {"descritas": sum(1 for c in indice if c["descricao"]), "sem_descricao": sem}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("acao", choices=["filtrar", "aplicar"])
    ap.add_argument("doc")
    a = ap.parse_args()
    proj = Projeto(a.projeto)
    print((filtrar if a.acao == "filtrar" else aplicar)(proj, a.doc))


if __name__ == "__main__":
    main()
