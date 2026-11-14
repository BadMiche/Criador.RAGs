"""Etapa 1 — extrai PDF/DOCX/etc. para .md, com imagens numeradas por página.

Uso:
  python extrair.py <projeto> <arquivo> [<arquivo> ...]
  python extrair.py <projeto> --aplicar-ocr <doc>     # depois que o agente OCR escreveu ocr/<doc>/pNNN.md

Saídas:
  fontes/<doc>.md                      marcadores <!-- pagina: N --> e links de imagem
  imagens/<doc>/pNNN_figMM.png         imagens (logos repetidos já removidos)
  imagens/<doc>/candidatas.json        lista para o filtro do Jev (página, legenda próxima)
  ocr/<doc>/pendentes.json             páginas digitalizadas para o agente OCR (Sonnet)
  originais/<doc>.<ext>                cópia do arquivo de entrada
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from comum import Projeto, carregar_config, ler_json, salvar_json, slug

LINK_IMG = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
LEGENDA = re.compile(r"^\s*(\*\*|_)?\s*(fig(ura)?\.?|tabela|quadro|gr[áa]fico|fluxograma|figure|table|chart)\s*\d*", re.I)
MARCA_PAGINA = "<!-- pagina: {n} -->"
MARCA_OCR = "<!-- OCR_PENDENTE pagina: {n} -->"


def extrair_pdf(proj: Projeto, arquivo: Path, doc: str, cfg: dict) -> dict:
    import pymupdf
    import pymupdf4llm

    pasta_img = proj.imagens(doc)
    tmp = pasta_img / "_bruto"
    tmp.mkdir(parents=True, exist_ok=True)
    paginas = pymupdf4llm.to_markdown(
        str(arquivo), page_chunks=True, write_images=True, image_path=str(tmp),
        image_format="png", image_size_limit=cfg["extracao"]["limite_tamanho_imagem"],
    )

    # logos/cabeçalhos: mesma imagem em várias páginas
    hashes: dict[str, set[int]] = defaultdict(set)
    for i, pg in enumerate(paginas, 1):
        for caminho in LINK_IMG.findall(pg["text"]):
            p = Path(caminho)
            if p.exists():
                hashes[hashlib.md5(p.read_bytes()).hexdigest()].add(i)
    repetidas = {h for h, pgs in hashes.items() if len(pgs) >= cfg["extracao"]["repeticao_logo"]}

    partes, candidatas, pendentes = [], [], []
    pdf = pymupdf.open(str(arquivo))
    for i, pg in enumerate(paginas, 1):
        texto = pg["text"]
        cont = 0

        def renomear(m: re.Match) -> str:
            nonlocal cont
            origem = Path(m.group(1))
            if not origem.exists():
                return ""
            if hashlib.md5(origem.read_bytes()).hexdigest() in repetidas:
                return ""
            cont += 1
            nome = f"p{i:03d}_fig{cont:02d}.png"
            shutil.move(str(origem), pasta_img / nome)
            candidatas.append({"arquivo": nome, "pagina": i, "legenda": "", "id": f"{doc} p{i} fig{cont}"})
            return f"![{doc} p{i} fig{cont}](../imagens/{doc}/{nome})"

        texto = LINK_IMG.sub(renomear, texto)
        _anotar_legendas(texto, candidatas, i)

        so_texto = LINK_IMG.sub("", texto).strip()
        if len(so_texto) < cfg["extracao"]["min_caracteres_pagina"]:
            png = proj.pasta(f"ocr/{doc}") / f"p{i:03d}.png"
            pdf[i - 1].get_pixmap(dpi=150).save(str(png))
            pendentes.append({"pagina": i, "imagem": str(png), "saida": str(png.with_suffix(".md"))})
            # página digitalizada: a "imagem" é a página inteira; o agente OCR transcreve e,
            # se houver figura importante, aponta para a imagem da página em ocr/<doc>/.
            for c in [c for c in candidatas if c["pagina"] == i]:
                (pasta_img / c["arquivo"]).unlink(missing_ok=True)
                candidatas.remove(c)
            texto = MARCA_OCR.format(n=i)
        partes.append(MARCA_PAGINA.format(n=i) + "\n" + texto.strip() + "\n")

    shutil.rmtree(tmp, ignore_errors=True)
    proj.fonte(doc).write_text("\n".join(partes), encoding="utf-8")
    salvar_json(pasta_img / "candidatas.json", candidatas)
    if pendentes:
        salvar_json(proj.pasta(f"ocr/{doc}") / "pendentes.json", pendentes)
    meta_pdf = {k: v for k, v in (pdf.metadata or {}).items() if v}
    salvar_json(proj.pasta("metadados") / f"{doc}.pdf.json", {"metadados_pdf": meta_pdf, "paginas": len(paginas)})
    return {"doc": doc, "paginas": len(paginas), "imagens": len(candidatas), "ocr_pendente": len(pendentes)}


def _anotar_legendas(texto: str, candidatas: list[dict], pagina: int) -> None:
    """Associa a cada imagem a primeira linha tipo 'Figura 3...' logo depois dela."""
    linhas = texto.splitlines()
    for idx, linha in enumerate(linhas):
        m = LINK_IMG.search(linha)
        if not m:
            continue
        nome = Path(m.group(1)).name
        for prox in linhas[idx + 1: idx + 6]:
            if LEGENDA.match(prox):
                for c in candidatas:
                    if c["arquivo"] == nome and c["pagina"] == pagina:
                        c["legenda"] = prox.strip(" *_")
                break


def extrair_outro(proj: Projeto, arquivo: Path, doc: str) -> dict:
    from markitdown import MarkItDown

    md = MarkItDown().convert(str(arquivo)).text_content
    proj.fonte(doc).write_text(md, encoding="utf-8")
    salvar_json(proj.imagens(doc) / "candidatas.json", [])
    return {"doc": doc, "paginas": None, "imagens": 0, "ocr_pendente": 0,
            "aviso": "imagens não extraídas para este formato"}


def aplicar_ocr(proj: Projeto, doc: str) -> int:
    pendentes = ler_json(proj.pasta(f"ocr/{doc}") / "pendentes.json", [])
    md = proj.fonte(doc).read_text(encoding="utf-8")
    feitos = 0
    for p in pendentes:
        saida = Path(p["saida"])
        if saida.exists():
            md = md.replace(MARCA_OCR.format(n=p["pagina"]), saida.read_text(encoding="utf-8").strip())
            feitos += 1
    proj.fonte(doc).write_text(md, encoding="utf-8")
    faltam = len(pendentes) - feitos
    print(f"OCR aplicado em {feitos} páginas; faltam {faltam}.")
    return faltam


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("arquivos", nargs="*")
    ap.add_argument("--aplicar-ocr", metavar="DOC")
    a = ap.parse_args()
    proj, cfg = Projeto(a.projeto), carregar_config()

    if a.aplicar_ocr:
        sys.exit(1 if aplicar_ocr(proj, a.aplicar_ocr) else 0)

    for arq in map(Path, a.arquivos):
        doc = slug(arq.name)
        shutil.copy2(arq, proj.pasta("originais") / f"{doc}{arq.suffix.lower()}")
        res = extrair_pdf(proj, arq, doc, cfg) if arq.suffix.lower() == ".pdf" else extrair_outro(proj, arq, doc)
        res["arquivo_original"] = arq.name
        salvar_json(proj.pasta("metadados") / f"{doc}.origem.json", res)
        print(res)


if __name__ == "__main__":
    main()
