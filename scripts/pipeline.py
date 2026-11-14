"""Motor do workflow: avança cada documento sozinho até precisar de um agente.

  python pipeline.py <projeto> [arquivo ...]

- Arquivos novos são extraídos; documentos já existentes continuam de onde pararam.
- Etapas de código e de Jev rodam aqui mesmo. Quando um documento precisa de um agente
  (OCR, descrição de imagens, metadados, planejamento, revisão, enxugamento, diagnóstico, resumo),
  ele para e a tarefa sai no JSON final, pronta para o orquestrador disparar (em paralelo).
- Rode de novo depois que os agentes terminarem. Repita até todos estarem em "concluidos".

Saída (stdout, JSON):
  {"tarefas": [{"doc", "etapa", "agente", "subagent_type", "modelo", "instrucoes", "prompt"}],
   "concluidos": [doc...], "erros": [{"doc", "erro"}], "log": [...]}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dividir
import extrair
import imagens
import metadados
import montar
import triagem
import verificar
from comum import (RAIZ_PLUGIN, Projeto, carregar_config, ler_json, ler_jsonl, salvar_json, salvar_jsonl,
                   slug)
from jev_client import JevErro

LOTE_HAIKU = 12          # trechos por agente de enxugamento (medido no teste real)
MAX_PASSOS = 40          # trava contra laço infinito por documento
MODELOS = {"ocr-sonnet": "sonnet", "descrever-imagem-haiku": "haiku", "metadados-haiku": "haiku",
           "planejador-opus": "opus", "revisor-triagem-sonnet": "sonnet", "enxugar-haiku": "haiku",
           "diagnostico-opus": "opus", "resumo-leitura-sonnet": "sonnet"}


class Tarefa(Exception):
    """Interrompe o avanço do documento: precisa de agente."""

    def __init__(self, etapa: str, agente: str, prompt: str, **extra):
        self.dados = {"etapa": etapa, "agente": agente, "subagent_type": f"criador-resum:{agente}",
                      "modelo": MODELOS[agente], "instrucoes": str(RAIZ_PLUGIN / "agents" / f"{agente}.md"),
                      "prompt": prompt, **extra}


def _cmd(proj: Projeto) -> str:
    return f"cd {RAIZ_PLUGIN / 'scripts'} && {sys.executable}"


def passo(proj: Projeto, doc: str, log: list) -> bool:
    """Executa UMA etapa automática do documento. Retorna False quando o documento está concluído.
    Levanta Tarefa quando precisa de um agente."""
    md_path = proj.fonte(doc)
    md = md_path.read_text(encoding="utf-8")
    base = f"Projeto: {proj.raiz}\nDocumento (<doc>): {doc}\n"

    # 1b. OCR
    ocr = proj.raiz / "ocr" / doc / "pendentes.json"
    if ocr.exists() and "OCR_PENDENTE" in md:
        pend = ler_json(ocr, [])
        if all(Path(p["saida"]).exists() for p in pend):
            extrair.aplicar_ocr(proj, doc)
            log.append(f"{doc}: OCR aplicado")
            return True
        raise Tarefa("1b OCR", "ocr-sonnet", base + f"Lista de páginas: {ocr}\nSalve cada página no campo 'saida'.")

    # 2-3. imagens
    pasta = proj.imagens(doc)
    if not (pasta / "indice.json").exists():
        log.append(f"{doc}: imagens filtradas pelo Jev {imagens.filtrar(proj, doc)}")
        return True
    if not (pasta / "indice.md").exists():
        mantidas = [i for i in ler_json(pasta / "indice.json", []) if i["mantida"]]
        if mantidas and not (pasta / "descricoes.json").exists():
            raise Tarefa("3 descrever imagens", "descrever-imagem-haiku",
                         base + f"Entrada: {pasta / 'indice.json'}\nSaída: {pasta / 'descricoes.json'}")
        imagens.aplicar(proj, doc)
        log.append(f"{doc}: descrições aplicadas")
        return True

    # 4. metadados
    meta = ler_json(proj.metadados(doc))
    if meta is None:
        log.append(f"{doc}: metadados (Jev) {metadados.selecionar(proj, doc)}")
        return True
    if not md.startswith("---\n"):
        if meta.get("pendentes"):
            raise Tarefa("4b metadados", "metadados-haiku",
                         base + f"Arquivo a completar: {proj.metadados(doc)}\nTexto: {md_path}\n"
                                f"Metadados do PDF: {proj.pasta('metadados') / (doc + '.pdf.json')}")
        metadados.aplicar(proj, doc)
        log.append(f"{doc}: frontmatter gravado")
        return True

    # 5. plano
    if not proj.plano(doc).exists():
        raise Tarefa("5 planejar", "planejador-opus",
                     base + f"Scripts (<scripts>): {RAIZ_PLUGIN / 'scripts'}\nRode os scripts com: `{_cmd(proj)} ...`\n"
                            f"Exemplo de plano: {RAIZ_PLUGIN / 'docs' / 'exemplo_plano.json'}\n"
                            f"Saída: {proj.plano(doc)} (validada)")

    # 6. divisão
    if not proj.trechos(doc).exists():
        ts = dividir.dividir_md(md, ler_json(proj.plano(doc))["divisao"])
        salvar_jsonl(proj.trechos(doc), ts)
        log.append(f"{doc}: {len(ts)} trechos")
        return True

    # 7. triagem
    tri = ler_jsonl(proj.triagem(doc))
    ids_trechos = {t["id"] for t in ler_jsonl(proj.trechos(doc))}
    faltam_triagem = ids_trechos - {d["id"] for d in tri}
    if faltam_triagem:
        log.append(f"{doc}: triagem (Jev) {triagem.rodar(proj, doc, faltam_triagem if tri else None)}")
        return True

    # 7b. revisão
    if any("acao_final" not in d for d in tri):
        p = triagem.pendentes(proj, doc)
        if p["pendentes"]:
            raise Tarefa("7b revisão", "revisor-triagem-sonnet",
                         base + f"Lista a revisar ({p['pendentes']} itens): {p['arquivo']}\n"
                                f"Plano: {proj.plano(doc)}\nSaída: {p['saida_esperada']} "
                                f"(uma entrada para cada id da lista; preserve as entradas já existentes)")
        log.append(f"{doc}: revisão aplicada {triagem.aplicar_revisao(proj, doc)}")
        return True

    # 8-9. enxugar <-> verificar
    if any(d["acao_final"] == "enxugar" for d in tri):
        r = verificar.rodar(proj, doc)          # verifica o que o Haiku já escreveu (sem custo se nada novo)
        if r["verificados"]:
            log.append(f"{doc}: verificação (Jev) {r}")
        p = verificar.pendentes(proj, doc)
        if p["pendentes"]:
            ids = [t["id"] for t in ler_json(Path(p["arquivo"]))["trechos"]]
            lotes = [ids[i:i + LOTE_HAIKU] for i in range(0, len(ids), LOTE_HAIKU)]
            raise Tarefa("8 enxugar", "enxugar-haiku", "", lotes=[
                {"prompt": base + f"Entrada: {p['arquivo']}\nProcesse SOMENTE estes ids: {', '.join(l)}\n"
                                  "Para cada um, salve o JSON no caminho do campo 'saida'."} for l in lotes])

        # 10. diagnóstico
        e = verificar.esgotados(proj, doc)
        if e["esgotados"]:
            if e["pode_redesenhar"] and not proj.diagnostico(doc).exists():
                raise Tarefa("10 diagnóstico", "diagnostico-opus",
                             base + f"Trechos esgotados: {', '.join(e['esgotados'])}\n"
                                    f"Scripts (<scripts>): {RAIZ_PLUGIN / 'scripts'}\nRode os scripts com: `{_cmd(proj)} ...`\n"
                                    "Os fatos-chave de cada trecho ficam congelados na 1ª tentativa (campo 'fatos_chave' em "
                                    "verificacao/<doc>.json); se a causa for a lista, apague esse campo dos trechos reiniciados. "
                                    "Se reiniciar a triagem com --ids, rode o triagem.py rodar você mesmo. Não rode o enxugamento.")
            log.append(f"{doc}: mantendo original {verificar.manter_original(proj, doc)}")
            return True

    # 11. montar + resumo
    if not proj.limpo(doc).exists():
        log.append(f"{doc}: montado {montar.montar(proj, doc)}")
        return True
    if not proj.resumo(doc).exists():
        raise Tarefa("11b resumo", "resumo-leitura-sonnet",
                     base + f"Texto final: {proj.limpo(doc)}\nRelatório: {proj.relatorio(doc)}\n"
                            f"Saída: {proj.resumo(doc)} (links de imagem relativos a essa pasta: ../imagens/...)\n"
                            "Use como título o nome real do documento; cite portaria/revista na linha de referência.")
    return False


def avancar(proj: Projeto, arquivos: list[str]) -> dict:
    cfg, log = carregar_config(), []
    existentes = set(proj.documentos())
    for arq in map(Path, arquivos):
        doc = slug(arq.name)
        if doc in existentes:
            continue
        import shutil
        shutil.copy2(arq, proj.pasta("originais") / f"{doc}{arq.suffix.lower()}")
        res = extrair.extrair_pdf(proj, arq, doc, cfg) if arq.suffix.lower() == ".pdf" \
            else extrair.extrair_outro(proj, arq, doc)
        salvar_json(proj.pasta("metadados") / f"{doc}.origem.json", {**res, "arquivo_original": arq.name})
        log.append(f"{doc}: extraído {res}")

    saida = {"tarefas": [], "concluidos": [], "erros": [], "log": log}
    for doc in proj.documentos():
        try:
            for _ in range(MAX_PASSOS):
                if not passo(proj, doc, log):
                    saida["concluidos"].append(doc)
                    break
            else:
                saida["erros"].append({"doc": doc, "erro": "laço sem progresso; veja status.py"})
        except Tarefa as t:
            saida["tarefas"].append({"doc": doc, **t.dados})
        except (JevErro, SystemExit) as e:
            saida["erros"].append({"doc": doc, "erro": str(e)})
    return saida


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("projeto")
    ap.add_argument("arquivos", nargs="*")
    a = ap.parse_args()
    print(json.dumps(avancar(Projeto(a.projeto), a.arquivos), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
