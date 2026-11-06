# Tierlist IA

Você escreve sobre o que é a tierlist, escolhe quantos itens quer, e a IA monta tudo: os itens, as fileiras
(S, A, B, C, D, F), a classificação e uma imagem para cada um. Depois é só arrastar para ajustar.

## Abrir

- Pelo Menu Iniciar: **Tierlist IA** (abre numa janela própria).
- Ou dois cliques em `abrir-no-navegador.bat`.

Na primeira vez, clique em **Configurações** (canto de baixo) e cole a chave da Anthropic. A chave fica guardada
criptografada pelo Windows, só neste PC. A da OpenAI é opcional: serve de reserva se o crédito do Claude acabar.

## Usar

1. Escreva o tema, do jeito que falaria: "os jogos da FromSoftware", "salgados de padaria", "personagens de
   Naruto pela força".
2. Escolha a quantidade de itens (5 a 60) e clique em **Montar tierlist**. Ctrl+Enter também funciona.
3. **A IA já classifica**: desligue se quiser os itens soltos em "Sem fileira" para você mesmo ranquear.
   **Pesquisar na web**: deixa a IA conferir coisa recente (lançamentos, elencos, temporada).

No tabuleiro:

- Arraste as cartas entre as fileiras.
- Clique numa carta e use o teclado: **1 a 9** manda para a fileira, **0** tira da fileira, **setas** mudam a
  ordem, **Enter** edita.
- **Duplo clique** numa carta: trocar a imagem (busca, link, arquivo ou Ctrl+V), mudar o nome, remover.
- Passe o mouse na placa da fileira para subir, descer, trocar a cor ou apagar. Clique no nome para renomear.
- **Fileira** e **Item** acrescentam; **Exportar PNG** salva a imagem da tierlist.
- Tudo salva sozinho. As tierlists ficam na lateral.

A IA não vê as imagens: ela diz o nome certo de cada item e o app busca a foto (wiki da Fandom, Wikipedia e
Bing). Quase sempre acerta; quando errar, é o duplo clique.

## Quanto custa

Cada tierlist mostra o custo estimado embaixo do título. Com o Sonnet 5.5 e a pesquisa na web fica em centavos
de dólar, tirado do crédito de API da sua conta da Anthropic.

## Licença

MIT (arquivo `LICENSE`). A fonte Archivo, em `app/fonts`, é da SIL Open Font License (`app/fonts/LICENSE.txt`).
