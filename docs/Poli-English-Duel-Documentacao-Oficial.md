# Poli English Duel

## Documento oficial do produto e da arquitetura

**Versão do documento:** 1.0  
**Data de referência:** 1 de junho de 2026  
**Status:** MVP publicado em produção  
**Endereço oficial:** https://voxdatagfurtado217.pythonanywhere.com  
**Projeto Firebase:** `poligbrasil-2022`

[PAGEBREAK]

# 1. Visão executiva

O **Poli English Duel** é uma plataforma web gamificada para prática de inglês por falantes de português brasileiro. O produto combina partidas multiplayer, feedback pedagógico imediato, progressão por XP e uma identidade visual retrô inspirada em terminais de desenvolvimento.

O objetivo central é transformar o estudo de vocabulário em sessões curtas e competitivas. Em vez de apresentar listas estáticas, o jogo oferece três experiências:

- **Translation Rush:** tradução entre inglês e português sob limite de tempo.
- **Syllable Strike:** formação de palavras inglesas a partir de uma sílaba.
- **Word Radar:** descoberta colaborativa e competitiva de uma palavra secreta por proximidade semântica pedagógica.

O MVP está publicado no PythonAnywhere, utiliza autenticação Google por meio do Firebase Authentication e mantém o estado competitivo sob controle do backend Python. Ranking, histórico, salas e tentativas são persistidos em SQLite.

## 1.1 Proposta de valor

- Prática ativa de vocabulário em vez de memorização passiva.
- Experiência multiplayer com salas compartilháveis.
- Feedback imediato após erros.
- Apoio pedagógico PT-BR → EN para iniciantes.
- Categorias e níveis de dificuldade.
- Arquitetura simples, econômica e adequada ao estágio atual do produto.

## 1.2 Público-alvo

- Estudantes brasileiros iniciantes e intermediários de inglês.
- Pessoas que desejam ampliar vocabulário em sessões rápidas.
- Amigos, colegas e grupos de estudo interessados em desafios multiplayer.

# 2. Escopo entregue

## 2.1 Funcionalidades disponíveis

| Área | Entrega |
| --- | --- |
| Autenticação | Login e logout com Google via Firebase Authentication |
| Identidade | Nome, UID e foto do usuário autenticado |
| Multiplayer | Criação de salas, entrada por código e atualização periódica do estado |
| Convites | Link copiável e compartilhamento pelo WhatsApp |
| Translation Rush | Tradução alternada EN → PT-BR e PT-BR → EN |
| Syllable Strike | Resposta com palavra inglesa iniciada pela sílaba exibida |
| Word Radar | Sala multiplayer persistente com tentativas compartilhadas |
| Progressão | Corações, XP, ranking global e histórico individual |
| Feedback | Animações, sons opcionais, contador numérico e resposta correta após erro |
| Conteúdo | Níveis, categorias, vocabulário curado e fallback FreeDict |
| Persistência | SQLite controlado pelo backend |
| Produção | Publicação WSGI Flask no PythonAnywhere |

## 2.2 Acesso sem login

Usuários não autenticados podem abrir a página inicial e consultar o ranking global. Os modos de jogo, o histórico e as operações de sala exigem autenticação.

Essa decisão evita partidas sem identidade verificável e protege o ranking contra gravações arbitrárias. O Firebase Anonymous Authentication está previsto como evolução possível para oferecer a opção **Jogar como convidado**, mas ainda não está exposto pela interface do MVP.

## 2.3 Elementos visuais presentes, mas não persistidos

A interface inicial apresenta uma área de missão diária como parte da ambientação visual. No MVP atual, essa seção ainda não representa missões persistidas ou recompensas processadas pelo backend.

# 3. Identidade visual e experiência

## 3.1 Direção visual

O projeto utiliza estética retrô inspirada em terminal e ferramentas de desenvolvimento:

