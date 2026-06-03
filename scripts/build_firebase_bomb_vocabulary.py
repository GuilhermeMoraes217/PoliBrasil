from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FREEDICT = ROOT / "data" / "freedict-index.json"
OUTPUT = ROOT / "data" / "firebase-bomb-vocabulary.json"
SOURCES = {
    "en": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/en/en_US.dic",
    "pt": "https://raw.githubusercontent.com/LibreOffice/dictionaries/master/pt_BR/pt_BR.dic",
}
EXTRA_WORDS = {
    "pt": {
        "tarado", "tarada", "tarados", "taradas",
        "acai", "bacaba", "bacuri", "belem", "breu", "carimbo", "chibe", "cupuacu",
        "curua", "egua", "farinha", "igarape", "jambu", "mani", "manicoba", "marajo",
        "marajoara", "miriti", "mucura", "nazare", "paidegua", "paraense", "pato",
        "pavulagem", "pirarucu", "pupunha", "tacaca", "tapereba", "tucupi", "veropa",
    }
}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    return re.sub(r"[^a-z]", "", "".join(char for char in text if unicodedata.category(char) != "Mn"))


def normalized_words(values) -> set[str]:
    words = set()
    for value in values:
        source = value.strip()
        if not source or any(not (char.isalpha() or char in "-'’") for char in source):
            continue
        word = normalize(source)
        if 3 <= len(word) <= 64:
            words.add(word)
    return words


def read_hunspell(url: str) -> set[str]:
    with urllib.request.urlopen(url, timeout=30) as response:
        lines = response.read().decode("utf-8-sig", errors="ignore").splitlines()
    return normalized_words(line.split("/", 1)[0] for line in lines[1:])


def build_chunks() -> dict:
    freedict = json.loads(FREEDICT.read_text(encoding="utf-8"))
    languages = {
        "en": normalized_words(freedict["english"]),
        "pt": normalized_words(freedict["portuguese"]),
    }
    for language, url in SOURCES.items():
        languages[language].update(read_hunspell(url))
    for language, words in EXTRA_WORDS.items():
        languages.setdefault(language, set()).update(normalized_words(words))
    chunks = {}
    for language, words in languages.items():
        chunks[language] = {}
        for word in sorted(words):
            chunks[language].setdefault(word[:2], {})[word] = True
    return {
        "metadata": {
            "source": "FreeDict eng-por 0.3 + LibreOffice Hunspell en_US and pt_BR",
            "format": "prefix chunks for Poli English Duel Word Bomb",
            "words": {language: len(words) for language, words in languages.items()},
        },
        "chunks": chunks,
    }


def validate_firebase_keys(payload: dict) -> None:
    def walk(node) -> None:
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if not key or any(char in key for char in ".#$[]/"):
                raise ValueError(f"Chave invalida para Firebase: {key!r}")
            walk(value)

    walk(payload)


def main() -> None:
    payload = build_chunks()
    validate_firebase_keys(payload)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Arquivo gerado: {OUTPUT}")
    print(f"Palavras: {payload['metadata']['words']}")
    print(f"Tamanho: {OUTPUT.stat().st_size / 1024 / 1024:.2f} MiB")
    print("Importe este JSON no nó /bombVocabulary do Firebase Realtime Database.")


if __name__ == "__main__":
    main()
