"""Etapas 5 (apoio) e 6 — esqueleto do .md para o planejador e divisão em trechos.

  python dividir.py <projeto> esqueleto <doc>   -> imprime o esqueleto (títulos, páginas, tokens, amostras)
  python dividir.py <projeto> dividir <doc>     -> trechos/<doc>.jsonl seguindo plano/<doc>.json["divisao"]

Cada trecho: {id, secao, paginas, texto, tokens, contexto_anterior}
'contexto_anterior' (sobreposição) só vai para o state do Jev; não entra no texto montado.
"""
from __future__ import annotations

import argparse
import re

from comum import Projeto, carregar_config, estimar_tokens, ler_json, salvar_jsonl, separar_frontmatter

HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
PAGINA = re.compile(r"<!-- pagina: (\d+) -->")
FRASE = re.compile(r"(?<=[.!?;])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9(])")


def blocos(md: str) -> list[dict]:
    """Quebra o .md em blocos (parágrafos/tabelas/listas/títulos), com página e caminho de títulos."""
    pagina, caminho, out, buf = 1, [], [], []

    def fecha():
        if buf:
            texto = "\n".join(buf).strip()
            if texto:
                out.append({"texto": texto, "pagina": pagina, "caminho": list(caminho), "nivel": None})
            buf.clear()

    for linha in md.splitlines():
        m = PAGINA.fullmatch(linha.strip())
        if m:
            fecha()
            pagina = int(m.group(1))
            continue
        h = HEADING.match(linha)
        if h:
            fecha()
            nivel = len(h.group(1))
            caminho[:] = [c for c in caminho if c[0] < nivel] + [(nivel, h.group(2).strip("* "))]
            out.append({"texto": linha.strip(), "pagina": pagina, "caminho": list(caminho), "nivel": nivel})
            continue
        if not linha.strip():
            fecha()
        else:
            buf.append(linha)
    fecha()
    return out


def secoes(bs: list[dict], nivel_corte: int) -> list[list[dict]]:
    grupos, atual = [], []
    for b in bs:
        if b["nivel"] is not None and b["nivel"] <= nivel_corte and atual:
            grupos.append(atual)
            atual = []
        atual.append(b)
    if atual:
        grupos.append(atual)
    return grupos


def _quebrar_bloco(b: dict, max_tok: int) -> list[dict]:
    if estimar_tokens(b["texto"]) <= max_tok or b["texto"].lstrip().startswith("|"):
        return [b]
    partes, buf = [], ""
    for frase in FRASE.split(b["texto"]):
        if buf and estimar_tokens(buf + " " + frase) > max_tok:
            partes.append(buf)
            buf = frase
        else:
            buf = f"{buf} {frase}".strip()
    if buf:
        partes.append(buf)
    return [{**b, "texto": p} for p in partes]


def dividir_md(md: str, divisao: dict) -> list[dict]:
    _, corpo = separar_frontmatter(md)
    max_tok, min_tok = int(divisao["max_tokens"]), int(divisao.get("min_tokens", 0))
    sobre = int(divisao.get("sobreposicao_paragrafos", 0))
    def tok(bs: list[dict]) -> int:
        return estimar_tokens("\n\n".join(x["texto"] for x in bs))

    trechos = []
    # Nunca mistura seções do nível de corte (ex.: "Agradecimentos" não se junta a "Tratamento"),
    # para a triagem julgar cada assunto separadamente.
    for sec in secoes(blocos(corpo), int(divisao["nivel_heading"])):
        bs = [p for b in sec for p in _quebrar_bloco(b, max_tok)]
        pedacos: list[list[dict]] = []
        atual: list[dict] = []
        for b in bs:
            if atual and tok(atual + [b]) > max_tok:
                pedacos.append(atual)
                atual = []
            atual.append(b)
        if atual:
            pedacos.append(atual)
        # sobra pequena no fim da seção volta para o pedaço anterior, se couber com folga
        if divisao.get("unir_pequenas", True) and len(pedacos) > 1 and tok(pedacos[-1]) < min_tok \
                and tok(pedacos[-2] + pedacos[-1]) <= max_tok * 1.2:
            pedacos[-2] += pedacos.pop()
        trechos += pedacos

    out = []
    for i, t in enumerate(trechos, 1):
        texto = "\n\n".join(b["texto"] for b in t)
        ant = trechos[i - 2][-sobre:] if sobre and i > 1 else []
        caminho = t[0]["caminho"]
        out.append({
            "id": f"t{i:04d}",
            "secao": " > ".join(c[1] for c in caminho) or "(sem título)",
            "paginas": [t[0]["pagina"], t[-1]["pagina"]],
            "texto": texto,
            "tokens": estimar_tokens(texto),
            "contexto_anterior": "\n\n".join(b["texto"] for b in ant),
        })
    return out


def esqueleto(md: str, amostra: int) -> str:
    _, corpo = separar_frontmatter(md)
    bs = blocos(corpo)
    total = estimar_tokens(corpo)
    linhas = [f"# Esqueleto ({total} tokens estimados, {len(bs)} blocos)", ""]
    idx_titulos = [i for i, b in enumerate(bs) if b["nivel"] is not None]
    if not idx_titulos:
        linhas.append("(nenhum título Markdown encontrado — a divisão terá de ser por parágrafos)")
    for k, i in enumerate(idx_titulos):
        fim = idx_titulos[k + 1] if k + 1 < len(idx_titulos) else len(bs)
        conteudo = [b["texto"] for b in bs[i + 1:fim]]
        tok = estimar_tokens("\n\n".join(conteudo)) if conteudo else 0
        b = bs[i]
        linhas.append(f"{'  ' * (b['nivel'] - 1)}- {b['texto']}  (p. {b['pagina']}, {tok} tokens, {len(conteudo)} blocos)")
        if conteudo:
            linhas.append(f"{'  ' * b['nivel']}> {' '.join(conteudo[0].split())[:amostra]}")
    inicio = [b["texto"] for b in bs[: (idx_titulos[0] if idx_titulos else 5)]]
    if inicio:
        linhas += ["", "## Texto antes do primeiro título", " ".join(" ".join(inicio).split())[: amostra * 2]]
    return "\n".join(linhas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("acao", choices=["esqueleto", "dividir"])
    ap.add_argument("doc")
    a = ap.parse_args()
    proj, cfg = Projeto(a.projeto), carregar_config()
    md = proj.fonte(a.doc).read_text(encoding="utf-8")
    if a.acao == "esqueleto":
        print(esqueleto(md, cfg["esqueleto"]["amostra_caracteres"]))
        return
    plano = ler_json(proj.plano(a.doc))
    if not plano:
        raise SystemExit(f"plano/{a.doc}.json não existe — rode o planejador antes.")
    trechos = dividir_md(md, plano["divisao"])
    salvar_jsonl(proj.trechos(a.doc), trechos)
    print({"trechos": len(trechos), "max_tokens_real": max(t["tokens"] for t in trechos) if trechos else 0})


if __name__ == "__main__":
    main()
