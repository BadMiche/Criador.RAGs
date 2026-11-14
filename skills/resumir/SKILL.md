---
name: resumir
description: Workflow multi-modelo que transforma um ou mais arquivos (PDF, DOCX...) em Markdown limpo com metadados de origem, imagens identificadas, trechos filtrados/enxutos e um resumo de leitura. Usa código, Jev (TypeSafe), Haiku, Sonnet e Opus, cada um na etapa em que é melhor ou mais barato. Use quando o usuário enviar arquivos e pedir para "criar um RAG", "processar", "limpar e resumir" ou "preparar para o RAG", ou para continuar um projeto já começado.
argument-hint: "<assunto> <arquivo> [arquivo...]"
---

# Resumir

Argumentos: `$ARGUMENTS` (o primeiro é o assunto; o resto são os arquivos). Se faltar o assunto, use um nome curto
derivado do tema; se faltarem arquivos, continue os documentos já existentes desse assunto.
Destino = `results/<assunto>` no diretório atual (caminho absoluto). O resultado sai em uma pasta por arquivo,
`results/<assunto>/<arquivo>/` (`resumido.md`, `limpo.md`, `imagens/`); o trabalho intermediário fica em `.trabalho/`.

## 1. Preparar (uma vez por sessão)
```bash
PY=$(bash "${CLAUDE_PLUGIN_ROOT}/scripts/preparar.sh")
```
Diga em uma linha que os arquivos serão enviados em trechos à API do TypeSafe (Jev).

## 2. Loop
```bash
"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/pipeline.py" <destino> <arquivos...>
```
O pipeline roda sozinho todas as etapas de código e de Jev e devolve um JSON:
- `erros`: se não estiver vazio, **pare** e mostre ao usuário (por exemplo, a chave do Jev ausente ou inválida). Nunca contorne.
- `tarefas`: dispare **todas em paralelo**, numa única mensagem, com a ferramenta Agent:
  - `subagent_type` = o campo `subagent_type` (o agente do plugin, que já tem o modelo certo);
  - `prompt` = o campo `prompt`. Se a tarefa tiver `lotes`, dispare **um agente por lote**, com o `prompt` do lote;
  - se o agente do plugin não estiver disponível, use `general-purpose` com `model` = `modelo` e comece o prompt com
    "Leia e siga as instruções de `<instrucoes>` (ignore o frontmatter)."
  - Rode-as em primeiro plano e espere todas terminarem.
- Depois, rode o pipeline de novo **sem os arquivos** (só o destino). Repita até `tarefas` e `erros` ficarem vazios.

Não edite os arquivos do projeto por conta própria nem pule etapas: o pipeline decide.
Para ver em que ponto está cada documento: `"$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/status.py" <destino>`.

## 3. Final
Para cada documento em `concluidos`, leia `.trabalho/relatorio/<doc>.json` e informe em poucas linhas:
a redução de tokens, quantos trechos foram descartados, enxugados ou mantidos com o texto original, e o caminho de
`results/<assunto>/<doc>/resumido.md`. Ofereça abrir um resumo.
