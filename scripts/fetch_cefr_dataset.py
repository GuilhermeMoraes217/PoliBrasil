from pathlib import Path
from urllib.request import urlretrieve


SOURCE = "https://raw.githubusercontent.com/Maximax67/Words-CEFR-Dataset/main/word_cefr_minified.db"
DESTINATION = Path(__file__).resolve().parents[1] / "data" / "word_cefr_minified.db"


def main():
    print("Baixando Words-CEFR-Dataset (MIT)...")
    urlretrieve(SOURCE, DESTINATION)
    print(f"Dataset salvo em {DESTINATION}")


if __name__ == "__main__":
    main()
