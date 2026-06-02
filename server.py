from __future__ import annotations

import json
import mimetypes
import os
import random
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from contextlib import closing
from difflib import SequenceMatcher
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = ROOT / "data" / "vocabulary.json"
FREEDICT_DATA = ROOT / "data" / "freedict-index.json"
DATABASE = ROOT / "data" / "poli.db"
FIREBASE_API_KEY = "AIzaSyBcsiGC1h_tBTJrlb2CE5DWxHVtFUimWPE"
FIREBASE_DATABASE_URL = "https://poligbrasil-2022-default-rtdb.firebaseio.com"
ROUND_SECONDS = 10
BOMB_MAX_PLAYERS = 8
LOCK = threading.RLock()
TOKEN_CACHE: dict[str, tuple[float, dict]] = {}
ALLOW_DEMO = os.getenv("POLI_ALLOW_DEMO", "").lower() in {"1", "true", "yes"}
REMOTE_BOMB_VOCABULARY = os.getenv("POLI_REMOTE_BOMB_VOCABULARY", "1").lower() not in {"0", "false", "no"}
REMOTE_BOMB_CACHE: dict[tuple[str, str], set[str]] = {}

with DATA.open(encoding="utf-8") as vocabulary_file:
    VOCABULARY = json.load(vocabulary_file)
with FREEDICT_DATA.open(encoding="utf-8") as freedict_file:
    FREEDICT = json.load(freedict_file)


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    return re.sub(r"[^a-z]", "", "".join(char for char in text if unicodedata.category(char) != "Mn"))


