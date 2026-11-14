"""Etapa 11 (apoio) — monta o .md limpo e o relatório do que foi removido/enxugado.

  python montar.py <projeto> <doc>
      limpo/<doc>.md       frontmatter + trechos finais na ordem (descartados saem;
                           enxugados aprovados entram condensados; o resto entra original)
      relatorio/<doc>.json contagens, tokens antes/depois, removidos por motivo, imagens
"""
from __future__ import annotations

import argparse

from comum import (Projeto, estimar_tokens, juntar_frontmatter, ler_json, ler_jsonl, salvar_json,
                   separar_frontmatter)
from dividir import HEADING


def montar(proj: Projeto, doc: str) -> dict:
    meta, _ = separar_frontmatter(proj.fonte(doc).read_text(encoding="utf-8"))
    trechos = {t["id"]: t for t in ler_jsonl(proj.trechos(doc))}
    triagem = ler_jsonl(proj.triagem(doc))
    if any("acao_final" not in d for d in triagem):
        raise SystemExit("triagem sem acao_final — rode 'triagem.py aplicar-revisao'.")
    verif = ler_json(proj.verificacao(doc), {})

    partes, removidos, uso = [], [], {"mantido": 0, "enxugado": 0, "descartado": 0, "enxugo_falhou": 0}
    tok_antes = tok_depois = 0
    for d in triagem:
        t = trechos[d["id"]]
        tok_antes += t["tokens"]
        if d["acao_final"] == "descartar":
            uso["descartado"] += 1
            removidos.append({"id": d["id"], "secao": d["secao"], "motivo": d["motivo_final"],
                              "tokens": t["tokens"], "inicio": " ".join(t["texto"].split())[:120]})
            continue
        texto = t["texto"]
        if d["acao_final"] == "enxugar":
            s = verif.get(d["id"], {})
            if s.get("status") == "aprovado":
                texto = s["historico"][-1]["condensado"].strip()
                primeira = t["texto"].splitlines()[0]
                if HEADING.match(primeira) and not texto.startswith(primeira):
                    texto = f"{primeira}\n\n{texto}"
                uso["enxugado"] += 1
            else:
                uso["enxugo_falhou"] += 1
        else:
            uso["mantido"] += 1
        tok_depois += estimar_tokens(texto)
        partes.append(f"<!-- trecho: {d['id']} | paginas: {t['paginas'][0]}-{t['paginas'][1]} -->\n{texto}")

    proj.limpo(doc).write_text(juntar_frontmatter(meta, "\n\n".join(partes) + "\n"), encoding="utf-8")

    por_motivo: dict[str, dict] = {}
    for r in removidos:
        m = por_motivo.setdefault(r["motivo"] or "sem motivo", {"trechos": 0, "tokens": 0, "secoes": []})
        m["trechos"] += 1
        m["tokens"] += r["tokens"]
        if r["secao"] not in m["secoes"]:
            m["secoes"].append(r["secao"])
    imgs = ler_json(proj.imagens(doc) / "indice.json", [])
    rel = {"documento": doc, "metadados": meta, "trechos": uso, "tokens_antes": tok_antes,
           "tokens_depois": tok_depois,
           "reducao_pct": round(100 * (1 - tok_depois / tok_antes), 1) if tok_antes else 0,
           "removidos_por_motivo": por_motivo, "removidos": removidos,
           "imagens": {"mantidas": sum(1 for i in imgs if i.get("mantida")),
                       "descartadas": sum(1 for i in imgs if not i.get("mantida"))},
           "redesenhos_do_plano": verif.get("_redesenhos", 0)}
    salvar_json(proj.relatorio(doc), rel)
    return {k: rel[k] for k in ("trechos", "tokens_antes", "tokens_depois", "reducao_pct")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("doc")
    a = ap.parse_args()
    print(montar(Projeto(a.projeto), a.doc))


if __name__ == "__main__":
    main()
