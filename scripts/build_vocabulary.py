from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path


# Base propria PT-BR inspirada na organizacao CEFR e nas listas tematicas Oxford.
# Formato: english, traducoes separadas por "|", categoria, nivel interno.
WORDS = """
apple|maçã|everyday|easy
book|livro|everyday|easy
coffee|café|everyday|easy
family|família|everyday|easy
friend|amigo|amiga|everyday|easy
house|casa|everyday|easy
music|música|everyday|easy
school|escola|everyday|easy
street|rua|everyday|easy
window|janela|everyday|easy
breakfast|café da manhã|everyday|easy
chair|cadeira|everyday|easy
clothes|roupas|everyday|easy
dinner|jantar|everyday|easy
garden|jardim|everyday|easy
kitchen|cozinha|everyday|easy
neighbor|vizinho|vizinha|everyday|medium
advice|conselho|everyday|medium
appointment|compromisso|consulta|everyday|medium
choice|escolha|everyday|medium
habit|hábito|costume|everyday|medium
knowledge|conhecimento|everyday|medium
lifestyle|estilo de vida|everyday|medium
neighborhood|vizinhança|everyday|medium
purpose|propósito|objetivo|everyday|medium
awareness|consciência|everyday|hard
commitment|compromisso|everyday|hard
household|família|lar|everyday|hard
willingness|disposição|everyday|hard
acquaintance|conhecido|conhecida|everyday|hard
airport|aeroporto|travel|easy
beach|praia|travel|easy
bridge|ponte|travel|easy
bus|ônibus|travel|easy
city|cidade|travel|easy
hotel|hotel|travel|easy
journey|jornada|viagem|travel|easy
map|mapa|travel|easy
passport|passaporte|travel|easy
ticket|passagem|bilhete|travel|easy
train|trem|travel|easy
trip|viagem|travel|easy
luggage|bagagem|travel|medium
boarding|embarque|travel|medium
destination|destino|travel|medium
departure|partida|saída|travel|medium
itinerary|roteiro|itinerário|travel|medium
landmark|ponto turístico|travel|medium
route|rota|caminho|travel|medium
sightseeing|turismo|passeio turístico|travel|medium
accommodation|hospedagem|acomodação|travel|hard
customs|alfândega|travel|hard
layover|escala|conexão|travel|hard
overseas|exterior|além-mar|travel|hard
work|trabalho|work|easy
job|emprego|trabalho|work|easy
boss|chefe|work|easy
office|escritório|work|easy
team|equipe|time|work|easy
meeting|reunião|work|easy
email|e-mail|work|easy
company|empresa|work|easy
career|carreira|work|easy
salary|salário|work|easy
deadline|prazo|data limite|work|medium
feedback|retorno|avaliação|work|medium
goal|meta|objetivo|work|medium
interview|entrevista|work|medium
leadership|liderança|work|medium
manager|gerente|gestor|work|medium
schedule|agenda|cronograma|work|medium
task|tarefa|work|medium
achievement|conquista|realização|work|hard
stakeholder|parte interessada|work|hard
workload|carga de trabalho|work|hard
promotion|promoção|work|hard
computer|computador|technology|easy
cloud|nuvem|technology|easy
file|arquivo|technology|easy
keyboard|teclado|technology|easy
mouse|mouse|technology|easy
screen|tela|technology|easy
website|site|technology|easy
password|senha|technology|easy
network|rede|technology|easy
app|aplicativo|app|technology|easy
backup|cópia de segurança|backup|technology|medium
browser|navegador|technology|medium
database|banco de dados|technology|medium
device|dispositivo|aparelho|technology|medium
download|baixar|download|technology|medium
software|programa|software|technology|medium
storage|armazenamento|technology|medium
update|atualização|atualizar|technology|medium
algorithm|algoritmo|technology|hard
bandwidth|largura de banda|technology|hard
encryption|criptografia|technology|hard
framework|estrutura|framework|technology|hard
throughput|taxa de transferência|technology|hard
""".strip()

BLOCKED_SYLLABLES = {"dn", "dj", "fn", "hm", "hr", "kb", "ng", "pn", "ps", "rh", "tz"}


def parse_words():
    translations = []
    for line in WORDS.splitlines():
        english, *values, category, difficulty = line.split("|")
        translations.append({"en": english, "pt": values, "category": category, "difficulty": difficulty})
    return translations


def internal_level(cefr_level):
    if cefr_level < 3:
        return "easy"
    if cefr_level < 5:
        return "medium"
    return "hard"


def load_cefr_words():
    database_path = Path(__file__).resolve().parents[1] / "data" / "word_cefr_minified.db"
    if not database_path.exists():
        return []
    with sqlite3.connect(database_path) as database:
        rows = database.execute(
            """
            SELECT words.word, MIN(word_pos.level) AS level, MAX(word_pos.frequency_count) AS frequency
            FROM words JOIN word_pos ON words.word_id = word_pos.word_id
            WHERE words.word GLOB '[a-z]*' AND LENGTH(words.word) BETWEEN 3 AND 16
            GROUP BY words.word
            ORDER BY frequency DESC
            LIMIT 6000
            """
        ).fetchall()
    return [{"word": word, "difficulty": internal_level(level)} for word, level, _ in rows if word.isalpha()]


def build_syllables(translations, cefr_words):
    groups = defaultdict(list)
    metadata = {}
    for item in translations:
        syllable = item["en"][:2]
        groups[syllable].append(item["en"])
        metadata.setdefault(syllable, {"category": item["category"], "difficulty": item["difficulty"]})
    for item in cefr_words:
        syllable = item["word"][:2]
        if item["word"] not in groups[syllable] and len(groups[syllable]) < 80:
            groups[syllable].append(item["word"])
        metadata.setdefault(syllable, {"category": "general", "difficulty": item["difficulty"]})
    return [
        {"syllable": syllable, "examples": words, **metadata[syllable]}
        for syllable, words in sorted(groups.items())
        if len(words) >= 3 and syllable not in BLOCKED_SYLLABLES
    ]


def main():
    translations = parse_words()
    cefr_words = load_cefr_words()
    payload = {
        "metadata": {
            "version": 2,
            "method": "Curadoria própria PT-BR inspirada na organização CEFR A1-B2 e em listas temáticas Oxford.",
            "reference": "https://www.oxfordlearnersdictionaries.com/us/about/wordlists/index.html",
            "externalSyllableWords": len(cefr_words),
            "externalDataset": "https://github.com/Maximax67/Words-CEFR-Dataset (MIT)",
        },
        "translations": translations,
        "syllables": build_syllables(translations, cefr_words),
    }
    destination = Path(__file__).resolve().parents[1] / "data" / "vocabulary.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(translations)} traduções e {len(payload['syllables'])} sílabas gravadas em {destination}")


if __name__ == "__main__":
    main()
