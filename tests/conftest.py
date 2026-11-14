import json
import shutil
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import jev_client  # noqa: E402


def _png(cor, w=300, h=200):
    import pymupdf
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, w, h), False)
    pix.set_rect(pix.irect, cor)
    return pix.tobytes("png")


@pytest.fixture
def pdf_exemplo(tmp_path) -> Path:
    import pymupdf
    doc = pymupdf.open()
    logo = _png((10, 10, 200), 120, 60)
    fig = _png((200, 30, 30))
    paginas = [
        [("Revista Brasileira de Pediatria. 2021;97(3):210-218", 8),
         ("Bronquiolite viral aguda: revisão", 18),
         ("Maria Silva, João Souza", 11),
         ("DOI: 10.1016/j.rbp.2021.01.004", 8),
         ("## Introdução", 0),
         ("A bronquiolite é a principal causa de internação em lactentes menores de 12 meses.", 11)],
        [("## Tratamento", 0),
         ("O tratamento é de suporte. Oxigênio se saturação abaixo de 90 %. Salina hipertônica 3 % não é recomendada de rotina.", 11),
         ("Historicamente, diversas terapias foram tentadas ao longo das décadas, como é amplamente sabido.", 11),
         ("FIG", 0),
         ("Figura 1. Fluxograma de manejo da bronquiolite.", 9)],
        [("## Agradecimentos", 0),
         ("Agradecemos à equipe do hospital pelo apoio na redação deste artigo.", 11),
         ("## Referências", 0),
         ("1. Ralston SL, et al. Pediatrics. 2014;134:e1474.", 9),
         ("2. Florin TA, et al. Lancet. 2017;389:211-224.", 9)],
    ]
    for linhas in paginas:
        p = doc.new_page()
        p.insert_image(pymupdf.Rect(450, 20, 570, 80), stream=logo)  # logo repetido
        y = 110
        for texto, tam in linhas:
            if texto == "FIG":
                p.insert_image(pymupdf.Rect(72, y, 372, y + 200), stream=fig)
                y += 215
                continue
            if texto.startswith("## "):
                p.insert_text((72, y), texto[3:], fontsize=16)
                y += 30
                continue
            p.insert_text((72, y), texto, fontsize=tam)
            y += 24
    caminho = tmp_path / "Bronquiolite Revisão (2021).pdf"
    doc.save(str(caminho))
    return caminho


@pytest.fixture
def projeto(tmp_path):
    from comum import Projeto
    return Projeto(tmp_path / "rags" / "teste")


@pytest.fixture
def plano_exemplo():
    return json.loads((RAIZ / "docs" / "exemplo_plano.json").read_text(encoding="utf-8"))


def _noul(p):
    return {"type": "noul", "noul": p}


def _choice(opcoes, escolhida):
    probs = {o: (0.9 if o == escolhida else 0.1 / max(1, len(opcoes) - 1)) for o in opcoes}
    return {"type": "choice", "choice": escolhida, "confidence": 0.8, "probabilities": probs}


def _score(n, valor):
    return {"type": "score", "score": valor, "confidence": 0.7,
            "legend": {str(i): "" for i in range(n)}, "probabilities": {str(i): 1 / n for i in range(n)}}


class JevFalso:
    """Jev simulado por heurísticas simples, com ajustes por teste."""

    def __init__(self):
        self.chamadas = []
        self.omite = 0.05

    def __call__(self, state, questions, assets=None, log=None, contexto=None):
        self.chamadas.append({"state": state, "questions": questions, "contexto": contexto})
        texto = json.dumps(state, ensure_ascii=False).lower()
        out = {}
        for qid, q in questions.items():
            if qid == "informativa":
                out[qid] = _noul(0.9)
            elif qid == "decorativa":
                out[qid] = _noul(0.1)
            elif qid.endswith("_existe"):
                out[qid] = _noul(0.9)
            elif qid.endswith("_qual"):
                alvo = {"titulo_qual": "bronquiolite viral", "autores_qual": "maria silva",
                        "revista_qual": "revista brasileira", "ano_qual": "2021"}[qid]
                esc = next((o for o, d in q["criteria"].items() if alvo in (str(d) + o).lower()),
                           next(iter(q["criteria"])))
                out[qid] = _choice(list(q["criteria"]), esc)
            elif qid == "lista_referencias":
                out[qid] = _noul(0.95 if "referências" in state.get("secao", "").lower() else 0.03)
            elif qid == "editorial":
                out[qid] = _noul(0.92 if "agradecimentos" in state.get("secao", "").lower() else 0.04)
            elif qid == "conteudo_clinico":
                out[qid] = _noul(0.9 if any(k in state.get("trecho", "") for k in ("%", "lactentes")) else 0.1)
            elif qid == "tipo_secao":
                out[qid] = _choice(list(q["criteria"]), "conteudo_clinico")
            elif qid == "prolixidade":
                out[qid] = _score(3, 1.6 if "historicamente" in texto else 0.2)
            elif qid == "omite":
                out[qid] = _noul(self.omite)
            elif qid == "inventa" or qid == "recomendacao_mudou":
                out[qid] = _noul(0.05)
            elif qid.startswith("fato_"):
                out[qid] = _noul(0.95)
            else:
                out[qid] = _noul(0.5)
        return out


@pytest.fixture
def jev(monkeypatch):
    falso = JevFalso()
    monkeypatch.setattr(jev_client, "perguntar", falso)
    return falso
