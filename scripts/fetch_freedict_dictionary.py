from __future__ import annotations

import json
import tarfile
import unicodedata
import urllib.request
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "freedict-eng-por-0.3.src.tar.xz"
DESTINATION = ROOT / "data" / "freedict-index.json"
SOURCE = "https://download.freedict.org/dictionaries/eng-por/0.3/freedict-eng-por-0.3.src.tar.xz"
NAMESPACE = {"tei": "http://www.tei-c.org/ns/1.0"}


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    return "".join(char for char in text if unicodedata.category(char) != "Mn").strip()


def clean(value: str) -> str:
    return " ".join(value.split()).strip(" ;,")


def main():
    print("Baixando FreeDict eng-por 0.3 (GPL-2.0-or-later)...")
    urllib.request.urlretrieve(SOURCE, ARCHIVE)
    with tarfile.open(ARCHIVE, "r:xz") as archive:
        xml = archive.extractfile("eng-por/eng-por.tei").read()
    root = ElementTree.fromstring(xml)
    english = {}
    portuguese = defaultdict(list)
    for entry in root.findall(".//tei:entry", NAMESPACE):
        headword = clean(entry.findtext("./tei:form/tei:orth", default="", namespaces=NAMESPACE))
        translations = []
        for quote in entry.findall(".//tei:cit[@type='trans']/tei:quote", NAMESPACE):
            value = clean("".join(quote.itertext()))
            if value and value not in translations:
                translations.append(value)
        if not headword or not translations:
            continue
        english[normalize(headword)] = {"word": headword, "translations": translations}
        for translation in translations:
            key = normalize(translation)
            if headword not in portuguese[key]:
                portuguese[key].append(headword)
    payload = {
        "metadata": {"source": SOURCE, "license": "GPL-2.0-or-later", "headwords": len(english)},
        "english": english,
        "portuguese": dict(portuguese),
    }
    DESTINATION.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{len(english)} verbetes e {len(portuguese)} traduções indexadas em {DESTINATION}")


if __name__ == "__main__":
    main()
