import unittest
import io
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import server
from app import app


class WsgiAppTest(unittest.TestCase):
    def setUp(self):
        server.DATABASE = Path(server.ROOT) / "data" / f"test-{uuid4().hex}.db"
        server.initialize_db()
        app.config.update(TESTING=True)
        self.client = app.test_client()

    def tearDown(self):
        for suffix in ("", "-shm", "-wal"):
            database_file = Path(f"{server.DATABASE}{suffix}")
            if database_file.exists():
                database_file.unlink()

    def test_health_endpoint_uses_wsgi_transport(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["transport"], "wsgi")

    def test_frontend_is_served(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"POLI", response.data.upper())
        response.close()

    def test_authenticated_endpoint_requires_login(self):
        response = self.client.get("/api/history")
        self.assertEqual(response.status_code, 401)

    def test_demo_token_is_rejected_by_default(self):
        with patch.object(server, "ALLOW_DEMO", False):
            response = self.client.post(
                "/api/rooms",
                headers={"Authorization": "Bearer demo-wsgi"},
                json={"mode": "translation", "difficulty": "easy", "category": "all"},
            )
        self.assertEqual(response.status_code, 401)

    def test_demo_token_can_create_room_when_explicitly_enabled(self):
        with patch.object(server, "ALLOW_DEMO", True):
            response = self.client.post(
                "/api/rooms",
                headers={"Authorization": "Bearer demo-wsgi"},
                json={"mode": "translation", "difficulty": "easy", "category": "all"},
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["room"]["status"], "waiting")

    def test_anonymous_firebase_token_cannot_create_room(self):
        firebase_response = io.BytesIO(json.dumps({"users": [{"localId": "anonymous-player"}]}).encode())
        with patch("server.urllib.request.urlopen", return_value=firebase_response):
            response = self.client.post(
                "/api/rooms",
                headers={"Authorization": "Bearer anonymous-firebase-token"},
                json={"mode": "translation", "difficulty": "easy", "category": "all"},
            )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Google", response.json["error"])

    def test_profile_starts_at_beginner_level_one(self):
        with patch.object(server, "ALLOW_DEMO", True):
            response = self.client.get("/api/profile", headers={"Authorization": "Bearer demo-profile"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["profile"]["progression"]["tier"], "beginner")
        self.assertEqual(response.json["profile"]["progression"]["level"], 1)

    def test_rematch_invite_can_be_accepted_after_finished_match(self):
        room = {
            "code": "REMAT1", "mode": "translation", "difficulty": "easy", "category": "all",
            "status": "finished", "round": 4, "players": {
                "demo-one": {"uid": "demo-one", "name": "PLAYER_ONE", "photo": "", "hearts": 2, "score": 200},
                "demo-two": {"uid": "demo-two", "name": "PLAYER_TWO", "photo": "", "hearts": 0, "score": 100},
            },
        }
        with server.closing(server.connect_db()) as database, database:
            server.write_room(database, room)
        with patch.object(server, "ALLOW_DEMO", True):
            requested = self.client.post(
                "/api/rooms/REMAT1/rematch", headers={"Authorization": "Bearer demo-one"}, json={"decision": "request"}
            )
            updates = self.client.get("/api/rematches", headers={"Authorization": "Bearer demo-two"})
            accepted = self.client.post(
                "/api/rooms/REMAT1/rematch", headers={"Authorization": "Bearer demo-two"}, json={"decision": "accept"}
            )
            requester_updates = self.client.get("/api/rematches", headers={"Authorization": "Bearer demo-one"})
        self.assertEqual(requested.status_code, 200)
        self.assertEqual(updates.json["rematches"][0]["requester"], "PLAYER_ONE")
        self.assertEqual(accepted.json["room"]["status"], "playing")
        self.assertEqual(accepted.json["room"]["round"], 1)
        self.assertIn("serverNow", accepted.json["room"])
        self.assertEqual(requester_updates.json["activeRooms"][0]["code"], "REMAT1")

    def test_word_bomb_host_can_start_only_after_everyone_is_ready(self):
        with patch.object(server, "ALLOW_DEMO", True):
            created = self.client.post(
                "/api/bombs", headers={"Authorization": "Bearer demo-one"}, json={"language": "en"}
            )
            code = created.json["bomb"]["code"]
            joined = self.client.post(
                f"/api/bombs/{code}/join", headers={"Authorization": "Bearer demo-two"}, json={}
            )
            blocked = self.client.post(
                f"/api/bombs/{code}/start", headers={"Authorization": "Bearer demo-one"}, json={}
            )
            self.client.post(
                f"/api/bombs/{code}/ready", headers={"Authorization": "Bearer demo-one"}, json={"ready": True}
            )
            self.client.post(
                f"/api/bombs/{code}/ready", headers={"Authorization": "Bearer demo-two"}, json={"ready": True}
            )
            started = self.client.post(
                f"/api/bombs/{code}/start", headers={"Authorization": "Bearer demo-one"}, json={}
            )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["bomb"]["difficulty"], "easy")
        self.assertEqual(created.json["bomb"]["sublevel"], 1)
        self.assertEqual(joined.status_code, 200)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(started.status_code, 200)
        self.assertEqual(started.json["bomb"]["status"], "playing")
        self.assertIn(started.json["bomb"]["turn"], {"demo-one", "demo-two"})
        self.assertIn("serverNow", started.json["bomb"])

    def test_pop_cards_room_can_be_created(self):
        with patch.object(server, "ALLOW_DEMO", True):
            created = self.client.post(
                "/api/bombs", headers={"Authorization": "Bearer demo-one"}, json={"language": "pt", "mode": "pop_cards"}
            )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json["bomb"]["mode"], "pop_cards")
        self.assertIsNone(created.json["bomb"]["activeCard"])
        self.assertEqual(created.json["bomb"]["phase"], "waiting_card")

    def test_word_bomb_rematch_returns_everyone_to_lobby(self):
        bomb = {
            "code": "BOMB02", "owner": "demo-one", "language": "pt", "difficulty": "easy", "status": "finished",
            "round": 5, "winner": "demo-one", "finishReason": "last_player", "rankingRecorded": True,
            "players": {
                "demo-one": {"uid": "demo-one", "name": "PLAYER_ONE", "photo": "", "hearts": 2, "score": 300, "ready": True},
                "demo-two": {"uid": "demo-two", "name": "PLAYER_TWO", "photo": "", "hearts": 0, "score": 100, "ready": True},
            },
            "order": ["demo-one", "demo-two"], "usedWords": {"maca": True}, "usedPrompts": ["ac"],
        }
        with server.closing(server.connect_db()) as database, database:
            server.write_bomb(database, bomb)
        with patch.object(server, "ALLOW_DEMO", True):
            response = self.client.post(
                "/api/bombs/BOMB02/rematch", headers={"Authorization": "Bearer demo-two"}, json={}
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["bomb"]["status"], "waiting")
        self.assertEqual(response.json["bomb"]["round"], 0)
        self.assertEqual(response.json["bomb"]["difficulty"], "easy")
        self.assertEqual(response.json["bomb"]["sublevel"], 1)
        self.assertTrue(all(player["hearts"] == 3 for player in response.json["bomb"]["players"].values()))
        self.assertTrue(all(not player["ready"] for player in response.json["bomb"]["players"].values()))


if __name__ == "__main__":
    unittest.main()
