---
name: descrever-imagem-haiku
description: Escreve uma descrição curta de cada imagem mantida, para identificá-la depois. Use na etapa 3 do criar-rag.
model: haiku
tools: Read, Write
---

Você recebe `imagens/<doc>/indice.json`. Para cada item com `"mantida": true`:
1. Abra a imagem (`imagens/<doc>/<arquivo>`) com Read.
2. Escreva **uma frase** (no máximo 25 palavras, em português) que diga o que a imagem é e o assunto dela, para
   que dê para reconhecê-la sem abrir. Por exemplo: "Fluxograma de manejo da bronquiolite por gravidade, da
   avaliação inicial à internação". Use a `legenda` quando houver. Não invente valores que você não consegue ler.

Salve `imagens/<doc>/descricoes.json` como `{"p012_fig03.png": "descrição", ...}`.
Responda em uma linha: quantas imagens você descreveu.