- Fundo verde-escuro com alto contraste.
- Tipografia pixelada para títulos.
- Tipografia monoespaçada para textos e comandos.
- Scanlines discretas para efeito de monitor.
- Cores de apoio verde, roxo e âmbar.
- Textos de interface em formato semelhante a comandos: `login_google()`, `sound_on()` e `mute()`.

## 3.2 Fluxo principal

1. O visitante acessa a página inicial.
2. O ranking global é carregado publicamente.
3. O usuário realiza login com Google.
4. O usuário escolhe um modo.
5. Nos duelos tradicionais, escolhe dificuldade e categoria.
6. O sistema cria uma sala com código de seis caracteres.
7. O link pode ser copiado ou compartilhado via WhatsApp.
8. O segundo jogador entra utilizando o código ou link.
9. O backend controla rodadas, respostas, pontuação e encerramento.
10. Ao final, o placar completo é exibido e a partida é registrada.

# 4. Modos de jogo

## 4.1 Translation Rush

O **Translation Rush** é um duelo por turnos com limite de dez segundos por rodada.

### Regras

- Cada jogador inicia com três corações.
- O backend alterna a direção da tradução entre inglês e português.
- Uma resposta correta concede `100 XP` na partida.
- Uma resposta incorreta ou fora do prazo remove um coração.
- Após erro, a resposta correta é exibida.
- A partida termina quando um jogador perde os três corações.
- Não há repetição de palavra na mesma partida.
- Se o conteúdo disponível para o filtro escolhido acabar, a partida é encerrada por esgotamento de conteúdo.

### Exemplo

```text
Prompt: friend
Instrução: traduza para português
Resposta válida: amigo
```

## 4.2 Syllable Strike

O **Syllable Strike** é um duelo por turnos no qual o jogador precisa responder uma palavra inglesa iniciada pela sílaba exibida.

### Regras

- Cada jogador inicia com três corações.
- O backend escolhe uma sílaba cadastrada.
- A palavra enviada precisa existir entre os exemplos válidos do desafio.
- A palavra precisa ter pelo menos três caracteres.
- Uma resposta já utilizada na partida não pode ser repetida.
- Uma resposta correta concede `100 XP`.
- Erro ou tempo esgotado remove um coração.
- A partida termina quando um jogador perde os três corações.
- A sílaba apresentada também não se repete na mesma partida.

### Exemplo

```text
Prompt: fri
Resposta válida: friend
```

## 4.3 Word Radar

O **Word Radar** adapta a mecânica de descoberta por proximidade para um contexto pedagógico de aprendizagem de inglês.

### Objetivo

Encontrar a palavra secreta inglesa. O primeiro jogador que atingir distância `0` vence a sala.

### Regras

- A palavra secreta fica somente no backend.
- A sala permanece aberta até alguém encontrar a resposta exata.
- Os jogadores enviam palavras inglesas como tentativas.
- Quanto menor o número exibido, mais próxima está a tentativa.
- A tentativa exata recebe distância `0`.
- A mesma palavra não pode ser enviada novamente na sala.
- Jogadores acumulam pontos de acordo com a proximidade.
- Ao acertar a palavra secreta, o vencedor recebe bônus.
- Salas ainda não finalizadas permanecem listadas para que o jogador possa retomá-las.

### Apoio para iniciantes

Se o jogador conhece uma palavra em português, mas não sabe escrevê-la em inglês:

1. Digita a palavra em português.
2. O backend procura traduções válidas.
3. A interface apresenta sugestões em inglês.
4. O jogador aceita a sugestão e envia a tentativa inglesa.

Quando uma tentativa aparece no histórico, o jogador pode consultar sua tradução em português por meio do ícone de informação e do tooltip.

### Distância pedagógica

A distância considera:

- Igualdade exata da palavra.
- Similaridade lexical.
- Conceito semântico cadastrado.
- Categoria temática.
- Nível de dificuldade.

A fórmula prioriza relações pedagógicas explícitas da base curada. O fallback do dicionário amplia a cobertura, mas palavras sem metadados semânticos detalhados recebem uma aproximação mais simples.

