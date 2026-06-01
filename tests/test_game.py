import unittest
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import server


class GameEngineTest(unittest.TestCase):
    def setUp(self):
        server.DATABASE = Path(server.ROOT) / "data" / f"test-{uuid4().hex}.db"
        server.initialize_db()
        self.player_one = {"uid": "one", "name": "PLAYER_ONE", "photo": "", "hearts": 3, "score": 0}
        self.player_two = {"uid": "two", "name": "PLAYER_TWO", "photo": "", "hearts": 3, "score": 0}

    def tearDown(self):
        for suffix in ("", "-shm", "-wal"):
            database_file = Path(f"{server.DATABASE}{suffix}")
            if database_file.exists():
                database_file.unlink()

    def room(self, mode="translation", difficulty="easy"):
        room = {
            "code": "ABC123",
            "mode": mode,
            "difficulty": difficulty,
            "status": "playing",
            "round": 0,
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()},
        }
        return server.next_round(room)

    def test_public_room_hides_answers(self):
        room = self.room()
        self.assertNotIn("answers", server.public_room(room)["prompt"])
        self.assertIn("answers", room["prompt"])

    def test_wrong_answer_reveals_correct_answer_after_attempt(self):
        room = self.room()
        expected = room["prompt"]["answers"][0]
        with closing(server.connect_db()) as database, database:
            room = server.apply_answer(database, room, "one", "definitely-wrong")
        self.assertEqual(server.public_room(room)["lastFeedback"]["answer"], expected)

    def test_correct_translation_adds_xp(self):
        room = self.room()
        answer = room["prompt"]["answers"][0]
        with closing(server.connect_db()) as database, database:
            room = server.apply_answer(database, room, "one", answer)
        self.assertEqual(room["players"]["one"]["score"], 100)
        self.assertEqual(room["players"]["one"]["hearts"], 3)

    def test_syllable_mode_rejects_uncatalogued_word(self):
        room = self.room(mode="syllable")
        invented_word = f"{room['prompt']['word']}zzzz"
        with closing(server.connect_db()) as database, database:
            room = server.apply_answer(database, room, "one", invented_word)
        self.assertEqual(room["players"]["one"]["hearts"], 2)

    def test_abandonment_records_ranking_and_history(self):
        room = self.room()
        with closing(server.connect_db()) as database, database:
            room = server.finish_room(database, room, "two", "abandoned")
            server.write_room(database, room)
            ranking = database.execute("SELECT wins FROM rankings WHERE uid = 'two'").fetchone()
            history = database.execute("SELECT result FROM history WHERE uid = 'one'").fetchone()
        self.assertEqual(room["status"], "finished")
        self.assertEqual(ranking["wins"], 1)
        self.assertEqual(history["result"], "loss")

    def test_demo_match_does_not_affect_ranking(self):
        room = self.room()
        room["demo"] = True
        with closing(server.connect_db()) as database, database:
            server.finish_room(database, room, "two", "hearts")
            ranking_count = database.execute("SELECT COUNT(*) FROM rankings").fetchone()[0]
            history_count = database.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        self.assertEqual(ranking_count, 0)
        self.assertEqual(history_count, 0)

    def test_next_round_restores_match_state_for_rematch(self):
        room = self.room()
        room["players"]["one"]["hearts"] = 0
        room.update({"status": "playing", "round": 0})
        for player in room["players"].values():
            player.update({"hearts": 3, "score": 0})
        room = server.next_round(room)
        self.assertEqual(room["round"], 1)
        self.assertEqual(room["players"]["one"]["hearts"], 3)

    def test_prompts_do_not_repeat_while_category_has_unused_words(self):
        room = self.room()
        first_prompt = room["prompt"]["id"]
        room = server.next_round(room)
        self.assertNotEqual(room["prompt"]["id"], first_prompt)

    def test_category_filters_prompts(self):
        prompt = server.choose_prompt("translation", "easy", "technology", [])
        technology_words = {item["en"] for item in server.VOCABULARY["translations"] if item["category"] == "technology" and item["difficulty"] == "easy"}
        self.assertIn(prompt["id"], technology_words)

    def test_translation_prompt_never_repeats_when_content_is_exhausted(self):
        candidates = [
            item["en"] for item in server.VOCABULARY["translations"]
            if item["category"] == "technology" and item["difficulty"] == "easy"
        ]
        prompt = server.choose_prompt("translation", "easy", "technology", candidates)
        self.assertIsNone(prompt)

    def test_syllable_prompt_never_repeats_when_content_is_exhausted(self):
        candidates = [
            item["syllable"] for item in server.VOCABULARY["syllables"]
            if item["difficulty"] == "hard"
        ]
        prompt = server.choose_prompt("syllable", "hard", "all", candidates)
        self.assertIsNone(prompt)

    def test_context_secret_stays_hidden_until_solved(self):
        secret = next(item for item in server.VOCABULARY["translations"] if item["en"] == "apple")
        context = {"status": "playing", "secret": secret, "guesses": [], "code": "RADAR1"}
        self.assertNotIn("secret", server.public_context(context))
        context = server.apply_context_guess(context, "apple")
        self.assertEqual(server.public_context(context)["secret"]["en"], "apple")

    def test_context_suggests_english_word_from_portuguese(self):
        suggestions = server.find_translation_suggestions("maçã")
        self.assertTrue(any(item["en"] == "apple" for item in suggestions))

    def test_context_suggests_ascii_portuguese_word(self):
        suggestions = server.find_translation_suggestions("camisa")
        self.assertTrue(any(item["en"] == "shirt" for item in suggestions))

    def test_context_rejects_repeated_guess(self):
        secret = next(item for item in server.VOCABULARY["translations"] if item["en"] == "apple")
        context = {"status": "playing", "secret": secret, "guesses": []}
        context = server.apply_context_guess(context, "book")
        with self.assertRaises(ValueError):
            server.apply_context_guess(context, "book")


if __name__ == "__main__":
    unittest.main()
