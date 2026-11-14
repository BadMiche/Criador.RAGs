"""Fluxo completo com Jev simulado e saídas dos agentes escritas à mão."""
import json

import pytest

import dividir
import extrair
import imagens
import metadados
import montar
import plano as planolib
import status
import triagem
import verificar
from comum import carregar_config, ler_json, ler_jsonl, salvar_json, separar_frontmatter


def _extrair(projeto, pdf):
    cfg = carregar_config()
    res = extrair.extrair_pdf(projeto, pdf, "bronquiolite-revisao-2021", cfg)
    salvar_json(projeto.pasta("metadados") / "bronquiolite-revisao-2021.origem.json",
                {**res, "arquivo_original": pdf.name})
    return "bronquiolite-revisao-2021"


def test_extracao_imagens_e_logo(projeto, pdf_exemplo):
    doc = _extrair(projeto, pdf_exemplo)
    md = projeto.fonte(doc).read_text()
    cand = ler_json(projeto.imagens(doc) / "candidatas.json")
    assert [c["arquivo"] for c in cand] == ["p002_fig01.png"]          # logo repetido saiu
    assert cand[0]["legenda"].startswith("Figura 1")
    assert "(../imagens/bronquiolite-revisao-2021/p002_fig01.png)" in md
    assert "<!-- pagina: 3 -->" in md
    assert (projeto.imagens(doc) / "p002_fig01.png").exists()


def test_fluxo_completo(projeto, pdf_exemplo, plano_exemplo, jev):
    doc = _extrair(projeto, pdf_exemplo)

    # 2-3 imagens
    assert imagens.filtrar(projeto, doc) == {"mantidas": 1, "descartadas": 0}
    salvar_json(projeto.imagens(doc) / "descricoes.json", {"p002_fig01.png": "Fluxograma de manejo."})
    imagens.aplicar(projeto, doc)
    assert "fig1 — Fluxograma de manejo." in projeto.fonte(doc).read_text()

    # 4 metadados
    metadados.selecionar(projeto, doc)
    meta = ler_json(projeto.metadados(doc))
    assert meta["doi"]["valor"] == "10.1016/j.rbp.2021.01.004"
    assert meta["titulo"]["valor"].startswith("Bronquiolite viral")
    assert meta["autores"]["valor"] == "Maria Silva, João Souza"
    assert meta["ano"]["valor"] == 2021
    metadados.aplicar(projeto, doc)
    front, _ = separar_frontmatter(projeto.fonte(doc).read_text())
    assert front["revista"].startswith("Revista Brasileira")

    # 5 plano (Opus) -> 6 divisão
    salvar_json(projeto.plano(doc), plano_exemplo)
    trechos = dividir.dividir_md(projeto.fonte(doc).read_text(), plano_exemplo["divisao"])
    from comum import salvar_jsonl
    salvar_jsonl(projeto.trechos(doc), trechos)
    secoes = [t["secao"] for t in trechos]
    assert any("Referências" in s for s in secoes) and any("Tratamento" in s for s in secoes)

    # 7 triagem
    r = triagem.rodar(projeto, doc)
    tri = {d["secao"].split(" > ")[-1]: d for d in ler_jsonl(projeto.triagem(doc))}
    assert tri["Referências"]["acao"] == "descartar"
    assert tri["Agradecimentos"]["acao"] == "descartar"
    assert tri["Tratamento"]["acao"] == "enxugar"
    assert r["revisar"] >= 2  # todo "descartar" vai para revisão

    # 7b revisão Sonnet: confirma tudo
    pend = triagem.pendentes(projeto, doc)
    lista = ler_json(projeto.pasta("revisao") / f"{doc}.pendentes.json")
    salvar_json(projeto.revisao(doc), {p["id"]: {"acao": p["acao_proposta"], "motivo": p["motivo"]} for p in lista})
    assert pend["pendentes"] == len(lista)
    triagem.aplicar_revisao(projeto, doc)

    # 8-9 enxugar + verificar
    verificar.pendentes(projeto, doc)
    tid = tri["Tratamento"]["id"]
    pend_enx = ler_json(projeto.enxuto(doc) / "_pendentes.json")
    assert [t["id"] for t in pend_enx["trechos"]] == [tid]
    orig = pend_enx["trechos"][0]["original"]
    salvar_json(projeto.enxuto(doc) / f"{tid}.json", {
        "fatos_chave": ["oxigênio se saturação abaixo de 90 %"],
        "condensado": "## Tratamento\n\nSuporte. Oxigênio se saturação < 90 %. Salina hipertônica 3 % não recomendada de rotina."})
    assert len(orig) > 0
    assert verificar.rodar(projeto, doc)["aprovado"] == 1

    # 11 montar
    res = montar.montar(projeto, doc)
    limpo = projeto.limpo(doc).read_text()
    assert "Ralston" not in limpo and "Agradecemos" not in limpo
    assert "Historicamente" not in limpo and "Salina hipertônica 3 %" in limpo
    assert limpo.startswith("---\n")
    rel = ler_json(projeto.relatorio(doc))
    assert "lista de referências" in rel["removidos_por_motivo"]
    assert res["tokens_depois"] < res["tokens_antes"]
    assert status.proxima(projeto, doc).startswith("11b")


