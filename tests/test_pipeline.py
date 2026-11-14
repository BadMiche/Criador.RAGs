"""pipeline.py em loop até concluir, com Jev e agentes simulados."""
import json
import re
from pathlib import Path

import pipeline
from comum import ler_json, salvar_json


def _agente_falso(t: dict, plano_exemplo: dict, proj) -> None:
    """Simula o que cada agente escreveria, a partir do prompt da tarefa."""
    doc = t["doc"]
    if t["agente"] == "descrever-imagem-haiku":
        indice = ler_json(proj.imagens(doc) / "indice.json")
        salvar_json(proj.imagens(doc) / "descricoes.json",
                    {i["arquivo"]: "Fluxograma de teste." for i in indice if i["mantida"]})
    elif t["agente"] == "metadados-haiku":
        meta = ler_json(proj.metadados(doc))
        for k in meta["pendentes"]:
            meta[k] = {"valor": None, "fonte": "nao_encontrado"}
        meta["pendentes"] = []
        salvar_json(proj.metadados(doc), meta)
    elif t["agente"] == "planejador-opus":
        salvar_json(proj.plano(doc), plano_exemplo)
    elif t["agente"] == "revisor-triagem-sonnet":
        lista = ler_json(proj.pasta("revisao") / f"{doc}.pendentes.json")
        rev = ler_json(proj.revisao(doc), {})
        rev.update({p["id"]: {"acao": p["acao_proposta"], "motivo": p["motivo"]} for p in lista})
        salvar_json(proj.revisao(doc), rev)
    elif t["agente"] == "enxugar-haiku":
        pend = ler_json(proj.enxuto(doc) / "_pendentes.json")
        for lote in t["lotes"]:
            ids = re.search(r"SOMENTE estes ids: (.*)", lote["prompt"]).group(1).split(", ")
            for item in pend["trechos"]:
                if item["id"] in ids:
                    cond = item["original"].replace("Historicamente, diversas terapias foram tentadas ao longo "
                                                    "das décadas, como é amplamente sabido.", "")
                    salvar_json(Path(item["saida"]), {"fatos_chave": [], "condensado": cond.strip()})
    elif t["agente"] == "resumo-leitura-sonnet":
        imgs = [i["arquivo"] for i in ler_json(proj.imagens(doc) / "indice.json") if i["mantida"]]
        proj.resumo(doc).write_text("# Resumo\n\n" + "".join(f"![fig](../imagens/{doc}/{a})\n" for a in imgs),
                                    encoding="utf-8")
    else:
        raise AssertionError(f"agente inesperado: {t['agente']}")


def test_pipeline_ate_concluir(tmp_path, pdf_exemplo, plano_exemplo, jev):
    from comum import projeto_de
    destino = tmp_path / "results" / "bronquiolite"
    projeto = projeto_de(destino)
    pedidos = []
    saida = pipeline.avancar(projeto, [str(pdf_exemplo)])
    for _ in range(15):
        assert not saida["erros"], saida["erros"]
        if not saida["tarefas"]:
            break
        for t in saida["tarefas"]:
            assert Path(t["instrucoes"]).exists() and t["subagent_type"].startswith("criador-resum:")
            pedidos.append(t["agente"])
            _agente_falso(t, plano_exemplo, projeto)
        saida = pipeline.avancar(projeto, [str(pdf_exemplo)])   # rodar de novo com os mesmos args é seguro
    assert saida["concluidos"] == ["bronquiolite-revisao-2021"]
    assert pedidos == ["descrever-imagem-haiku", "metadados-haiku", "planejador-opus",
                       "revisor-triagem-sonnet", "enxugar-haiku", "resumo-leitura-sonnet"]
    # resultado publicado: uma pasta por arquivo, links de imagem válidos a partir dela
    pasta = destino / "bronquiolite-revisao-2021"
    assert sorted(p.name for p in pasta.iterdir()) == ["imagens", "limpo.md", "resumido.md"]
    limpo, resumo = (pasta / "limpo.md").read_text(), (pasta / "resumido.md").read_text()
    assert "Ralston" not in limpo and "Historicamente" not in limpo
    links = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", limpo + resumo)
    assert links and all((pasta / l).exists() for l in links), links
    assert (pasta / "imagens" / "indice.md").exists()
    assert sorted(p.name for p in destino.iterdir()) == [".trabalho", "bronquiolite-revisao-2021"]


def test_pipeline_lotes_e_erro_do_jev(projeto, pdf_exemplo, monkeypatch):
    import jev_client

    def falha(**kw):
        raise jev_client.JevErro("HTTP 401: chave inválida")
    monkeypatch.setattr(jev_client, "perguntar", falha)
    saida = pipeline.avancar(projeto, [str(pdf_exemplo)])
    assert saida["erros"] and "401" in saida["erros"][0]["erro"] and not saida["concluidos"]
    assert json.dumps(saida, ensure_ascii=False)
