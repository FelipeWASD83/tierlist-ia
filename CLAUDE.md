# CLAUDE.md: tierlist-ia

App local onde a pessoa descreve uma tierlist em texto ("personagens de One Piece do mais forte ao mais fraco"),
escolhe quantos itens quer (5 a 60) e a IA monta tudo: título, fileiras, itens já classificados e uma imagem
por item. Depois ele arrasta para ajustar, troca imagem, exporta PNG. Criado em 06/11/2026 a pedido dele. O
`CLAUDE.md` da raiz vale aqui também; o uso, para ele, está no `README.md`.

Versão atual: `versao.json` (mesmo número no topo do `CHANGELOG.md`).

## 1. Como roda

```
Menu Iniciar "Tierlist IA" ─► _organizacao\atalhos\janela-app (Electron, --app=tierlist-ia)
                                └─► python iniciar.py   (aplica atualização baixada, sobe e reinicia o servidor)
                                      └─► python servidor\servidor.py --porta 4362
janela ◄── http://127.0.0.1:4362/
```

- **Só biblioteca padrão do Python**, sem venv e sem pacote compilado (Smart App Control). HTTP pelo `urllib`.
- `abrir-no-navegador.bat`: o mesmo servidor, aberto no navegador padrão.
- Preview: entradas `tierlist-ia` (porta 4362, dados de verdade) e `tierlist-ia-demo` (porta 4363) do
  `launch.json` da raiz. A demo (`ferramentas\demo.py`) usa dados em `%TEMP%\tierlist-ia-demo` e um Claude falso
  que sempre responde a mesma tierlist de One Piece; as imagens são buscadas de verdade. Não gasta crédito.
- Dados em `dados/` (fora do git): `config.json`, `segredos.json` (chaves da Anthropic, da OpenAI e token do
  GitHub, protegidas pelo DPAPI do Windows), `tierlists/<id>.json`, `imagens/<sha1>.<ext>`, `atualizacao/`.
  `TIERLIST_IA_DADOS` troca a pasta.

## 2. Mapa do código

| Arquivo | O que faz |
|---|---|
| `servidor/servidor.py` | Rotas `/api/*`, estáticos de `app/`, `/imagens/<nome>`, a tarefa de gerar em segundo plano |
| `servidor/ia.py` | O pedido à IA: prompt, ferramenta `deliver_tierlist` (JSON garantido), busca na web, reserva por crédito, `normalize()` |
| `servidor/provedor.py` | **Cópia idêntica** do `contato-ia/contato/provedor.py` (lado do modelo, pares de reserva, sem crédito, preço). Bug nele se corrige no mestre e se copia |
| `servidor/imagens.py` | Fandom, Wikipedia e Bing; download com trava de endereço público e checagem de bytes; guarda por hash |
| `servidor/armazem.py` | As tierlists em JSON; `clean()` garante que cada item fica num lugar só |
| `servidor/segredos.py` | Copiado do `central` (DPAPI) |
| `servidor/atualizador.py`, `iniciar.py` | Atualização pelas releases do GitHub, no modelo do `clave` |
| `app/js/app.js` | Lateral, caixa do pedido, acompanhamento da geração, salvamento automático |
| `app/js/board.js` | Fileiras, cartas, arrastar e soltar, teclado (1 a 9, 0, setas, Enter) |
| `app/js/drawer.js` | Gaveta: editar carta (trocar imagem por busca, link, arquivo, Ctrl+V), carta nova, Configurações |
| `app/js/export.js` | PNG de 2400 px desenhado num canvas |
| `testes/` | unittest com IA falsa (`falsos.py`); `test_provedor.py` é o mesmo dos outros projetos |

## 3. Decisões (não desfazer sem motivo novo)