def test_loop_ate_esgotar_e_diagnostico(projeto, pdf_exemplo, plano_exemplo, jev):
    doc = _extrair(projeto, pdf_exemplo)
    salvar_json(projeto.imagens(doc) / "indice.json", [])
    salvar_json(projeto.plano(doc), plano_exemplo)
    from comum import salvar_jsonl
    salvar_jsonl(projeto.trechos(doc), dividir.dividir_md(projeto.fonte(doc).read_text(), plano_exemplo["divisao"]))
    triagem.rodar(projeto, doc)
    lista = triagem.pendentes(projeto, doc) and ler_json(projeto.pasta("revisao") / f"{doc}.pendentes.json")
    salvar_json(projeto.revisao(doc), {p["id"]: {"acao": p["acao_proposta"]} for p in lista})
    triagem.aplicar_revisao(projeto, doc)
    tid = next(d["id"] for d in ler_jsonl(projeto.triagem(doc)) if d["acao_final"] == "enxugar")

    jev.omite = 0.9  # o Jev sempre acha que falta algo
    vc = carregar_config()["verificacao"]
    for tentativa in range(vc["max_voltas"] + 1):
        verificar.pendentes(projeto, doc)
        item = ler_json(projeto.enxuto(doc) / "_pendentes.json")["trechos"][0]
        if tentativa:
            assert any("deixou de fora" in f for f in item["feedback"])  # feedback específico volta ao Haiku
        salvar_json(projeto.enxuto(doc) / f"{tid}.json", {"fatos_chave": [], "condensado": f"Curto v{tentativa}."})
        verificar.rodar(projeto, doc)
    est = verificar.esgotados(projeto, doc)
    assert est["esgotados"] == [tid] and est["pode_redesenhar"]

    verificar.reiniciar(projeto, doc, [tid])          # Opus refez o plano: 1 redesenho
    assert not verificar.esgotados(projeto, doc)["pode_redesenhar"]
    with pytest.raises(SystemExit):
        verificar.reiniciar(projeto, doc, [tid])      # limite de redesenhos

    # desistência: trecho fica original no texto final
    for tentativa in range(vc["max_voltas"] + 1):
        salvar_json(projeto.enxuto(doc) / f"{tid}.json", {"fatos_chave": [], "condensado": f"Outro v{tentativa}."})
        verificar.rodar(projeto, doc)
    verificar.manter_original(projeto, doc)
    montar.montar(projeto, doc)
    assert "Historicamente" in projeto.limpo(doc).read_text()


def test_validacao_do_plano(plano_exemplo):
    planolib.validar(plano_exemplo)
    ruim = json.loads(json.dumps(plano_exemplo))
    ruim["perguntas_triagem"]["tipo_secao"]["criteria"] = {"so_uma": "x"}
    ruim["regras"].append({"se": [{"q": "nao_existe", "op": ">", "v": 0.5}], "acao": "apagar"})
    with pytest.raises(planolib.PlanoInvalido) as e:
        planolib.validar(ruim)
    msg = str(e.value)
    assert "choice precisa" in msg and "não existe" in msg and "acao inválida" in msg


def test_regras_e_faixa_incerta(plano_exemplo):
    base = {
        "lista_referencias": {"type": "noul", "noul": 0.05},
        "editorial": {"type": "noul", "noul": 0.05},
        "conteudo_clinico": {"type": "noul", "noul": 0.9},
        "tipo_secao": {"type": "choice", "choice": "conteudo_clinico", "confidence": 0.9,
                       "probabilities": {"conteudo_clinico": 0.9, "metodologia_da_revisao": 0.1}},
        "prolixidade": {"type": "score", "score": 0.3, "confidence": 0.8, "probabilities": {}},
    }
    faixa = (0.3, 0.7)
    d = planolib.decidir(plano_exemplo, base, faixa)
    assert d == {"acao": "manter", "motivo": "padrão", "regra": None, "incerta": False, "revisar": False}

    ref = {**base, "lista_referencias": {"type": "noul", "noul": 0.9}}
    assert planolib.decidir(plano_exemplo, ref, faixa)["acao"] == "descartar"
    assert planolib.decidir(plano_exemplo, ref, faixa)["revisar"]       # descartar sempre revisa

    incerto = {**base, "editorial": {"type": "noul", "noul": 0.5}}
    d = planolib.decidir(plano_exemplo, incerto, faixa)
    assert d["acao"] == "manter" and d["incerta"] and d["revisar"]

    prolixo = {**base, "prolixidade": {"type": "score", "score": 1.5, "confidence": 0.6, "probabilities": {}}}
    assert planolib.decidir(plano_exemplo, prolixo, faixa)["acao"] == "enxugar"


