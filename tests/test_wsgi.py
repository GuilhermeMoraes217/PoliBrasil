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


if __name__ == "__main__":
    unittest.main()