def progression_from_xp(xp: int) -> dict:
    xp = max(0, int(xp))
    absolute_level = min(30, xp // 500 + 1)
    if absolute_level <= 5:
        tier, level, max_level = "beginner", absolute_level, 5
    elif absolute_level <= 15:
        tier, level, max_level = "intermediate", absolute_level - 5, 10
    else:
        tier, level, max_level = "advanced", absolute_level - 15, 15
    return {"tier": tier, "level": level, "maxLevel": max_level, "xp": xp}


def connect_db() -> sqlite3.Connection:
    database = sqlite3.connect(DATABASE)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA journal_mode=WAL")
    return database


def initialize_db() -> None:
    with closing(connect_db()) as database, database:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                code TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rankings (
                uid TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                photo TEXT NOT NULL DEFAULT '',
                xp INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                losses INTEGER NOT NULL DEFAULT 0,
                games INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                room_code TEXT NOT NULL,
                opponent TEXT NOT NULL,
                mode TEXT NOT NULL,
                result TEXT NOT NULL,
                xp INTEGER NOT NULL,
                played_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS contexts (
                code TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bombs (
                code TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )


def read_room(database: sqlite3.Connection, code: str) -> dict | None:
    row = database.execute("SELECT payload FROM rooms WHERE code = ?", (code,)).fetchone()
    return json.loads(row["payload"]) if row else None


def write_room(database: sqlite3.Connection, room: dict) -> None:
    database.execute(
        """
        INSERT INTO rooms(code, payload, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
        """,
        (room["code"], json.dumps(room, ensure_ascii=False), now_ms()),
    )

def read_context(database: sqlite3.Connection, code: str) -> dict | None:
    row = database.execute("SELECT payload FROM contexts WHERE code = ?", (code,)).fetchone()
    return json.loads(row["payload"]) if row else None


def write_context(database: sqlite3.Connection, context: dict) -> None:
    database.execute(
        """
        INSERT INTO contexts(code, payload, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
        """,
        (context["code"], json.dumps(context, ensure_ascii=False), now_ms()),
    )


def read_bomb(database: sqlite3.Connection, code: str) -> dict | None:
    row = database.execute("SELECT payload FROM bombs WHERE code = ?", (code,)).fetchone()
    return json.loads(row["payload"]) if row else None


def write_bomb(database: sqlite3.Connection, bomb: dict) -> None:
    database.execute(
        """
        INSERT INTO bombs(code, payload, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(code) DO UPDATE SET payload = excluded.payload, updated_at = excluded.updated_at
        """,
        (bomb["code"], json.dumps(bomb, ensure_ascii=False), now_ms()),
    )


def context_candidates(difficulty: str, category: str) -> list[dict]:
    candidates = [
        item for item in VOCABULARY["translations"]
        if item.get("difficulty", "easy") == difficulty
        and (category == "all" or item.get("category", "everyday") == category)
    ]
    return candidates or VOCABULARY["translations"]


def context_similarity(guess: dict, secret: dict) -> int:
    if guess["en"] == secret["en"]:
        return 0
    lexical = SequenceMatcher(None, guess["en"], secret["en"]).ratio()
    same_concept = guess.get("concept") and guess.get("concept") == secret.get("concept")
    same_category = guess.get("category") == secret.get("category")
    concept_bonus = 58 if same_concept else 0
    category_bonus = 16 if same_category else 0
    difficulty_bonus = 5 if guess.get("difficulty") == secret.get("difficulty") else 0
    similarity = min(99, max(1, round(lexical * 20 + concept_bonus + category_bonus + difficulty_bonus)))
    return 100 - similarity


def public_context(context: dict) -> dict:
    public = {key: value for key, value in context.items() if key != "secret"}
    return public


def find_translation_suggestions(value: str) -> list[dict]:
    normalized = normalize(value)
    if not normalized:
        return []
    suggestions = []
    for item in VOCABULARY["translations"]:
        if any(normalize(translation) == normalized for translation in item["pt"]):
            suggestions.append({"en": item["en"], "pt": item["pt"][0]})
    for english in FREEDICT["portuguese"].get(normalized, []):
        if not any(item["en"] == english for item in suggestions):
            suggestions.append({"en": english, "pt": value})
    return suggestions[:5]


def apply_context_guess(context: dict, uid: str, value: str) -> dict:
    normalized = normalize(value)
    candidate = next((item for item in VOCABULARY["translations"] if normalize(item["en"]) == normalized), None)
    if not candidate and normalized in FREEDICT["english"]:
        freedict_word = FREEDICT["english"][normalized]
        candidate = {"en": freedict_word["word"], "pt": freedict_word["translations"], "category": "general", "difficulty": "unknown"}
    if not candidate:
        raise ValueError("Digite uma palavra em inglês cadastrada ou use uma sugestão em português")
    if any(item["word"] == candidate["en"] and item["round"] == context["round"] for item in context["guesses"]):
        raise ValueError("Esta palavra já foi enviada")
    proximity = context_similarity(candidate, context["secret"])
    context["learningNote"] = f"{candidate['pt'][0]} em inglês: {candidate['en']}"
    context["lastSolved"] = None
    points = max(1, 100 - proximity)
    solved = proximity == 0
    if solved:
        points += 100
    player = context["players"][uid]
    player["score"] = player.get("score", 0) + points
    context["guesses"].append({
        "word": candidate["en"], "translation": candidate["pt"][0], "proximity": proximity,
        "points": points, "uid": uid, "player": player["name"], "round": context["round"],
    })
    if proximity == 0:
        context["lastSolved"] = {"word": context["secret"]["en"], "translation": context["secret"]["pt"][0], "uid": uid, "player": player["name"]}
        context["status"] = "finished"
        context["winner"] = uid
    return context


def choose_prompt(mode: str, difficulty: str, category: str, used_prompts: list[str], round_number: int = 1) -> dict:
    candidates = [
        item for item in VOCABULARY[f"{mode}s"]
        if item.get("difficulty", "easy") == difficulty
        and (category == "all" or item.get("category", "everyday") == category)
    ]
    if not candidates:
        candidates = VOCABULARY[f"{mode}s"]
    available = [item for item in candidates if (item.get("en") or item.get("syllable")) not in used_prompts]
    if not available:
        return None
    item = random.choice(available)
    prompt_id = item.get("en") or item["syllable"]
    if mode == "syllable":
        return {
            "word": item["syllable"],
            "hint": "DIGITE UMA PALAVRA EM INGLÊS QUE COMECE COM",
            "answers": item["examples"],
            "id": prompt_id,
        }
    english_to_portuguese = round_number % 2 == 1
    if english_to_portuguese:
        return {"word": item["en"], "hint": "TRADUZA PARA PORTUGUÊS", "answers": item["pt"], "id": prompt_id}
    return {"word": item["pt"][0], "hint": "TRADUZA PARA INGLÊS", "answers": [item["en"]], "id": prompt_id}


def next_round(room: dict, database: sqlite3.Connection | None = None) -> dict:
    player_ids = list(room["players"])
    room["round"] = room.get("round", 0) + 1
    room["turn"] = player_ids[(room["round"] - 1) % len(player_ids)]
    room["prompt"] = choose_prompt(room["mode"], room["difficulty"], room.get("category", "all"), room.setdefault("usedPrompts", []), room["round"])
    if not room["prompt"]:
        scores = {uid: player.get("score", 0) for uid, player in room["players"].items()}
        best_score = max(scores.values())
        leaders = [uid for uid, score in scores.items() if score == best_score]
        winner = leaders[0] if len(leaders) == 1 else None
        if database:
            return finish_room(database, room, winner, "content_exhausted")
        room.update({"status": "finished", "winner": winner, "finishReason": "content_exhausted", "deadline": now_ms()})
        return room
    room["usedPrompts"].append(room["prompt"]["id"])
    room["deadline"] = now_ms() + ROUND_SECONDS * 1000
    return room


def public_room(room: dict) -> dict:
    public = json.loads(json.dumps(room))
    public["serverNow"] = now_ms()
    if "prompt" in public:
        public["prompt"].pop("answers", None)
    return public


def update_ranking(database: sqlite3.Connection, player: dict, won: bool) -> None:
    xp = player.get("score", 0) + (150 if won else 30)
    database.execute(
        """
        INSERT INTO rankings(uid, name, photo, xp, wins, losses, games, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(uid) DO UPDATE SET
            name = excluded.name,
            photo = excluded.photo,
            xp = rankings.xp + excluded.xp,
            wins = rankings.wins + excluded.wins,
            losses = rankings.losses + excluded.losses,
            games = rankings.games + 1,
            updated_at = excluded.updated_at
        """,
        (player["uid"], player["name"], player.get("photo", ""), xp, int(won), int(not won), now_ms()),
    )


def finish_room(database: sqlite3.Connection, room: dict, winner: str | None, reason: str) -> dict:
    if room["status"] == "finished":
        return room
    room.update({"status": "finished", "winner": winner, "finishReason": reason, "deadline": now_ms()})
    if room.get("demo"):
        return room
    players = list(room["players"].values())
    if len(players) == 2:
        for player in players:
            opponent = next(item for item in players if item["uid"] != player["uid"])
            won = player["uid"] == winner
            update_ranking(database, player, won)
            database.execute(
                "INSERT INTO history(uid, room_code, opponent, mode, result, xp, played_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (player["uid"], room["code"], opponent["name"], room["mode"], "win" if won else "loss", player.get("score", 0), now_ms()),
            )
    return room


def record_context_ranking(database: sqlite3.Connection, context: dict) -> dict:
    if context.get("rankingRecorded"):
        return context
    if len(context["players"]) < 2:
        context["rankingRecorded"] = True
        return context
    for player in context["players"].values():
        won = player["uid"] == context.get("winner")
        update_ranking(database, player, won)
        database.execute(
            "INSERT INTO history(uid, room_code, opponent, mode, result, xp, played_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (player["uid"], context["code"], "WORD_RADAR", "word_radar", "win" if won else "loss", player.get("score", 0), now_ms()),
        )
    context["rankingRecorded"] = True
    return context


def bomb_dictionary(language: str) -> set[str]:
    if language == "pt":
        return {
            normalize(word) for word in FREEDICT["portuguese"]
            if len(normalize(word)) >= 3 and normalize(word).isalpha()
        }
    return {
        normalize(word) for word in FREEDICT["english"]
        if len(normalize(word)) >= 3 and normalize(word).isalpha()
    }


def build_bomb_prompts(language: str) -> list[str]:
    frequency: dict[str, int] = {}
    for word in bomb_dictionary(language):
        for index in range(len(word) - 1):
            prompt = word[index:index + 2]
            frequency[prompt] = frequency.get(prompt, 0) + 1
    return [prompt for prompt, count in frequency.items() if count >= 12]


BOMB_WORDS = {language: bomb_dictionary(language) for language in ("en", "pt")}
BOMB_PROMPTS = {language: build_bomb_prompts(language) for language in ("en", "pt")}


def remote_bomb_words(language: str, prefix: str) -> set[str]:
    key = (language, prefix)
    if key in REMOTE_BOMB_CACHE:
        return REMOTE_BOMB_CACHE[key]
    words: set[str] = set()
    if REMOTE_BOMB_VOCABULARY:
        url = f"{FIREBASE_DATABASE_URL}/bombVocabulary/chunks/{language}/{prefix}.json"
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                payload = json.load(response) or {}
            words = set(payload if isinstance(payload, list) else payload)
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            pass
    REMOTE_BOMB_CACHE[key] = words
    return words


def bomb_word_exists(language: str, word: str) -> bool:
    return word in BOMB_WORDS[language] or word in remote_bomb_words(language, word[:2])


def public_bomb(bomb: dict) -> dict:
    public = json.loads(json.dumps(bomb))
    public["serverNow"] = now_ms()
    public.pop("usedWords", None)
    public.pop("usedPrompts", None)
    return public


def record_bomb_ranking(database: sqlite3.Connection, bomb: dict) -> dict:
    if bomb.get("rankingRecorded"):
        return bomb
    if len(bomb["players"]) < 2:
        bomb["rankingRecorded"] = True
        return bomb
    for player in bomb["players"].values():
        won = player["uid"] == bomb.get("winner")
        update_ranking(database, player, won)
        database.execute(
            "INSERT INTO history(uid, room_code, opponent, mode, result, xp, played_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (player["uid"], bomb["code"], "WORD_BOMB", "word_bomb", "win" if won else "loss", player.get("score", 0), now_ms()),
        )
    bomb["rankingRecorded"] = True
    return bomb


def finish_bomb(database: sqlite3.Connection, bomb: dict, winner: str | None, reason: str) -> dict:
    if bomb["status"] == "finished":
        return bomb
    bomb.update({"status": "finished", "winner": winner, "finishReason": reason, "deadline": now_ms()})
    return record_bomb_ranking(database, bomb)


def bomb_alive_players(bomb: dict) -> list[str]:
    return [
        uid for uid in bomb.get("order", [])
        if uid in bomb["players"] and bomb["players"][uid].get("hearts", 0) > 0
    ]


def next_bomb_turn(bomb: dict, database: sqlite3.Connection | None = None) -> dict:
    alive = bomb_alive_players(bomb)
    if len(alive) <= 1:
        if database:
            return finish_bomb(database, bomb, alive[0] if alive else None, "last_player")
        bomb.update({"status": "finished", "winner": alive[0] if alive else None, "finishReason": "last_player"})
        return bomb
    bomb["round"] = bomb.get("round", 0) + 1
    current = bomb.get("turn")
    current_index = alive.index(current) if current in alive else -1
    bomb["turn"] = alive[(current_index + 1) % len(alive)]
    prompts = BOMB_PROMPTS[bomb["language"]]
    available = [prompt for prompt in prompts if prompt not in bomb.setdefault("usedPrompts", [])]
    if not available:
        bomb["usedPrompts"] = []
        available = prompts
    bomb["prompt"] = random.choice(available)
    bomb["usedPrompts"].append(bomb["prompt"])
    bomb["deadline"] = now_ms() + ROUND_SECONDS * 1000
    return bomb


def apply_bomb_answer(database: sqlite3.Connection, bomb: dict, uid: str, answer: str) -> tuple[dict, bool]:
    if bomb["status"] != "playing" or bomb.get("turn") != uid:
        return bomb, False
    normalized = normalize(answer)
    valid = (
        len(normalized) >= 3
        and bomb["prompt"] in normalized
        and bomb_word_exists(bomb["language"], normalized)
        and normalized not in bomb.setdefault("usedWords", {})
    )
    if not valid:
        bomb["lastFeedback"] = {"id": now_ms(), "uid": uid, "kind": "invalid", "answer": normalized}
        return bomb, False
    bomb["usedWords"][normalized] = True
    bomb["players"][uid]["score"] = bomb["players"][uid].get("score", 0) + 100
    bomb["lastFeedback"] = {"id": now_ms(), "uid": uid, "kind": "correct", "answer": normalized, "xp": 100}
    return next_bomb_turn(bomb, database), True


def advance_bomb(database: sqlite3.Connection, bomb: dict) -> dict:
    if bomb["status"] != "playing" or bomb.get("deadline", 0) > now_ms():
        return bomb
    player = bomb["players"][bomb["turn"]]
    player["hearts"] = max(0, player.get("hearts", 0) - 1)
    bomb["lastFeedback"] = {"id": now_ms(), "uid": player["uid"], "kind": "timeout", "answer": bomb["prompt"]}
    return next_bomb_turn(bomb, database)


def apply_answer(database: sqlite3.Connection, room: dict, uid: str, answer: str, timed_out: bool = False) -> dict:
    if room["status"] != "playing" or room.get("turn") != uid:
        return room
    player = room["players"][uid]
    normalized = normalize(answer)
    if room["mode"] == "translation":
        correct = any(normalize(item) == normalized for item in room["prompt"]["answers"])
    else:
        valid_words = {normalize(item) for item in room["prompt"]["answers"]}
        correct = len(normalized) >= 3 and normalized in valid_words and normalized not in room.get("usedWords", {})
    if correct and not timed_out:
        player["score"] = player.get("score", 0) + 100
        room["lastFeedback"] = {"id": now_ms(), "uid": uid, "kind": "correct", "answer": normalized, "xp": 100}
        if room["mode"] == "syllable":
            room.setdefault("usedWords", {})[normalized] = True
    else:
        player["hearts"] -= 1
        room["lastFeedback"] = {
            "id": now_ms(), "uid": uid, "kind": "timeout" if timed_out else "wrong",
            "answer": room["prompt"]["answers"][0], "xp": 0,
        }
    if player["hearts"] <= 0:
        winner = next(player_uid for player_uid in room["players"] if player_uid != uid)
        return finish_room(database, room, winner, "hearts")
    return next_round(room, database)


def advance_room(database: sqlite3.Connection, room: dict) -> dict:
    if room["status"] == "playing" and room.get("deadline", 0) <= now_ms():
        room = apply_answer(database, room, room["turn"], "", timed_out=True)
    if room["status"] == "playing" and room.get("turn") == "bot":
        answer = room["prompt"]["answers"][0] if random.random() > 0.28 else "wrong"
        room = apply_answer(database, room, "bot", answer)
    return room


def random_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choice(alphabet) for _ in range(6))


class PoliHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/health":
            return self.send_json({"status": "ok", "game": "Poli English Duel", "database": "sqlite"})
        if path == "/api/vocabulary":
            return self.send_json({"translations": len(VOCABULARY["translations"]), "syllables": len(VOCABULARY["syllables"])})
        if path == "/api/ranking":
            return self.send_json({"ranking": self.get_ranking()})
        if path == "/api/profile":
            user = self.require_user()
            return self.send_json({"profile": self.get_profile(user)}) if user else None
        if path == "/api/rematches":
            user = self.require_user()
            return self.send_json({
                "rematches": self.get_pending_rematches(user["uid"]),
                "activeRooms": self.get_active_rooms(user["uid"]),
            }) if user else None
        if path == "/api/history":
            user = self.require_user()
            return self.send_json({"history": self.get_history(user["uid"])}) if user else None
        if path == "/api/contexts":
            user = self.require_user()
            return self.send_json({"contexts": self.get_open_contexts(user["uid"])}) if user else None
        if path == "/api/bombs":
            user = self.require_user()
            return self.send_json({"bombs": self.get_open_bombs(user["uid"])}) if user else None
        if path.startswith("/api/bombs/"):
            user = self.require_user()
            return self.get_bomb(path.split("/")[-1], user) if user else None
        if path.startswith("/api/contexts/"):
            user = self.require_user()
            return self.get_context(path.split("/")[-1], user) if user else None
        if path.startswith("/api/rooms/"):
            user = self.require_user()
            return self.get_room(path.split("/")[-1], user) if user else None
        if path.startswith("/api/"):
            return self.send_json({"error": "Endpoint not found"}, status=404)
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        user = self.require_user()
        if not user:
            return
        payload = self.read_json()
        if path == "/api/rooms":
            return self.create_room(user, payload)
        if path == "/api/contexts":
            return self.create_context(user, payload)
        if path == "/api/bombs":
            return self.create_bomb(user, payload)
        bomb_match = re.fullmatch(r"/api/bombs/([A-Z0-9]{6})/(join|ready|start|answer|leave)", path)
        if bomb_match:
            code, action = bomb_match.groups()
            return getattr(self, f"{action}_bomb")(code, user, payload)
        context_match = re.fullmatch(r"/api/contexts/([A-Z0-9]{6})/(join|suggest|guess)", path)
        if context_match:
            code, action = context_match.groups()
            return getattr(self, f"{action}_context")(code, user, payload)
        match = re.fullmatch(r"/api/rooms/([A-Z0-9]{6})/(join|answer|leave|rematch)", path)
        if not match:
            return self.send_json({"error": "Endpoint not found"}, status=404)
        code, action = match.groups()
        return getattr(self, f"{action}_room")(code, user, payload)

    def create_bomb(self, user: dict, payload: dict):
        language = payload.get("language", "en")
        if language not in {"en", "pt"}:
            return self.send_json({"error": "Idioma invalido"}, status=400)
        with LOCK, closing(connect_db()) as database, database:
            code = random_code()
            while read_bomb(database, code):
                code = random_code()
            player = self.player_from_user(user)
            player["ready"] = False
            bomb = {
                "code": code, "owner": user["uid"], "language": language, "status": "waiting",
                "createdAt": now_ms(), "round": 0, "players": {user["uid"]: player}, "order": [user["uid"]],
                "usedWords": {}, "usedPrompts": [],
            }
            write_bomb(database, bomb)
        return self.send_json({"bomb": public_bomb(bomb)}, status=201)

    def get_bomb(self, code: str, user: dict):
        with LOCK, closing(connect_db()) as database, database:
            bomb = read_bomb(database, code.upper())
            if not bomb or user["uid"] not in bomb.get("players", {}):
                return self.send_json({"error": "Sala Word Bomb nao encontrada"}, status=404)
            bomb = advance_bomb(database, bomb)
            write_bomb(database, bomb)
        return self.send_json({"bomb": public_bomb(bomb)})

    def join_bomb(self, code: str, user: dict, payload: dict):
        del payload
        with LOCK, closing(connect_db()) as database, database:
            bomb = read_bomb(database, code)
            if not bomb:
                return self.send_json({"error": "Sala Word Bomb nao encontrada"}, status=404)
            if bomb["status"] != "waiting" and user["uid"] not in bomb["players"]:
                return self.send_json({"error": "Esta partida ja comecou"}, status=409)
            if len(bomb["players"]) >= BOMB_MAX_PLAYERS and user["uid"] not in bomb["players"]:
                return self.send_json({"error": "Esta sala ja esta cheia"}, status=409)
            if user["uid"] not in bomb["players"]:
                player = self.player_from_user(user)
                player["ready"] = False
                bomb["players"][user["uid"]] = player
                bomb["order"].append(user["uid"])
            write_bomb(database, bomb)
        return self.send_json({"bomb": public_bomb(bomb)})

    def ready_bomb(self, code: str, user: dict, payload: dict):
        with LOCK, closing(connect_db()) as database, database:
            bomb = read_bomb(database, code)
            if not bomb or user["uid"] not in bomb.get("players", {}):
                return self.send_json({"error": "Sala Word Bomb nao encontrada"}, status=404)
            if bomb["status"] != "waiting":
                return self.send_json({"error": "A partida ja comecou"}, status=409)
            bomb["players"][user["uid"]]["ready"] = bool(payload.get("ready"))
            write_bomb(database, bomb)
        return self.send_json({"bomb": public_bomb(bomb)})

    def start_bomb(self, code: str, user: dict, payload: dict):
        del payload
        with LOCK, closing(connect_db()) as database, database:
            bomb = read_bomb(database, code)
            if not bomb or user["uid"] not in bomb.get("players", {}):
                return self.send_json({"error": "Sala Word Bomb nao encontrada"}, status=404)
            if bomb["owner"] != user["uid"]:
                return self.send_json({"error": "Somente o host pode iniciar a partida"}, status=403)
            if bomb["status"] != "waiting":
                return self.send_json({"error": "A partida ja comecou"}, status=409)
            if len(bomb["players"]) < 2 or not all(player.get("ready") for player in bomb["players"].values()):
                return self.send_json({"error": "Todos os jogadores precisam estar prontos"}, status=409)
            bomb["status"] = "playing"
            bomb = next_bomb_turn(bomb, database)
            write_bomb(database, bomb)
        return self.send_json({"bomb": public_bomb(bomb)})

    def answer_bomb(self, code: str, user: dict, payload: dict):
        with LOCK, closing(connect_db()) as database, database:
            bomb = read_bomb(database, code)
            if not bomb or user["uid"] not in bomb.get("players", {}):
                return self.send_json({"error": "Sala Word Bomb nao encontrada"}, status=404)
            bomb = advance_bomb(database, bomb)
            if payload.get("round") != bomb.get("round"):
                write_bomb(database, bomb)
                return self.send_json({"bomb": public_bomb(bomb)})
            bomb, accepted = apply_bomb_answer(database, bomb, user["uid"], str(payload.get("answer", "")))
            write_bomb(database, bomb)
        status = 200 if accepted else 400
        return self.send_json({"bomb": public_bomb(bomb), "error": None if accepted else "Palavra invalida. Tente novamente antes do tempo acabar."}, status=status)

    def leave_bomb(self, code: str, user: dict, payload: dict):
        del payload
        with LOCK, closing(connect_db()) as database, database:
            bomb = read_bomb(database, code)
            if not bomb or user["uid"] not in bomb.get("players", {}):
                return self.send_json({"ok": True})
            if bomb["status"] == "waiting":
                bomb["players"].pop(user["uid"], None)
                bomb["order"] = [uid for uid in bomb["order"] if uid != user["uid"]]
                if bomb["owner"] == user["uid"] and bomb["order"]:
                    bomb["owner"] = bomb["order"][0]
                if not bomb["players"]:
                    bomb["status"] = "finished"
                    bomb["finishReason"] = "cancelled"
            elif bomb["status"] == "playing":
                bomb["players"][user["uid"]]["hearts"] = 0
                alive = bomb_alive_players(bomb)
                if len(alive) <= 1:
                    bomb = finish_bomb(database, bomb, alive[0] if alive else None, "last_player")
                elif bomb.get("turn") == user["uid"]:
                    bomb = next_bomb_turn(bomb, database)
            write_bomb(database, bomb)
        return self.send_json({"ok": True})

    def get_open_bombs(self, uid: str):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT payload FROM bombs ORDER BY updated_at DESC").fetchall()
        bombs = []
        for row in rows:
            bomb = json.loads(row["payload"])
            if bomb.get("status") in {"waiting", "playing"} and uid in bomb.get("players", {}):
                bombs.append({
                    "code": bomb["code"], "language": bomb["language"], "status": bomb["status"],
                    "players": len(bomb["players"]), "createdAt": bomb["createdAt"],
                })
        return bombs[:10]

    def create_context(self, user: dict, payload: dict):
        difficulty = payload.get("difficulty", "easy")
        category = payload.get("category", "all")
        if difficulty not in {"easy", "medium", "hard"} or category not in {"all", "everyday", "travel", "work", "technology"}:
            return self.send_json({"error": "Nível ou categoria inválidos"}, status=400)
        with LOCK, closing(connect_db()) as database, database:
            code = random_code()
            context = {
                "code": code, "owner": user["uid"], "difficulty": difficulty, "category": category,
                "status": "playing", "createdAt": now_ms(), "guesses": [], "round": 1,
                "players": {user["uid"]: self.player_from_user(user)},
            }
            context["secret"] = random.choice(context_candidates(difficulty, category))
            write_context(database, context)
        return self.send_json({"context": public_context(context)}, status=201)

    def get_context(self, code: str, user: dict):
        with closing(connect_db()) as database, database:
            context = read_context(database, code)
        if not context or user["uid"] not in context.get("players", {}):
            return self.send_json({"error": "Desafio não encontrado"}, status=404)
        return self.send_json({"context": public_context(context)})

    def join_context(self, code: str, user: dict, payload: dict):
        del payload
        with LOCK, closing(connect_db()) as database, database:
            context = read_context(database, code)
            if not context:
                return self.send_json({"error": "Sala Word Radar não encontrada"}, status=404)
            context.setdefault("players", {})[user["uid"]] = self.player_from_user(user)
            write_context(database, context)
        return self.send_json({"context": public_context(context)})

    def suggest_context(self, code: str, user: dict, payload: dict):
        with closing(connect_db()) as database, database:
            context = read_context(database, code)
        if not context or user["uid"] not in context.get("players", {}):
            return self.send_json({"error": "Desafio não encontrado"}, status=404)
        value = str(payload.get("value", ""))
        known_english = any(normalize(item["en"]) == normalize(value) for item in VOCABULARY["translations"]) or normalize(value) in FREEDICT["english"]
        return self.send_json({"suggestions": find_translation_suggestions(value), "knownEnglish": known_english})

    def guess_context(self, code: str, user: dict, payload: dict):
        with LOCK, closing(connect_db()) as database, database:
            context = read_context(database, code)
            if not context or user["uid"] not in context.get("players", {}):
                return self.send_json({"error": "Desafio não encontrado"}, status=404)
            if context["status"] == "finished":
                return self.send_json({"context": public_context(context)})
            try:
                context = apply_context_guess(context, user["uid"], str(payload.get("value", "")))
            except ValueError as error:
                return self.send_json({"error": str(error)}, status=400)
            if context["status"] == "finished":
                context = record_context_ranking(database, context)
            write_context(database, context)
        return self.send_json({"context": public_context(context)})

    def get_open_contexts(self, uid: str):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT payload FROM contexts ORDER BY updated_at DESC").fetchall()
        contexts = []
        for row in rows:
            context = json.loads(row["payload"])
            if context.get("status") == "playing" and uid in context.get("players", {}):
                contexts.append({
                    "code": context["code"], "difficulty": context["difficulty"], "category": context["category"],
                    "players": len(context["players"]), "guesses": len(context["guesses"]), "createdAt": context["createdAt"],
                })
        return contexts[:10]

    def create_room(self, user: dict, payload: dict):
        mode = payload.get("mode", "translation")
        difficulty = payload.get("difficulty", "easy")
        category = payload.get("category", "all")
        if mode not in {"translation", "syllable"} or difficulty not in {"easy", "medium", "hard"} or category not in {"all", "everyday", "travel", "work", "technology"}:
            return self.send_json({"error": "Modo ou dificuldade inválidos"}, status=400)
        with LOCK, closing(connect_db()) as database, database:
            code = random_code()
            while read_room(database, code):
                code = random_code()
            room = {
                "code": code, "mode": mode, "difficulty": difficulty, "category": category, "status": "waiting",
                "owner": user["uid"], "createdAt": now_ms(), "round": 0,
                "players": {user["uid"]: self.player_from_user(user)},
                "demo": bool(payload.get("demo")),
            }
            if payload.get("demo"):
                room["players"]["bot"] = {"uid": "bot", "name": "BYTE_RIVAL", "photo": "", "hearts": 3, "score": 0}
                room["status"] = "playing"
                room = next_round(room, database)
            write_room(database, room)
        return self.send_json({"room": public_room(room)}, status=201)

    def get_room(self, code: str, user: dict):
        with LOCK, closing(connect_db()) as database, database:
            room = read_room(database, code.upper())
            if not room or user["uid"] not in room["players"]:
                return self.send_json({"error": "Sala não encontrada"}, status=404)
            room = advance_room(database, room)
            write_room(database, room)
        return self.send_json({"room": public_room(room)})

    def join_room(self, code: str, user: dict, payload: dict):
        del payload
        with LOCK, closing(connect_db()) as database, database:
            room = read_room(database, code)
            if not room:
                return self.send_json({"error": "Sala não encontrada"}, status=404)
            if len(room["players"]) >= 2 and user["uid"] not in room["players"]:
                return self.send_json({"error": "Esta sala já está cheia"}, status=409)
            room["players"][user["uid"]] = self.player_from_user(user)
            if len(room["players"]) == 2 and room["status"] == "waiting":
                room["status"] = "playing"
                room = next_round(room, database)
            write_room(database, room)
        return self.send_json({"room": public_room(room)})

    def answer_room(self, code: str, user: dict, payload: dict):
        with LOCK, closing(connect_db()) as database, database:
            room = read_room(database, code)
            if not room or user["uid"] not in room["players"]:
                return self.send_json({"error": "Sala não encontrada"}, status=404)
            if payload.get("round") != room.get("round"):
                return self.send_json({"room": public_room(room)})
            room = apply_answer(database, room, user["uid"], str(payload.get("answer", "")), bool(payload.get("timeout")))
            write_room(database, room)
        return self.send_json({"room": public_room(room)})

    def leave_room(self, code: str, user: dict, payload: dict):
        del payload
        with LOCK, closing(connect_db()) as database, database:
            room = read_room(database, code)
            if not room or user["uid"] not in room["players"]:
                return self.send_json({"ok": True})
            if room["status"] == "playing":
                winner = next((uid for uid in room["players"] if uid != user["uid"]), None)
                room = finish_room(database, room, winner, "abandoned")
            elif room["status"] == "waiting":
                room["status"] = "finished"
                room["finishReason"] = "cancelled"
            write_room(database, room)
        return self.send_json({"ok": True})

    def rematch_room(self, code: str, user: dict, payload: dict):
        decision = payload.get("decision", "request")
        if decision not in {"request", "accept", "decline"}:
            return self.send_json({"error": "Ação de revanche inválida"}, status=400)
        with LOCK, closing(connect_db()) as database, database:
            room = read_room(database, code)
            if not room or user["uid"] not in room["players"]:
                return self.send_json({"error": "Sala não encontrada"}, status=404)
            if room["status"] != "finished":
                return self.send_json({"error": "A revanche só pode ser solicitada após a partida"}, status=409)
            if decision == "decline":
                room["rematch"] = {}
                write_room(database, room)
                return self.send_json({"room": public_room(room)})
            room.setdefault("rematch", {})[user["uid"]] = True
            if room["status"] == "finished" and len(room["rematch"]) == len(room["players"]):
                room.update({"status": "playing", "round": 0, "usedWords": {}, "usedPrompts": [], "rematch": {}, "winner": None, "finishReason": None, "lastFeedback": None})
                for player in room["players"].values():
                    player.update({"hearts": 3, "score": 0})
                room = next_round(room, database)
            write_room(database, room)
        return self.send_json({"room": public_room(room)})

    def get_pending_rematches(self, uid: str):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT payload FROM rooms ORDER BY updated_at DESC").fetchall()
        rematches = []
        for row in rows:
            room = json.loads(row["payload"])
            requests = room.get("rematch", {})
            if room.get("status") != "finished" or uid not in room.get("players", {}) or requests.get(uid):
                continue
            requester_uid = next((player_uid for player_uid in requests if player_uid != uid), None)
            if requester_uid:
                rematches.append({
                    "code": room["code"], "mode": room["mode"], "requester": room["players"][requester_uid]["name"],
                })
        return rematches[:1]

    def get_active_rooms(self, uid: str):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT payload FROM rooms ORDER BY updated_at DESC").fetchall()
        rooms = []
        for row in rows:
            room = json.loads(row["payload"])
            if room.get("status") == "playing" and uid in room.get("players", {}):
                rooms.append(public_room(room))
        return rooms[:1]

    def get_ranking(self):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT name, photo, xp, wins, losses, games FROM rankings ORDER BY xp DESC, wins DESC LIMIT 10").fetchall()
        return [{**dict(row), "progression": progression_from_xp(row["xp"])} for row in rows]

    def get_profile(self, user: dict):
        with closing(connect_db()) as database, database:
            row = database.execute("SELECT name, photo, xp, wins, losses, games FROM rankings WHERE uid = ?", (user["uid"],)).fetchone()
        profile = dict(row) if row else {
            "name": user.get("name", "GUEST_PLAYER"), "photo": user.get("photo", ""),
            "xp": 0, "wins": 0, "losses": 0, "games": 0,
        }
        return {**profile, "progression": progression_from_xp(profile["xp"])}

    def get_history(self, uid: str):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT opponent, mode, result, xp, played_at FROM history WHERE uid = ? ORDER BY played_at DESC LIMIT 8", (uid,)).fetchall()
        return [dict(row) for row in rows]

    def player_from_user(self, user: dict) -> dict:
        profile = self.get_profile(user)
        return {
            "uid": user["uid"], "name": user.get("name", "GUEST_PLAYER"), "photo": user.get("photo", ""),
            "hearts": 3, "score": 0, "progression": profile["progression"],
        }

    def require_user(self) -> dict | None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            self.send_json({"error": "Faça login para continuar"}, status=401)
            return None
        token = authorization[7:]
        if token.startswith("demo-"):
            if ALLOW_DEMO:
                return {"uid": token, "name": "DEMO_PLAYER", "photo": ""}
            self.send_json({"error": "Modo demo desativado"}, status=401)
            return None
        cached = TOKEN_CACHE.get(token)
        if cached and cached[0] > time.time() and cached[1].get("authProvider") == "google":
            return cached[1]
        request = urllib.request.Request(
            f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={FIREBASE_API_KEY}",
            data=json.dumps({"idToken": token}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                firebase_user = json.load(response)["users"][0]
        except urllib.error.HTTPError:
            self.send_json({"error": "Sessão inválida"}, status=401)
            return None
        except urllib.error.URLError:
            self.send_json({"error": "Não foi possível validar a sessão com o Firebase"}, status=503)
            return None
        except (KeyError, IndexError):
            self.send_json({"error": "Resposta inválida recebida do Firebase"}, status=502)
            return None
        providers = {provider.get("providerId") for provider in firebase_user.get("providerUserInfo", [])}
        if "google.com" not in providers:
            self.send_json({"error": "Faça login com Google para jogar"}, status=401)
            return None
        user = {
            "uid": firebase_user["localId"], "name": firebase_user.get("displayName", "GUEST_PLAYER").upper().replace(" ", "_"),
            "photo": firebase_user.get("photoUrl", ""), "authProvider": "google",
        }
        TOKEN_CACHE[token] = (time.time() + 300, user)
        return user

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return {}

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path):
        return mimetypes.guess_type(path)[0] or "application/octet-stream"


def run():
    initialize_db()
    address = ("127.0.0.1", 8000)
    print("Poli English Duel rodando em http://localhost:8000")
    ThreadingHTTPServer(address, PoliHandler).serve_forever()


if __name__ == "__main__":
    run()