# 5. Gamificação

## 5.1 Corações

Nos duelos tradicionais, cada jogador começa com três corações. Uma resposta incorreta ou o estouro do cronômetro remove um coração. A interface apresenta animação visual nessa perda.

## 5.2 XP e placar

- Resposta correta em duelo tradicional: `100 XP`.
- Word Radar: pontuação proporcional à proximidade.
- Word Radar exato: pontos de proximidade mais bônus de `100 XP`.
- Encerramento de duelo tradicional: atualização de ranking e histórico.
- Vitória em duelo tradicional: bônus adicional no cálculo persistido do ranking.

## 5.3 Ranking e histórico

O dashboard contém:

- **Top Players:** ranking global público ordenado por XP e vitórias.
- **Últimos Duelos:** histórico individual disponível após login.

Dados demonstrativos não entram no ranking nem no histórico.

## 5.4 Áudio

O jogo possui efeitos sonoros opcionais gerados no navegador. O estado de áudio é salvo localmente no browser por meio de `localStorage`.

# 6. Conteúdo pedagógico

## 6.1 Base curada

O arquivo `data/vocabulary.json` mantém o conteúdo principal utilizado pelos modos competitivos.

| Métrica | Quantidade |
| --- | ---: |
| Traduções curadas | 111 |
| Desafios de sílabas gerados | 173 |
| Palavras de nível easy | 60 |
| Palavras de nível medium | 33 |
| Palavras de nível hard | 18 |

## 6.2 Categorias

| Categoria | Identificador | Palavras curadas |
| --- | --- | ---: |
| Cotidiano | `everyday` | 42 |
| Viagens | `travel` | 24 |
| Trabalho | `work` | 22 |
| Tecnologia | `technology` | 23 |

## 6.3 Dicionário complementar FreeDict

O arquivo `data/freedict-index.json` amplia a capacidade de sugestão PT-BR → EN e a aceitação de palavras inglesas no Word Radar.

| Métrica | Quantidade |
| --- | ---: |
| Verbetes ingleses indexados | 15.770 |
| Traduções portuguesas indexadas | 17.299 |

O dicionário complementar é derivado do **FreeDict eng-por 0.3**, distribuído sob licença GPL-2.0-or-later.

## 6.4 Referências de conteúdo

- FreeDict eng-por: https://download.freedict.org/dictionaries/eng-por/0.3/
- Oxford Learner's Dictionaries Word Lists: https://www.oxfordlearnersdictionaries.com/us/about/wordlists/index.html
- Words CEFR Dataset: https://github.com/Maximax67/Words-CEFR-Dataset

O dataset CEFR externo é utilizado como fonte complementar para enriquecer o modo de sílabas. A curadoria principal PT-BR permanece própria do projeto.

## 6.5 Atualização da base

```bash
python scripts/fetch_cefr_dataset.py
python scripts/fetch_freedict_dictionary.py
python scripts/build_vocabulary.py
```

# 7. Arquitetura técnica

## 7.1 Visão geral

```text
Navegador
  |
  | HTML, CSS e JavaScript
  | Token Firebase no cabeçalho Authorization
  v
PythonAnywhere / uWSGI
  |
  v
app.py / Flask / WSGI
  |
  v
server.py / regras autoritativas do jogo
  |
  +--> SQLite: salas, Word Radar, ranking e histórico
  |
  +--> Firebase Identity Toolkit: validação do token do usuário
```

## 7.2 Frontend

Tecnologias:

- HTML5.
- CSS3 responsivo.
- JavaScript ES Modules.
- Firebase Web SDK carregado no navegador.
- Google Fonts: `Press Start 2P` e `Space Mono`.

Responsabilidades:

- Renderização das telas.
- Login e logout.
- Envio do token Firebase ao backend.
- Polling periódico das salas.
- Feedback visual, sonoro e timers.
- Compartilhamento de convite.

## 7.3 Backend local

