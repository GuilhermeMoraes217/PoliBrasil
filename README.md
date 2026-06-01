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
- Timer de 10 segundos, três corações e XP.
- Dificuldades `easy`, `medium` e `hard`.
- Convites por link, revanche, abandono de partida, ranking e histórico.
- Validação autoritativa de respostas no backend Python.

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
- `data/poli.db`: banco SQLite criado automaticamente pelo servidor.
- `public/`: frontend HTML, CSS e JavaScript.
- `firebase.rules.json`: bloqueia alterações diretas no Realtime Database.

## Arquitetura

O Firebase Authentication identifica os jogadores. O Python valida o token Firebase e processa as ações competitivas. Ranking, histórico e salas ficam no SQLite do servidor.

O navegador não grava mais partidas diretamente no Realtime Database. Isso impede que alguém altere XP, corações ou respostas pelo DevTools. Em uma implantação futura com múltiplas instâncias do backend, o SQLite pode ser substituído pelo Firebase Admin SDK ou por outro banco centralizado sem expor credenciais administrativas no navegador.
