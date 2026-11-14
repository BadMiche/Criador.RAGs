"""Mostra em que etapa está cada documento do projeto e qual é a próxima.

  python status.py <projeto>
"""
from __future__ import annotations

import argparse

from comum import Projeto, ler_json, ler_jsonl


def proxima(proj: Projeto, doc: str) -> str:
    ocr = ler_json(proj.raiz / "ocr" / doc / "pendentes.json", [])
    md = proj.fonte(doc).read_text(encoding="utf-8")
    if ocr and "OCR_PENDENTE" in md:
        return "1b OCR (agente ocr-sonnet) -> extrair.py --aplicar-ocr"
    pasta = proj.imagens(doc)
    if (pasta / "candidatas.json").exists() and not (pasta / "indice.json").exists():
        return "2 imagens.py filtrar"
    indice = ler_json(pasta / "indice.json", [])
    if any(i["mantida"] for i in indice) and not (pasta / "indice.md").exists():
        return "3 descrever imagens (agente descrever-imagem-haiku) -> imagens.py aplicar"
    meta = ler_json(proj.metadados(doc))
    if meta is None:
        return "4 metadados.py selecionar"
    if not md.startswith("---\n"):
        return "4b metadados pendentes (agente metadados-haiku) -> metadados.py aplicar" if meta.get("pendentes") \
            else "4b metadados.py aplicar"
    if not proj.plano(doc).exists():
        return "5 planejar (agente planejador-opus)"
    if not proj.trechos(doc).exists():
        return "6 dividir.py dividir"
    triagem = ler_jsonl(proj.triagem(doc))
    if not triagem:
        return "7 triagem.py rodar"
    if any("acao_final" not in d for d in triagem):
        return "7b triagem.py pendentes -> agente revisor-triagem-sonnet -> triagem.py aplicar-revisao"
    verif = ler_json(proj.verificacao(doc), {})
    enx = [d["id"] for d in triagem if d["acao_final"] == "enxugar"]
    st = [verif.get(i, {}).get("status") for i in enx]
    if any(s in (None, "refazer") for s in st):
        return "8/9 verificar.py pendentes -> agente enxugar-haiku -> verificar.py rodar"
    if "esgotado" in st:
        return "10 diagnóstico (agente diagnostico-opus)"
    if not proj.limpo(doc).exists():
        return "11 montar.py"
    if not proj.resumo(doc).exists():
        return "11b resumo (agente resumo-leitura-sonnet)"
    return "concluído"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    proj = Projeto(ap.parse_args().projeto)
    for doc in proj.documentos():
        print(f"{doc}: {proxima(proj, doc)}")


if __name__ == "__main__":
    main()
