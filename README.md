# Poli English Duel

Jogo multiplayer de duelos para praticar inglês, com visual retro inspirado em terminal.

## Documentação oficial

- [Documento Word](docs/Poli-English-Duel-Documentacao-Oficial.docx)
- [Fonte Markdown versionável](docs/Poli-English-Duel-Documentacao-Oficial.md)

## Rodar localmente

```powershell
python server.py
```

Abra `http://localhost:8000`. Para habilitar localmente partidas demonstrativas contra um oponente virtual:

```powershell
$env:POLI_ALLOW_DEMO="1"
python server.py
```

Depois use `http://localhost:8000/?demo=1`. Em produção, não configure `POLI_ALLOW_DEMO`.

Para testar localmente a mesma entrada WSGI usada em produção:

```powershell
pip install -r requirements.txt
python app.py
```

## Hospedar no PythonAnywhere

1. Envie o projeto para `/home/SEU_USUARIO/PoliBrasil`.
2. Em um console Bash, crie o ambiente e instale as dependências:

```bash
mkvirtualenv --python=/usr/bin/python3.13 poli-env
pip install -r /home/SEU_USUARIO/PoliBrasil/requirements.txt
```

3. Em **Web > Add a new web app**, escolha **Manual configuration** e a mesma versão do Python.
4. Em **Virtualenv**, informe `/home/SEU_USUARIO/.virtualenvs/poli-env`.
5. No arquivo WSGI exibido na aba **Web**, substitua o conteúdo pelo trecho abaixo, ajustando `SEU_USUARIO`:

```python
import sys

path = "/home/SEU_USUARIO/PoliBrasil"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
```

6. Clique em **Reload** e abra `https://SEU_USUARIO.pythonanywhere.com`.
7. No Firebase, adicione `SEU_USUARIO.pythonanywhere.com` em **Authentication > Settings > Authorized domains** para liberar o login Google.

O PythonAnywhere importa `app.py` via WSGI. Não execute `python server.py` em produção. O SQLite continua persistente em `data/poli.db`; faça backup periódico desse arquivo.

## Recursos

- Login com Google via Firebase Authentication.
- Duelo de tradução e duelo de palavras por sílaba.
- Modo multiplayer persistente `Word Radar`: descubra palavras inglesas por aproximação e aprenda traduções durante as tentativas.
- Modo multiplayer `Word Bomb`: sala para até oito jogadores, lobby com confirmação de pronto, início controlado pelo host, sílaba em qualquer parte da palavra e digitação ao vivo via Firebase Realtime Database.
- Timer de 10 segundos, três corações e XP.
- Dificuldades `easy`, `medium` e `hard`.
- Categorias: cotidiano, viagens, trabalho e tecnologia.
- Convites por link, revanche, abandono de partida, ranking e histórico.
- Validação autoritativa de respostas no backend Python.
- Feedback visual e sonoro opcional, timer numérico e convite via WhatsApp.
- Trilhas lounge opcionais geradas no navegador, sem arquivos de áudio pesados.

No `Word Radar`, o backend mantém a palavra secreta oculta. O jogador pode criar uma sala, retomar uma sala aberta ou entrar em uma existente, digitar uma palavra em português para receber uma sugestão inglesa e competir por XP com outras pessoas. A distância pedagógica considera tema, nível e semelhança lexical dentro da base curada: quanto menor o número, mais perto da resposta. Ao chegar em `0`, o jogador recebe bônus e vence a sala.

Para ampliar as sugestões offline português→inglês, o projeto também usa o dicionário livre [FreeDict eng-por](https://download.freedict.org/dictionaries/eng-por/0.3/), sob licença GPL-2.0-or-later. O índice processado possui mais de 15 mil verbetes ingleses e 17 mil traduções portuguesas. Nenhum dicionário finito cobre literalmente todas as palavras e flexões possíveis, mas essa camada oferece um fallback amplo além da curadoria pedagógica.

## Vocabulário amplo do Word Bomb no Firebase

O `Word Bomb` pode consultar blocos remotos particionados por idioma e prefixo no Realtime Database. O gerador combina o FreeDict local com os dicionários Hunspell `en_US` e `pt_BR` do repositório oficial [LibreOffice/dictionaries](https://github.com/LibreOffice/dictionaries):

```powershell
python scripts/build_firebase_bomb_vocabulary.py
```

O arquivo ignorado `data/firebase-bomb-vocabulary.json` é gerado localmente. No Firebase Console, abra **Realtime Database > Data**, crie ou selecione o nó `/bombVocabulary` e use **Import JSON** com esse arquivo. Depois publique `firebase.rules.json`.

O backend consulta somente o bloco necessário, por exemplo `/bombVocabulary/chunks/pt/pa`, e mantém cache em memória. Se o Firebase estiver indisponível, a base local continua funcionando. Para desativar consultas remotas, configure `POLI_REMOTE_BOMB_VOCABULARY=0`.

## Ativar Firebase e Google Login

1. No [console do Firebase](https://console.firebase.google.com/), abra o projeto `poligbrasil-2022`.
2. Em **Project settings > Your apps**, crie ou abra um app Web.
3. Copie a `apiKey` para `public/firebase-config.js`.
4. Em **Authentication > Sign-in method**, habilite **Google**.
5. Em **Realtime Database > Rules**, publique o conteúdo de `firebase.rules.json`.

O banco configurado é:

```text
https://poligbrasil-2022-default-rtdb.firebaseio.com/
```

## Estrutura

- `server.py`: servidor Python, API de partidas e validação de tokens Firebase.
- `data/vocabulary.json`: palavras iniciais dos dois modos.
- `scripts/build_vocabulary.py`: fonte curada e gerador do vocabulário JSON.
- `scripts/build_firebase_bomb_vocabulary.py`: gera o payload remoto particionado do Word Bomb.
- `data/poli.db`: banco SQLite criado automaticamente pelo servidor.
- `public/`: frontend HTML, CSS e JavaScript.
- `firebase.rules.json`: libera somente o texto temporário digitado no `Word Bomb`; estado competitivo permanece bloqueado.

## Arquitetura

O Firebase Authentication identifica os jogadores. O Python valida o token Firebase e processa as ações competitivas. Ranking, histórico e salas ficam no SQLite do servidor.

O navegador não grava partidas diretamente no Realtime Database. Isso impede que alguém altere XP, corações ou respostas pelo DevTools. No `Word Bomb`, o Firebase transmite apenas o rascunho temporário de digitação do próprio usuário autenticado. Em uma implantação futura com múltiplas instâncias do backend, o SQLite pode ser substituído pelo Firebase Admin SDK ou por outro banco centralizado sem expor credenciais administrativas no navegador.

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
