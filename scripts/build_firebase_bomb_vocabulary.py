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


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    return re.sub(r"[^a-z]", "", "".join(char for char in text if unicodedata.category(char) != "Mn"))


def read_hunspell(url: str) -> set[str]:
    with urllib.request.urlopen(url, timeout=30) as response:
        lines = response.read().decode("utf-8-sig", errors="ignore").splitlines()
    words = set()
    for line in lines[1:]:
        word = normalize(line.split("/", 1)[0].strip())
        if len(word) >= 3:
            words.add(word)
    return words


def build_chunks() -> dict:
    freedict = json.loads(FREEDICT.read_text(encoding="utf-8"))
    languages = {
        "en": set(freedict["english"]),
        "pt": set(freedict["portuguese"]),
    }
    for language, url in SOURCES.items():
        languages[language].update(read_hunspell(url))
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


def main() -> None:
    payload = build_chunks()
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Arquivo gerado: {OUTPUT}")
    print(f"Palavras: {payload['metadata']['words']}")
    print(f"Tamanho: {OUTPUT.stat().st_size / 1024 / 1024:.2f} MiB")
    print("Importe este JSON no nó /bombVocabulary do Firebase Realtime Database.")


if __name__ == "__main__":
    main()