def test_divisao_respeita_limite_e_tabela():
    tabela = "\n".join(["| Droga | Dose |", "|---|---|"] + [f"| D{i} | {i} mg/kg |" for i in range(40)])
    longo = " ".join(["Frase longa com conteúdo clínico relevante para o teste."] * 120)
    md = f"# Doc\n\n## A\n\n{longo}\n\n## B\n\n{tabela}\n\n## C\n\nCurto.\n\n## D\n\nCurto também.\n"
    ts = dividir.dividir_md(md, {"nivel_heading": 2, "max_tokens": 400, "min_tokens": 20,
                                 "unir_pequenas": True, "sobreposicao_paragrafos": 1})
    assert all(t["tokens"] <= 400 for t in ts if not t["texto"].lstrip("#").strip().startswith("B"))
    assert sum(1 for t in ts if "| D0 |" in t["texto"]) == 1 and any("| D39 |" in t["texto"] for t in ts)
    assert ts[1]["contexto_anterior"]                     # sobreposição só no contexto
    assert "Curto." in ts[-1]["texto"] or "Curto." in ts[-2]["texto"]


def test_numeros_com_unidade():
    a = verificar.numeros("Dose 10 mg/kg, saturação < 90 %, 3-5 dias; ver ![x](p012_fig03.png)")
    assert a == {"10mg", "90%", "3-5dias", "3dias", "5dias"}
    assert verificar.numeros("50 anos e 74 anos") <= verificar.numeros("de 50 a 74 anos")
    assert verificar.numeros("Dose 10 mg/kg") <= a


def test_imagem_dentro_dos_limites_do_jev(tmp_path):
    import io

    from PIL import Image

    import jev_client
    for w, h in ((198, 169), (1064, 245), (3000, 900)):
        p = tmp_path / f"{w}x{h}.png"
        Image.new("RGB", (w, h), "red").save(p)
        out = Image.open(io.BytesIO(jev_client.preparar_imagem(p)))
        assert all(jev_client.IMG_MIN <= s <= jev_client.IMG_MAX for s in out.size), out.size


def test_sobra_pequena_volta_para_o_pedaco_anterior():
    paragrafos = [" ".join([f"Frase {i} com conteúdo."] * 30) for i in range(5)] + ["Sobra curta."]
    md = "# Seção\n\n" + "\n\n".join(paragrafos) + "\n"
    div = {"nivel_heading": 1, "max_tokens": 400, "min_tokens": 50, "unir_pequenas": True}
    ts = dividir.dividir_md(md, div)
    junto = "\n\n".join(t["texto"] for t in ts)
    for p in paragrafos:
        assert junto.count(p) == 1          # nada perdido nem duplicado
    assert "Sobra curta." in ts[-1]["texto"] and ts[-1]["tokens"] > 50


def test_fatos_chave_congelados_na_primeira_tentativa(projeto, pdf_exemplo, plano_exemplo, jev):
    doc = _extrair(projeto, pdf_exemplo)
    salvar_json(projeto.plano(doc), plano_exemplo)
    from comum import salvar_jsonl
    salvar_jsonl(projeto.trechos(doc), dividir.dividir_md(projeto.fonte(doc).read_text(), plano_exemplo["divisao"]))
    triagem.rodar(projeto, doc)
    lista = triagem.pendentes(projeto, doc) and ler_json(projeto.pasta("revisao") / f"{doc}.pendentes.json")
    salvar_json(projeto.revisao(doc), {p["id"]: {"acao": p["acao_proposta"]} for p in lista})
    triagem.aplicar_revisao(projeto, doc)
    tid = next(d["id"] for d in ler_jsonl(projeto.triagem(doc)) if d["acao_final"] == "enxugar")

    jev.omite = 0.9
    salvar_json(projeto.enxuto(doc) / f"{tid}.json", {"fatos_chave": ["fato A"], "condensado": "v1"})
    verificar.rodar(projeto, doc)
    jev.omite = 0.05
    # o Haiku tenta encurtar a própria checklist: a verificação continua cobrando "fato A"
    salvar_json(projeto.enxuto(doc) / f"{tid}.json", {"fatos_chave": [], "condensado": "v2"})
    verificar.rodar(projeto, doc)
    ultima = jev.chamadas[-1]["questions"]
    assert "fato A" in ultima["fato_00"]["instructions"]
    verificar.pendentes(projeto, doc)