- **A IA não busca imagem; o servidor busca.** A busca na web da API devolve páginas, não imagens. A IA devolve,
  por item, o título do artigo na Fandom (`fandom_wiki` + `fandom_title`), o título na Wikipedia e um termo de
  busca; o `imagens.py` tenta nessa ordem.
  - **Fandom primeiro** para ficção: a imagem principal do artigo é o retrato oficial do personagem.
  - **Wikipedia** ignora redirecionamento para seção (`tofragment`): "Trafalgar Law" leva à lista de
    personagens, cuja imagem é foto de grupo.
  - **Bing por `/images/async`**: a página normal `/images/search` às vezes respondeu a script com o resultado só
    da primeira palavra ("Trafalgar" virou a praça). E o resultado só é aceito sozinho se o título ou a página
    mencionar o nome do item (`mentions`); senão a carta fica "Sem imagem" e ele escolhe.
  - **DuckDuckGo fora**: em 06/11/2026 responde a script com desafio anti-robô. Contornar isso não se faz.
  - Conferido em 06/11/2026 com 20 personagens de One Piece: todos com a imagem certa.
- **Imagem sempre baixada para `dados/imagens`** (nome = SHA-1 dos bytes): a tierlist não quebra se o site
  mudar, e o canvas do PNG lê sem bloqueio de origem. SVG é recusado (pode levar script); limite de 8 MB;
  só endereço público (nada de 127.0.0.1 ou rede de casa, conferido também em cada redirecionamento).
- **JSON pela ferramenta `deliver_tierlist`** com `strict: true` e `tool_choice: auto` (forçar dá 400 no Sonnet
  5.5, Opus 5.5 e Fable 5.1). Se a IA responder em texto, um empurrão; `pause_turn` (busca longa) continua com o
  mesmo conteúdo.
- **Modelo padrão `claude-sonnet-5-5`, esforço médio**, pela pesquisa `.claude/pesquisas/modelos-claude.md`:
  forte e mais rápido que o Opus. Trocável em Configurações. IA dos dois lados, como os outros projetos: sem
  crédito no Claude, refaz no par do GPT (precisa da chave da OpenAI, opcional).
- **Busca na web**: `web_search_20260209` nos modelos que aceitam, `web_search_20250305` no Haiku. O custo
  mostrado soma tokens (preço do `provedor.py`) e US$ 0,01 por busca.
- **Segurança local** (como o `clave` e o `central`): só 127.0.0.1, `Host` conferido, toda `/api` exige o
  cabeçalho `X-Tierlist: 1` (página de outro site não manda sem preflight, que nunca é aprovado), escrita com
  `Origin` de fora é recusada. A chave nunca volta para a tela (só os 4 últimos caracteres).
- **Visual "placar de auditório"** (do print do Decathlon Yestalgia na biblioteca): borda preta grossa, sombra
  dura sem desfoque, placas de cor chapada nas fileiras, só a fonte Archivo (servida da pasta `app/fonts`, eixo
  de largura). Lateral escura, área de trabalho clara. Diferente de propósito da `tierlist-steam`.
- **Recorte das cartas puxado para o alto** (`object-position: 50% 12%`, e o mesmo no PNG): retrato de
  personagem e capa têm rosto e título em cima.

## 4. Testes e verificação

```
python -m unittest discover -s testes -t .      # nesta pasta; 82 testes, uns 5 s, sem rede
```

- Conferido em 06/11/2026 na demo, em tela larga e em monitor em pé: gerar (barra de progresso), as 20 imagens,
  gaveta de editar com 16 opções, teclado, arrastar para outra fileira, salvamento no servidor, exportar PNG,
  Configurações e a checagem de atualização. Console sem erro, nenhuma requisição falhando.
- **Nunca chamado com a chave real**: o Claude e o GPT de verdade não foram testados. Se der erro na primeira
  tierlist de verdade, os suspeitos são a combinação `strict` + busca na web e o texto do erro de saldo.
- O atualizador nunca rodou contra uma release de verdade (o repositório não tem release).

## 5. Fim de tarefa

Subir a versão (`versao.json` e `CHANGELOG.md`), commit, backup. Release é decisão dele.
