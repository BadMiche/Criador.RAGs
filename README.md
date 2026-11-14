# Criador.Resum

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

**No Mac** (uma vez, no Terminal):

```bash
claude plugin marketplace add https://github.com/BadMiche/Criador.RAGs.git
```

```bash
claude plugin install criador-resum@criador-resum
```

```bash
echo 'export TYPESAFE_API_KEY=sua_chave' >> ~/.zshrc
```

- Use a URL **HTTPS** como acima. A forma curta (`BadMiche/...`) clona por SSH e falha se o Mac não tiver chave SSH do GitHub.
- A chave do Jev é criada em https://console.typesafe.ai. Depois do `echo`, abra um Terminal novo.
- As dependências Python são instaladas sozinhas no primeiro uso, num venv próprio em `~/.criador-resum/venv`.
- Se aparecer "marketplace já existe", remova e repita: `claude plugin marketplace remove criador-resum`.
- Se você instalou a versão antiga (`criador-rags`), remova antes:
  `claude plugin uninstall criador-rags@criador-rags` e `claude plugin marketplace remove criador-rags`.

**Na nuvem (claude.ai/code):** use o ambiente "Criador.Resum", que já tem a chave do Jev salva e instala o plugin
em toda sessão nova. Neste repositório, o plugin também já vem habilitado em `.claude/settings.json`.

## Usar

Uma conversa do Claude Code que já estava aberta antes da instalação não enxerga o plugin. Abra uma nova:

**Pelo Terminal**
1. Se o Claude Code estiver aberto, feche (`/exit`).
2. Vá até a pasta dos PDFs: `cd ~/Documents/artigos`
3. Abra o Claude Code: `claude`
4. Digite o comando com o nome do RAG e os arquivos:
   ```
   /criador-resum:criar-rag bronquiolite artigo1.pdf artigo2.pdf
   ```
   Ao digitar `/criador`, o comando deve aparecer nas sugestões. Se aparecer, a instalação deu certo.

**Pelo app Claude para desktop (aba Code):** abra uma conversa nova, escolha a pasta dos PDFs e digite o mesmo comando.

- O resultado sai em `rags/<nome>/` dentro da pasta onde você abriu o Claude; o resumo de leitura fica em `rags/<nome>/resumos/`.
- Para continuar um projeto que parou no meio: `/criador-resum:criar-rag bronquiolite` (só o nome).
- Se o comando não aparecer nas sugestões, rode `claude plugin list` no Terminal e confira se `criador-resum` está instalado e habilitado.

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