O arquivo `server.py` disponibiliza um servidor local com `ThreadingHTTPServer`, útil para desenvolvimento:

```bash
python server.py
```

Endereço local:

```text
http://localhost:8000
```

## 7.4 Backend de produção

O arquivo `app.py` é a camada Flask/WSGI usada no PythonAnywhere. Ele reutiliza as regras implementadas em `server.py` e adapta o transporte HTTP ao ambiente uWSGI.

```bash
python app.py
```

Esse comando serve apenas para teste local da entrada de produção. No PythonAnywhere, o carregamento ocorre pelo arquivo WSGI configurado na plataforma.

## 7.5 Persistência SQLite

O arquivo `data/poli.db` é criado automaticamente e contém quatro tabelas.

| Tabela | Responsabilidade |
| --- | --- |
| `rooms` | Estado serializado dos duelos Translation Rush e Syllable Strike |
| `contexts` | Estado serializado das salas Word Radar |
| `rankings` | XP, vitórias, derrotas e partidas por usuário |
| `history` | Histórico individual de duelos concluídos |

Salas e contextos são armazenados como payload JSON. Ranking e histórico utilizam colunas relacionais para consultas ordenadas.

## 7.6 Concorrência

O backend utiliza:

- `threading.RLock()` para proteger operações críticas.
- SQLite em modo WAL.
- Atualizações autoritativas no servidor.

Essa abordagem atende ao MVP hospedado em uma única instância. Para escalar horizontalmente, será necessário mover a persistência para um banco centralizado e adotar coordenação entre instâncias.

# 8. Autenticação e segurança

## 8.1 Firebase Authentication

O frontend utiliza Firebase Authentication com provedor Google. Depois do login, o navegador envia o token no cabeçalho:

```text
Authorization: Bearer <firebase-id-token>
```

O backend valida o token consultando o Firebase Identity Toolkit e mantém um cache temporário de cinco minutos para reduzir chamadas externas.

## 8.2 Dados públicos do Firebase

O arquivo `public/firebase-config.js` contém a configuração pública do Web App Firebase. A `apiKey` do Firebase para aplicações web identifica o projeto; ela não deve ser tratada como segredo administrativo.

Credenciais administrativas, chaves privadas e `client secret` OAuth não são enviados ao navegador.

## 8.3 Realtime Database

O Firebase Realtime Database foi configurado inicialmente, porém o navegador não grava o estado das partidas diretamente nele. As regras publicadas bloqueiam leitura e escrita:

```json
{
  "rules": {
    ".read": false,
    ".write": false
  }
}
```

O estado competitivo fica no SQLite do backend. Isso impede que um jogador altere XP, corações, respostas ou salas diretamente pelo DevTools.

## 8.4 Palavra secreta protegida

No Word Radar, a palavra secreta não é enviada ao frontend enquanto a partida está ativa. A resposta permanece no backend e apenas o resultado público das tentativas é retornado.

## 8.5 Limites atuais

- O MVP utiliza SQLite e uma única instância.
- Não há painel administrativo.
- Não há rate limiting específico por IP ou usuário.
- Não há rotina automatizada de backup.
- Não há moderação de nomes além dos dados recebidos do provedor de autenticação.

# 9. API HTTP

## 9.1 Endpoints públicos

| Método | Endpoint | Finalidade |
| --- | --- | --- |
| `GET` | `/` | Interface principal |
| `GET` | `/api/health` | Verificação de saúde |
| `GET` | `/api/vocabulary` | Quantidade de traduções e sílabas |
| `GET` | `/api/ranking` | Ranking global |

## 9.2 Endpoints autenticados de duelos

| Método | Endpoint | Finalidade |
| --- | --- | --- |
| `POST` | `/api/rooms` | Criar sala |
| `GET` | `/api/rooms/<code>` | Consultar estado |
| `POST` | `/api/rooms/<code>/join` | Entrar na sala |
| `POST` | `/api/rooms/<code>/answer` | Enviar resposta |
| `POST` | `/api/rooms/<code>/leave` | Abandonar sala |
| `POST` | `/api/rooms/<code>/rematch` | Solicitar revanche |
| `GET` | `/api/history` | Consultar histórico pessoal |

