---
name: criar-rag
description: Workflow multi-modelo que transforma um ou mais arquivos (PDF, DOCX...) em Markdown limpo com metadados de origem, imagens identificadas, trechos filtrados/enxutos e um resumo de leitura. Usa código, Jev (TypeSafe), Haiku, Sonnet e Opus, cada um na etapa em que é melhor ou mais barato. Use quando o usuário enviar arquivos e pedir para "criar um RAG", "processar", "limpar e resumir" ou "preparar para o RAG".
---

# Criar RAG (até o texto limpo + resumo)

`S=${CLAUDE_PLUGIN_ROOT}/scripts` · projeto = `rags/<nome>` no diretório atual (pergunte o nome só se não for óbvio).
Requisitos: `pip install -r ${CLAUDE_PLUGIN_ROOT}/requirements.txt` e `TYPESAFE_API_KEY` no ambiente.
Se o Jev falhar (sem chave, sem rede), **pare e informe**: nunca trate erro como resposta.

A qualquer momento, `python $S/status.py <projeto>` mostra a próxima etapa de cada documento. Use para retomar.
Processe os documentos em paralelo sempre que as etapas forem independentes.

| # | Etapa | Como |
|---|---|---|
| 1 | Extrair | `python $S/extrair.py <projeto> <arquivos...>` |
| 1b | OCR (só se houver `ocr/<doc>/pendentes.json`) | agente **ocr-sonnet** → `python $S/extrair.py <projeto> --aplicar-ocr <doc>` |
| 2 | Filtrar imagens (Jev) | `python $S/imagens.py <projeto> filtrar <doc>` |
| 3 | Descrever imagens | agente **descrever-imagem-haiku** (se houver imagens mantidas) → `python $S/imagens.py <projeto> aplicar <doc>` |
| 4 | Metadados (código + Jev) | `python $S/metadados.py <projeto> selecionar <doc>` |
| 4b | Completar metadados | se `pendentes` não estiver vazio: agente **metadados-haiku**; depois `python $S/metadados.py <projeto> aplicar <doc>` |
| 5 | Planejar | agente **planejador-opus** (projeto, doc, `$S`) → `plano/<doc>.json` validado |
| 6 | Dividir | `python $S/dividir.py <projeto> dividir <doc>` |
| 7 | Triagem (Jev) | `python $S/triagem.py <projeto> rodar <doc>` |
| 7b | Revisão | `python $S/triagem.py <projeto> pendentes <doc>`; se houver pendentes, agente **revisor-triagem-sonnet**; depois `python $S/triagem.py <projeto> aplicar-revisao <doc>` |
| 8 | Enxugar | `python $S/verificar.py <projeto> pendentes <doc>` → agente **enxugar-haiku** (em lotes de ~15 trechos, em paralelo) |
| 9 | Verificar (Jev + código) | `python $S/verificar.py <projeto> rodar <doc>`; enquanto houver `refazer`, volte ao passo 8 (o feedback vai junto) |
| 10 | Diagnóstico | se `verificar.py ... esgotados <doc>` listar trechos: agente **diagnostico-opus**; continue do passo que ele indicar (6, 7 ou 8) |
| 11 | Montar | `python $S/montar.py <projeto> <doc>` → `limpo/<doc>.md` + `relatorio/<doc>.json` |
| 11b | Resumo de leitura | agente **resumo-leitura-sonnet** → `resumos/<doc>_resumo.md` |

Regras:
- Não pule a validação do plano nem a revisão de "descartar": são o que protege contra perda de conteúdo.
- O loop 8↔9 para sozinho (`max_voltas` no `config.yaml`) e o diagnóstico pode refazer o plano só uma vez (`max_redesenhos`).
- Antes do primeiro uso real do Jev em dados do usuário, avise quais arquivos serão enviados à API do TypeSafe.

Ao final, informe em poucas linhas: os documentos processados, a redução de tokens, os trechos que ficaram com o texto original
e os caminhos dos resumos. Ofereça abrir um resumo.
