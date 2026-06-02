from __future__ import annotations

import re

from flask import Flask, jsonify, request, send_from_directory

from server import PUBLIC, PoliHandler, VOCABULARY, initialize_db


app = Flask(__name__, static_folder=str(PUBLIC), static_url_path="")
initialize_db()


class FlaskPoliHandler(PoliHandler):
    """Reuse the game API while Flask provides the WSGI transport."""

    def __init__(self):
        self.headers = request.headers
        self.response = None

    def send_json(self, payload, status=200):
        self.response = jsonify(payload), status
        return self.response


@app.after_request
def disable_cache(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(PUBLIC, "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "game": "Poli English Duel", "database": "sqlite", "transport": "wsgi"})


@app.get("/api/vocabulary")
def vocabulary():
    return jsonify({"translations": len(VOCABULARY["translations"]), "syllables": len(VOCABULARY["syllables"])})


@app.get("/api/ranking")
def ranking():
    handler = FlaskPoliHandler()
    return jsonify({"ranking": handler.get_ranking()})


@app.get("/api/profile")
def profile():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return jsonify({"profile": handler.get_profile(user)}) if user else handler.response


@app.get("/api/rematches")
def rematches():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return jsonify({
        "rematches": handler.get_pending_rematches(user["uid"]),
        "activeRooms": handler.get_active_rooms(user["uid"]),
    }) if user else handler.response


@app.get("/api/history")
def history():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return jsonify({"history": handler.get_history(user["uid"])}) if user else handler.response


@app.get("/api/contexts")
def contexts():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return jsonify({"contexts": handler.get_open_contexts(user["uid"])}) if user else handler.response


@app.get("/api/bombs")
def bombs():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return jsonify({"bombs": handler.get_open_bombs(user["uid"])}) if user else handler.response


@app.get("/api/bombs/<code>")
def get_bomb(code):
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return handler.get_bomb(code.upper(), user) if user else handler.response


@app.get("/api/contexts/<code>")
def get_context(code):
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return handler.get_context(code.upper(), user) if user else handler.response


@app.get("/api/rooms/<code>")
def get_room(code):
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return handler.get_room(code.upper(), user) if user else handler.response


@app.post("/api/rooms")
def create_room():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return handler.create_room(user, request.get_json(silent=True) or {}) if user else handler.response


@app.post("/api/contexts")
def create_context():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return handler.create_context(user, request.get_json(silent=True) or {}) if user else handler.response


@app.post("/api/bombs")
def create_bomb():
    handler = FlaskPoliHandler()
    user = handler.require_user()
    return handler.create_bomb(user, request.get_json(silent=True) or {}) if user else handler.response


@app.post("/api/bombs/<code>/<action>")
def bomb_action(code, action):
    if not re.fullmatch(r"(join|ready|start|answer|leave)", action):
        return jsonify({"error": "Endpoint not found"}), 404
    handler = FlaskPoliHandler()
    user = handler.require_user()
    if not user:
        return handler.response
    return getattr(handler, f"{action}_bomb")(code.upper(), user, request.get_json(silent=True) or {})


@app.post("/api/contexts/<code>/<action>")
def context_action(code, action):
    if not re.fullmatch(r"(join|suggest|guess)", action):
        return jsonify({"error": "Endpoint not found"}), 404
    handler = FlaskPoliHandler()
    user = handler.require_user()
    if not user:
        return handler.response
    return getattr(handler, f"{action}_context")(code.upper(), user, request.get_json(silent=True) or {})


@app.post("/api/rooms/<code>/<action>")
def room_action(code, action):
    if not re.fullmatch(r"(join|answer|leave|rematch)", action):
        return jsonify({"error": "Endpoint not found"}), 404
    handler = FlaskPoliHandler()
    user = handler.require_user()
    if not user:
        return handler.response
    return getattr(handler, f"{action}_room")(code.upper(), user, request.get_json(silent=True) or {})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