## 9.3 Endpoints autenticados do Word Radar

| Método | Endpoint | Finalidade |
| --- | --- | --- |
| `POST` | `/api/contexts` | Criar sala Word Radar |
| `GET` | `/api/contexts` | Listar salas abertas do usuário |
| `GET` | `/api/contexts/<code>` | Consultar estado |
| `POST` | `/api/contexts/<code>/join` | Entrar em sala existente |
| `POST` | `/api/contexts/<code>/suggest` | Obter sugestão PT-BR → EN |
| `POST` | `/api/contexts/<code>/guess` | Enviar tentativa inglesa |

# 10. Estrutura do repositório

| Caminho | Descrição |
| --- | --- |
| `app.py` | Entrada Flask/WSGI de produção |
| `server.py` | Motor do jogo, API local e regras autoritativas |
| `requirements.txt` | Dependências Python de produção |
| `public/index.html` | Estrutura visual |
| `public/styles.css` | Tema retrô e responsividade |
| `public/app.js` | Estado da interface e comunicação com API |
| `public/firebase-config.js` | Configuração pública Firebase |
| `data/vocabulary.json` | Vocabulário curado |
| `data/freedict-index.json` | Índice complementar PT-BR ↔ EN |
| `data/poli.db` | Banco SQLite gerado em execução |
| `scripts/build_vocabulary.py` | Geração do vocabulário |
| `scripts/fetch_cefr_dataset.py` | Download do dataset CEFR |
| `scripts/fetch_freedict_dictionary.py` | Processamento FreeDict |
| `tests/test_game.py` | Testes do motor |
| `tests/test_wsgi.py` | Testes da entrada Flask |
| `firebase.rules.json` | Regras restritivas do Realtime Database |

# 11. Implantação no PythonAnywhere

## 11.1 Produção atual

| Item | Valor |
| --- | --- |
| Plataforma | PythonAnywhere |
| URL | https://voxdatagfurtado217.pythonanywhere.com |
| Diretório | `/home/voxdatagfurtado217/PoliBrasil` |
| Virtualenv | `/home/voxdatagfurtado217/.virtualenvs/poli-env` |
| Framework de publicação | Flask via WSGI |
| Versão Python configurada | Python 3.13 |

## 11.2 Instalação

```bash
mkvirtualenv --python=/usr/bin/python3.13 poli-env
pip install -r /home/voxdatagfurtado217/PoliBrasil/requirements.txt
```

## 11.3 Arquivo WSGI

```python
import sys

path = "/home/voxdatagfurtado217/PoliBrasil"
if path not in sys.path:
    sys.path.insert(0, path)

from app import app as application
```

## 11.4 Domínio autorizado no Firebase

Para permitir login Google em produção, o domínio abaixo deve permanecer cadastrado em **Firebase Console > Authentication > Settings > Authorized domains**:

```text
voxdatagfurtado217.pythonanywhere.com
```

## 11.5 Health check

```text
https://voxdatagfurtado217.pythonanywhere.com/api/health
```

Resposta esperada:

```json
{"database":"sqlite","game":"Poli English Duel","status":"ok","transport":"wsgi"}
```

# 12. Operação e manutenção

## 12.1 Publicar uma atualização

1. Testar localmente.
2. Gerar backup da versão estável.
3. Enviar os arquivos alterados ao PythonAnywhere.
4. Abrir a aba **Web**.
5. Clicar em **Reload**.
6. Validar `/api/health`.
7. Validar página inicial, login e criação de sala.

## 12.2 Arquivos que não devem ser enviados

- Backups `.rar` ou `.zip`.
- Pasta `.git/`.
- Pasta `__pycache__/`.
- Arquivos `*.pyc`.
- Bancos locais de teste.
- Fontes externas brutas já processadas.

