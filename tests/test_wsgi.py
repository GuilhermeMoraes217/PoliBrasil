import unittest
from pathlib import Path
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

    def test_demo_token_can_create_room(self):
        response = self.client.post(
            "/api/rooms",
            headers={"Authorization": "Bearer demo-wsgi"},
            json={"mode": "translation", "difficulty": "easy", "category": "all"},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["room"]["status"], "waiting")


if __name__ == "__main__":
    unittest.main()
