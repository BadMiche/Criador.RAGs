# Criador.RAGs

Plugin do Claude Code que transforma um ou mais arquivos (PDF, DOCX...) em:
**Markdown limpo + metadados de origem + imagens identificadas + trechos filtrados/enxutos + resumo de leitura**.
A indexação vetorial (o RAG em si) fica para a próxima fase; a saída `limpo/` já está pronta para ela.

Cada etapa usa o executor mais barato que faz bem o trabalho:

| Etapa | Executor |
|---|---|
| Extrair texto e imagens, dividir, montar | código |
| Filtrar imagens, escolher metadados, triar trechos, verificar o enxugamento | **Jev** (TypeSafe), com respostas tipadas e probabilidades |
| Descrever imagens, completar metadados, enxugar | Haiku |
| OCR de páginas digitalizadas, revisar decisões arriscadas, resumo de leitura | Sonnet |
| Planejar cada documento (divisão + perguntas do Jev) e diagnosticar falhas | Opus |

## Fluxo

```
arquivo → 1 extrair (.md + imagens/pNNN_figMM.png) → 2 Jev filtra imagens → 3 Haiku descreve
        → 4 metadados (regex + Jev escolhe + Haiku completa) → frontmatter YAML
        → 5 Opus lê o .md e escreve plano/<doc>.json (divisão, perguntas score/choice/noul, regras)
        → 6 dividir → 7 Jev tria cada trecho → 7b Sonnet revisa "descartar" e incertos
        → 8 Haiku enxuga ⇄ 9 verificação (código + Jev), até 2 voltas com feedback
        → 10 se ainda falhar: Opus diagnostica e pode recriar o plano (1×)
        → 11 montar limpo/<doc>.md → Sonnet escreve resumos/<doc>_resumo.md
```

## Instalar

**No Mac** (uma vez):

```bash
claude plugin marketplace add BadMiche/Criador.RAGs
```

```bash
claude plugin install criador-rags@criador-rags
```

```bash
echo 'export TYPESAFE_API_KEY=sua_chave' >> ~/.zshrc
```

A chave é criada em https://console.typesafe.ai. As dependências Python são instaladas sozinhas no primeiro uso,
num venv próprio em `~/.criador-rags/venv`.

**Na nuvem (claude.ai/code):** use o ambiente "Criador.RAGs", que já tem a chave do Jev salva e instala o plugin
em toda sessão nova. Neste repositório, o plugin também já vem habilitado em `.claude/settings.json`.

## Usar

```
/criador-rags:criar-rag <nome-do-rag> arquivo1.pdf arquivo2.pdf
```

Para continuar um projeto que parou no meio, rode o mesmo comando só com o nome (`/criador-rags:criar-rag bronquiolite`).

Por baixo, `scripts/pipeline.py` roda sozinho todas as etapas de código e de Jev e devolve as tarefas de agente que
faltam (com prompt e lotes); a skill dispara essas tarefas em paralelo e repete até concluir.
Para ver em que etapa está cada documento: `python scripts/status.py rags/<nome>`.

## Saída (`rags/<nome>/`)

| Pasta | Conteúdo |
|---|---|
| `fontes/` | .md extraído, com frontmatter de metadados e marcadores de página |
| `imagens/<doc>/` | `pNNN_figMM.png` (página + nº da figura), `indice.md` com legenda e descrição |
| `plano/` | o plano do Opus de cada documento (e as versões anteriores) |
| `trechos/`, `triagem/`, `revisao/`, `verificacao/` | as decisões de cada etapa, para auditoria |
| `limpo/` | o texto final filtrado e enxuto |
| `resumos/` | o resumo de leitura |
| `relatorio/` | o que foi removido e por quê, e a redução de tokens |
| `logs/` | o payload exato de cada chamada ao Jev |

Limiares, modelo do Jev e limites do loop ficam em `config.yaml`. Um plano de exemplo está em `docs/exemplo_plano.json`.

## Testes

```bash
python -m pytest -q
```

Os testes usam um Jev simulado e não chamam a API.
