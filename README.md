# Poli English Duel

Jogo multiplayer de duelos para praticar inglês, com visual retro inspirado em terminal.

## Rodar localmente

```powershell
python server.py
```

Abra `http://localhost:8000`. Para iniciar uma partida demonstrativa contra um oponente virtual, use `http://localhost:8000/?demo=1`.

## Recursos

- Login com Google via Firebase Authentication.
- Duelo de tradução e duelo de palavras por sílaba.
- Modo multiplayer persistente `Word Radar`: descubra palavras inglesas por aproximação e aprenda traduções durante as tentativas.
- Timer de 10 segundos, três corações e XP.
- Dificuldades `easy`, `medium` e `hard`.
- Categorias: cotidiano, viagens, trabalho e tecnologia.
- Convites por link, revanche, abandono de partida, ranking e histórico.
- Validação autoritativa de respostas no backend Python.
- Feedback visual e sonoro opcional, timer numérico e convite via WhatsApp.

No `Word Radar`, o backend mantém a palavra secreta oculta. O jogador pode criar uma sala, retomar uma sala aberta ou entrar em uma existente, digitar uma palavra em português para receber uma sugestão inglesa e competir por XP com outras pessoas. A distância pedagógica considera tema, nível e semelhança lexical dentro da base curada: quanto menor o número, mais perto da resposta. Ao chegar em `0`, o jogador recebe bônus e vence a sala.

Para ampliar as sugestões offline português→inglês, o projeto também usa o dicionário livre [FreeDict eng-por](https://download.freedict.org/dictionaries/eng-por/0.3/), sob licença GPL-2.0-or-later. O índice processado possui mais de 15 mil verbetes ingleses e 17 mil traduções portuguesas. Nenhum dicionário finito cobre literalmente todas as palavras e flexões possíveis, mas essa camada oferece um fallback amplo além da curadoria pedagógica.

## Ativar Firebase e Google Login

1. No [console do Firebase](https://console.firebase.google.com/), abra o projeto `poligbrasil-2022`.
2. Em **Project settings > Your apps**, crie ou abra um app Web.
3. Copie a `apiKey` para `public/firebase-config.js`.
4. Em **Authentication > Sign-in method**, habilite **Google**.
5. Para permitir jogadores convidados durante o desenvolvimento, habilite também **Anonymous**.
6. Em **Realtime Database > Rules**, publique o conteúdo de `firebase.rules.json`.

O banco configurado é:

```text
https://poligbrasil-2022-default-rtdb.firebaseio.com/
```

## Estrutura

- `server.py`: servidor Python, API de partidas e validação de tokens Firebase.
- `data/vocabulary.json`: palavras iniciais dos dois modos.
- `scripts/build_vocabulary.py`: fonte curada e gerador do vocabulário JSON.
- `data/poli.db`: banco SQLite criado automaticamente pelo servidor.
- `public/`: frontend HTML, CSS e JavaScript.
- `firebase.rules.json`: bloqueia alterações diretas no Realtime Database.

## Arquitetura

O Firebase Authentication identifica os jogadores. O Python valida o token Firebase e processa as ações competitivas. Ranking, histórico e salas ficam no SQLite do servidor.

O navegador não grava mais partidas diretamente no Realtime Database. Isso impede que alguém altere XP, corações ou respostas pelo DevTools. Em uma implantação futura com múltiplas instâncias do backend, o SQLite pode ser substituído pelo Firebase Admin SDK ou por outro banco centralizado sem expor credenciais administrativas no navegador.

## Vocabulário

A base própria PT-BR usa como referência pedagógica a organização CEFR A1-B2 e as listas temáticas descritas pela [Oxford Learner's Dictionaries](https://www.oxfordlearnersdictionaries.com/us/about/wordlists/index.html). Ela não replica integralmente uma lista externa.

Para baixar ou atualizar a fonte externa MIT e regenerar `data/vocabulary.json`:

```powershell
python scripts/fetch_cefr_dataset.py
python scripts/fetch_freedict_dictionary.py
python scripts/build_vocabulary.py
```

O gerador também cria automaticamente os desafios de sílabas a partir das palavras inglesas cadastradas. Quando o dataset externo está disponível, ele incorpora até 6.000 palavras classificadas por nível para enriquecer esse modo.

Fonte externa: [Maximax67/Words-CEFR-Dataset](https://github.com/Maximax67/Words-CEFR-Dataset), disponibilizada sob licença MIT e construída a partir de CEFR-J, frequência e análise linguística. O banco bruto é baixado localmente e ignorado pelo Git; o JSON processado fica versionado.