## 12.3 Backup do banco de produção

O arquivo prioritário é:

```text
/home/voxdatagfurtado217/PoliBrasil/data/poli.db
```

Recomenda-se baixar uma cópia antes de atualizações relevantes. Esse arquivo contém ranking, histórico e salas persistidas.

## 12.4 Checklist de validação pós-deploy

- Abrir `/api/health`.
- Abrir a página inicial.
- Confirmar carregamento do CSS e JavaScript.
- Realizar login Google.
- Confirmar carregamento do ranking.
- Criar sala Translation Rush.
- Entrar com segundo usuário.
- Validar cronômetro, corações e resposta correta após erro.
- Criar sala Syllable Strike.
- Confirmar ausência de repetição.
- Criar sala Word Radar.
- Validar sugestão em português.
- Retomar sala Word Radar aberta.
- Validar encerramento ao atingir distância `0`.

# 13. Qualidade e testes

O projeto possui testes automatizados para o motor e para a camada WSGI.

## 13.1 Comandos de validação

```bash
python -m py_compile server.py app.py
python -m unittest discover -s tests -v
node --check public/app.js
git diff --check
```

## 13.2 Cobertura funcional atual

- Ocultação de respostas enviadas ao frontend.
- Feedback da resposta correta após erro.
- Pontuação e perda de corações.
- Rejeição de palavra inválida.
- Ranking e histórico.
- Exclusão de partidas demo.
- Ausência de repetição de prompts.
- Filtros por categoria.
- Esgotamento de conteúdo.
- Proteção da palavra secreta.
- Sugestões PT-BR → EN.
- Fallback FreeDict.
- Distância semântica pedagógica.
- Encerramento do Word Radar por acerto.
- Entrada WSGI, frontend e autenticação obrigatória.

# 14. Limitações e próximos passos

## 14.1 Prioridade alta

- Implementar backup periódico do SQLite.
- Adicionar rate limiting aos endpoints de tentativa e criação de sala.
- Criar opção **Jogar como convidado** com Firebase Anonymous Authentication.
- Adicionar monitoramento simples do health check.

## 14.2 Evolução de produto

- Missões diárias persistentes.
- Perfil detalhado do jogador.
- Estatísticas por categoria e dificuldade.
- Sistema de conquistas.
- Curadoria editorial ampliada da base semântica do Word Radar.
- Painel administrativo para conteúdo.
- Salas públicas e matchmaking.

## 14.3 Evolução de arquitetura

- Migrar SQLite para banco centralizado quando houver necessidade de múltiplas instâncias.
- Adotar filas ou eventos para recursos assíncronos.
- Introduzir testes end-to-end automatizados.
- Avaliar observabilidade com logs estruturados.

# 15. Glossário

| Termo | Definição |
| --- | --- |
| Backend autoritativo | Servidor que decide respostas válidas, pontuação e estado das partidas |
| CEFR | Referência europeia de níveis de proficiência linguística |
| Firebase Authentication | Serviço utilizado para login Google e identificação dos usuários |
| FreeDict | Dicionário livre usado como fallback de traduções |
| Polling | Atualização periódica do estado por requisições HTTP |
| SQLite | Banco de dados local persistente usado pelo backend |
| WSGI | Interface padrão para publicar aplicações Python na web |
| Word Radar | Modo de descoberta de palavra secreta por proximidade pedagógica |

# 16. Conclusão

O **Poli English Duel** saiu de uma ideia de duelo de traduções para um MVP online com três modos, autenticação, persistência, ranking, histórico, conteúdo ampliado e uma arquitetura preparada para evoluir.

O desenho atual privilegia simplicidade operacional e proteção das regras competitivas. A interface permanece leve, o backend mantém autoridade sobre os resultados e a base pedagógica pode crescer de forma incremental.

---

**Documento oficial do Poli English Duel**  
**Versão 1.0 — 1 de junho de 2026**
