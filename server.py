from __future__ import annotations

import json
import mimetypes
import random
import re
import sqlite3
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from contextlib import closing
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC = ROOT / "public"
DATA = ROOT / "data" / "vocabulary.json"
DATABASE = ROOT / "data" / "poli.db"
FIREBASE_API_KEY = "AIzaSyBcsiGC1h_tBTJrlb2CE5DWxHVtFUimWPE"
ROUND_SECONDS = 10
LOCK = threading.RLock()
TOKEN_CACHE: dict[str, tuple[float, dict]] = {}

with DATA.open(encoding="utf-8") as vocabulary_file:
    VOCABULARY = json.load(vocabulary_file)


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower())
    return re.sub(r"[^a-z]", "", "".join(char for char in text if unicodedata.category(char) != "Mn"))


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


def choose_prompt(mode: str, difficulty: str, round_number: int) -> dict:
    candidates = [item for item in VOCABULARY[f"{mode}s"] if item.get("difficulty", "easy") == difficulty]
    if not candidates:
        candidates = VOCABULARY[f"{mode}s"]
    item = candidates[(round_number * 7) % len(candidates)]
    if mode == "syllable":
        return {
            "word": item["syllable"],
            "hint": "DIGITE UMA PALAVRA EM INGLÊS QUE COMECE COM",
            "answers": item["examples"],
        }
    english_to_portuguese = round_number % 2 == 1
    if english_to_portuguese:
        return {"word": item["en"], "hint": "TRADUZA PARA PORTUGUÊS", "answers": item["pt"]}
    return {"word": item["pt"][0], "hint": "TRADUZA PARA INGLÊS", "answers": [item["en"]]}


def next_round(room: dict) -> dict:
    player_ids = list(room["players"])
    room["round"] = room.get("round", 0) + 1
    room["turn"] = player_ids[(room["round"] - 1) % len(player_ids)]
    room["prompt"] = choose_prompt(room["mode"], room["difficulty"], room["round"])
    room["deadline"] = now_ms() + ROUND_SECONDS * 1000
    return room


def public_room(room: dict) -> dict:
    public = json.loads(json.dumps(room))
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
        if room["mode"] == "syllable":
            room.setdefault("usedWords", {})[normalized] = True
    else:
        player["hearts"] -= 1
    if player["hearts"] <= 0:
        winner = next(player_uid for player_uid in room["players"] if player_uid != uid)
        return finish_room(database, room, winner, "hearts")
    return next_round(room)


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
        if path == "/api/history":
            user = self.require_user()
            return self.send_json({"history": self.get_history(user["uid"])}) if user else None
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
        match = re.fullmatch(r"/api/rooms/([A-Z0-9]{6})/(join|answer|leave|rematch)", path)
        if not match:
            return self.send_json({"error": "Endpoint not found"}, status=404)
        code, action = match.groups()
        return getattr(self, f"{action}_room")(code, user, payload)

    def create_room(self, user: dict, payload: dict):
        mode = payload.get("mode", "translation")
        difficulty = payload.get("difficulty", "easy")
        if mode not in {"translation", "syllable"} or difficulty not in {"easy", "medium", "hard"}:
            return self.send_json({"error": "Modo ou dificuldade inválidos"}, status=400)
        with LOCK, closing(connect_db()) as database, database:
            code = random_code()
            while read_room(database, code):
                code = random_code()
            room = {
                "code": code, "mode": mode, "difficulty": difficulty, "status": "waiting",
                "owner": user["uid"], "createdAt": now_ms(), "round": 0,
                "players": {user["uid"]: self.player_from_user(user)},
                "demo": bool(payload.get("demo")),
            }
            if payload.get("demo"):
                room["players"]["bot"] = {"uid": "bot", "name": "BYTE_RIVAL", "photo": "", "hearts": 3, "score": 0}
                room["status"] = "playing"
                room = next_round(room)
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
                room = next_round(room)
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
        del payload
        with LOCK, closing(connect_db()) as database, database:
            room = read_room(database, code)
            if not room or user["uid"] not in room["players"]:
                return self.send_json({"error": "Sala não encontrada"}, status=404)
            room.setdefault("rematch", {})[user["uid"]] = True
            if room["status"] == "finished" and len(room["rematch"]) == len(room["players"]):
                room.update({"status": "playing", "round": 0, "usedWords": {}, "rematch": {}, "winner": None, "finishReason": None})
                for player in room["players"].values():
                    player.update({"hearts": 3, "score": 0})
                room = next_round(room)
            write_room(database, room)
        return self.send_json({"room": public_room(room)})

    def get_ranking(self):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT name, photo, xp, wins, losses, games FROM rankings ORDER BY xp DESC, wins DESC LIMIT 10").fetchall()
        return [dict(row) for row in rows]

    def get_history(self, uid: str):
        with closing(connect_db()) as database, database:
            rows = database.execute("SELECT opponent, mode, result, xp, played_at FROM history WHERE uid = ? ORDER BY played_at DESC LIMIT 8", (uid,)).fetchall()
        return [dict(row) for row in rows]

    def player_from_user(self, user: dict) -> dict:
        return {"uid": user["uid"], "name": user.get("name", "GUEST_PLAYER"), "photo": user.get("photo", ""), "hearts": 3, "score": 0}

    def require_user(self) -> dict | None:
        authorization = self.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            self.send_json({"error": "Faça login para continuar"}, status=401)
            return None
        token = authorization[7:]
        if token.startswith("demo-"):
            return {"uid": token, "name": "DEMO_PLAYER", "photo": ""}
        cached = TOKEN_CACHE.get(token)
        if cached and cached[0] > time.time():
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
        user = {"uid": firebase_user["localId"], "name": firebase_user.get("displayName", "GUEST_PLAYER").upper().replace(" ", "_"), "photo": firebase_user.get("photoUrl", "")}
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
