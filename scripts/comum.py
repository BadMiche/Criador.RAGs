"""Utilidades compartilhadas: caminhos do projeto, config, JSON/JSONL, tokens."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable

import yaml

RAIZ_PLUGIN = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = RAIZ_PLUGIN / "config.yaml"


def carregar_config(caminho: Path | None = None) -> dict:
    with open(caminho or CONFIG_PADRAO, encoding="utf-8") as f:
        return yaml.safe_load(f)


def slug(texto: str) -> str:
    """Nome de arquivo seguro, sem acentos: 'Artigo Sepse (2021).pdf' -> 'artigo-sepse-2021'."""
    texto = unicodedata.normalize("NFKD", Path(texto).stem).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto or "documento"


def estimar_tokens(texto: str) -> int:
    """Estimativa simples (~4 caracteres por token), suficiente para dividir texto."""
    return max(1, len(texto) // 4)


class Projeto:
    """Pastas de um projeto (futuro RAG): rags/<nome>/..."""

    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def pasta(self, nome: str) -> Path:
        p = self.raiz / nome
        p.mkdir(parents=True, exist_ok=True)
        return p

    def fonte(self, doc: str) -> Path:
        return self.pasta("fontes") / f"{doc}.md"

    def imagens(self, doc: str) -> Path:
        return self.pasta("imagens") / doc

    def metadados(self, doc: str) -> Path:
        return self.pasta("metadados") / f"{doc}.json"

    def plano(self, doc: str) -> Path:
        return self.pasta("plano") / f"{doc}.json"

    def trechos(self, doc: str) -> Path:
        return self.pasta("trechos") / f"{doc}.jsonl"

    def triagem(self, doc: str) -> Path:
        return self.pasta("triagem") / f"{doc}.jsonl"

    def revisao(self, doc: str) -> Path:
        return self.pasta("revisao") / f"{doc}.json"

    def enxuto(self, doc: str) -> Path:
        return self.pasta("enxuto") / doc

    def verificacao(self, doc: str) -> Path:
        return self.pasta("verificacao") / f"{doc}.json"

    def diagnostico(self, doc: str) -> Path:
        return self.pasta("diagnostico") / f"{doc}.md"

    def limpo(self, doc: str) -> Path:
        return self.pasta("limpo") / f"{doc}.md"

    def relatorio(self, doc: str) -> Path:
        return self.pasta("relatorio") / f"{doc}.json"

    def resumo(self, doc: str) -> Path:
        return self.pasta("resumos") / f"{doc}_resumo.md"

    def log_jev(self, doc: str) -> Path:
        return self.pasta("logs") / f"jev_{doc}.jsonl"

    def documentos(self) -> list[str]:
        return sorted(p.stem for p in (self.raiz / "fontes").glob("*.md"))


def ler_json(caminho: Path, padrao: Any = None) -> Any:
    if not Path(caminho).exists():
        return padrao
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def salvar_json(caminho: Path, dados: Any) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def ler_jsonl(caminho: Path) -> list[dict]:
    if not Path(caminho).exists():
        return []
    with open(caminho, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def salvar_jsonl(caminho: Path, linhas: Iterable[dict]) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        for l in linhas:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")


def anexar_jsonl(caminho: Path, linha: dict) -> None:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def separar_frontmatter(md: str) -> tuple[dict, str]:
    m = FRONTMATTER.match(md)
    if not m:
        return {}, md
    return yaml.safe_load(m.group(1)) or {}, md[m.end():]


def juntar_frontmatter(meta: dict, corpo: str) -> str:
    if not meta:
        return corpo
    cab = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{cab}\n---\n{corpo.lstrip()}"
