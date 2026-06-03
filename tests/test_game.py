import unittest
import io
import json
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import server
from scripts import build_firebase_bomb_vocabulary


class GameEngineTest(unittest.TestCase):
    def setUp(self):
        server.DATABASE = Path(server.ROOT) / "data" / f"test-{uuid4().hex}.db"
        server.initialize_db()
        self.player_one = {"uid": "one", "name": "PLAYER_ONE", "photo": "", "hearts": 3, "score": 0}
        self.player_two = {"uid": "two", "name": "PLAYER_TWO", "photo": "", "hearts": 3, "score": 0}
        self.remote_bomb_vocabulary = server.REMOTE_BOMB_VOCABULARY
        server.REMOTE_BOMB_VOCABULARY = False
        server.REMOTE_BOMB_CACHE.clear()

    def tearDown(self):
        server.REMOTE_BOMB_VOCABULARY = self.remote_bomb_vocabulary
        server.REMOTE_BOMB_CACHE.clear()
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

    def test_public_room_includes_server_clock_for_timer_sync(self):
        room = self.room()
        public = server.public_room(room)
        self.assertIn("serverNow", public)
        self.assertLess(abs(server.now_ms() - public["serverNow"]), 1000)

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
        context = {"status": "playing", "secret": secret, "guesses": [], "code": "RADAR1", "players": {"one": self.player_one.copy()}, "round": 1, "difficulty": "easy", "category": "everyday"}
        self.assertNotIn("secret", server.public_context(context))
        context = server.apply_context_guess(context, "one", "apple")
        self.assertEqual(context["guesses"][0]["proximity"], 0)
        self.assertEqual(context["lastSolved"]["word"], "apple")
        self.assertNotIn("secret", server.public_context(context))

    def test_context_suggests_english_word_from_portuguese(self):
        suggestions = server.find_translation_suggestions("maçã")
        self.assertTrue(any(item["en"] == "apple" for item in suggestions))

    def test_context_suggests_ascii_portuguese_word(self):
        suggestions = server.find_translation_suggestions("camisa")
        self.assertTrue(any(item["en"] == "shirt" for item in suggestions))

    def test_context_rejects_repeated_guess(self):
        secret = next(item for item in server.VOCABULARY["translations"] if item["en"] == "apple")
        context = {"status": "playing", "secret": secret, "guesses": [], "players": {"one": self.player_one.copy()}, "round": 1}
        context = server.apply_context_guess(context, "one", "book")
        with self.assertRaises(ValueError):
            server.apply_context_guess(context, "one", "book")

    def test_context_uses_freedict_portuguese_fallback(self):
        suggestions = server.find_translation_suggestions("abelha")
        self.assertTrue(any(item["en"] == "bee" for item in suggestions))

    def test_context_accepts_freedict_english_guess_and_teaches_translation(self):
        secret = next(item for item in server.VOCABULARY["translations"] if item["en"] == "apple")
        context = {"status": "playing", "secret": secret, "guesses": [], "players": {"one": self.player_one.copy()}, "round": 1}
        context = server.apply_context_guess(context, "one", "bee")
        self.assertIn("em inglês: bee", context["learningNote"])

    def test_context_semantic_concept_ranks_related_word_closer(self):
        secret = next(item for item in server.VOCABULARY["translations"] if item["en"] == "shirt")
        dress = next(item for item in server.VOCABULARY["translations"] if item["en"] == "dress")
        apple = next(item for item in server.VOCABULARY["translations"] if item["en"] == "apple")
        self.assertLess(server.context_similarity(dress, secret), server.context_similarity(apple, secret))

    def test_context_scores_players_and_finishes_after_solution(self):
        secret = next(item for item in server.VOCABULARY["translations"] if item["en"] == "apple")
        context = {
            "status": "playing", "secret": secret, "guesses": [], "players": {"one": self.player_one.copy()},
            "round": 1, "difficulty": "easy", "category": "everyday",
        }
        context = server.apply_context_guess(context, "one", "apple")
        self.assertEqual(context["players"]["one"]["score"], 200)
        self.assertEqual(context["round"], 1)
        self.assertEqual(context["status"], "finished")
        self.assertEqual(context["winner"], "one")

    def test_progression_uses_three_tiers_and_caps_advanced_level(self):
        self.assertEqual(server.progression_from_xp(0)["tier"], "beginner")
        self.assertEqual(server.progression_from_xp(0)["level"], 1)
        self.assertEqual(server.progression_from_xp(2499)["level"], 5)
        self.assertEqual(server.progression_from_xp(2500)["tier"], "intermediate")
        self.assertEqual(server.progression_from_xp(2500)["level"], 1)
        self.assertEqual(server.progression_from_xp(7499)["level"], 10)
        self.assertEqual(server.progression_from_xp(7500)["tier"], "advanced")
        self.assertEqual(server.progression_from_xp(7500)["level"], 1)
        self.assertEqual(server.progression_from_xp(999999)["level"], 15)

    def test_context_ranking_is_recorded_only_once(self):
        context = {
            "code": "RADAR1", "status": "finished", "winner": "one",
            "players": {"one": {**self.player_one.copy(), "score": 200}, "two": self.player_two.copy()},
        }
        with closing(server.connect_db()) as database, database:
            server.record_context_ranking(database, context)
            server.record_context_ranking(database, context)
            ranking = database.execute("SELECT xp, wins, games FROM rankings WHERE uid = 'one'").fetchone()
            history_count = database.execute("SELECT COUNT(*) FROM history WHERE uid = 'one'").fetchone()[0]
        self.assertEqual(dict(ranking), {"xp": 350, "wins": 1, "games": 1})
        self.assertEqual(history_count, 1)

    def test_context_solo_match_does_not_affect_ranking(self):
        context = {
            "code": "RADAR1", "status": "finished", "winner": "one",
            "players": {"one": {**self.player_one.copy(), "score": 200}},
        }
        with closing(server.connect_db()) as database, database:
            server.record_context_ranking(database, context)
            ranking_count = database.execute("SELECT COUNT(*) FROM rankings").fetchone()[0]
        self.assertEqual(ranking_count, 0)

    def test_word_bomb_accepts_dictionary_word_with_prompt_and_moves_turn(self):
        bomb = {
            "code": "BOMB01", "status": "playing", "language": "en", "round": 1, "turn": "one", "prompt": "bo",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()}, "order": ["one", "two"],
            "usedWords": {}, "usedPrompts": ["bo"],
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "one", "book")
        self.assertTrue(accepted)
        self.assertEqual(bomb["players"]["one"]["score"], 100)
        self.assertEqual(bomb["turn"], "two")

    def test_word_bomb_accepts_prompt_in_the_middle_of_word(self):
        bomb = {
            "code": "BOMB01", "status": "playing", "language": "en", "round": 1, "turn": "one", "prompt": "oo",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()}, "order": ["one", "two"],
            "usedWords": {}, "usedPrompts": ["oo"],
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "one", "book")
        self.assertTrue(accepted)
        self.assertEqual(bomb["turn"], "two")

    def test_word_chain_first_answer_sets_next_required_syllable(self):
        bomb = {
            "code": "CHAIN1", "mode": "word_chain", "status": "playing", "language": "en",
            "round": 1, "turn": "one", "requiredSyllable": None, "lastWord": None,
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()},
            "order": ["one", "two"], "usedWords": {},
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "one", "banana")
        self.assertTrue(accepted)
        self.assertEqual(bomb["requiredSyllable"], "na")
        self.assertEqual(bomb["lastWord"], "banana")
        self.assertEqual(bomb["players"]["one"]["score"], 100)
        self.assertEqual(bomb["turn"], "two")

    def test_word_chain_rejects_missing_required_syllable_without_losing_turn(self):
        bomb = {
            "code": "CHAIN1", "mode": "word_chain", "status": "playing", "language": "en",
            "round": 2, "turn": "two", "requiredSyllable": "na", "lastWord": "banana",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()},
            "order": ["one", "two"], "usedWords": {"banana": True},
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "two", "table")
        self.assertFalse(accepted)
        self.assertEqual(bomb["turn"], "two")
        self.assertEqual(bomb["players"]["two"]["hearts"], 3)
        self.assertEqual(bomb["lastFeedback"]["kind"], "missing_syllable")

    def test_word_chain_rejects_repeated_word(self):
        bomb = {
            "code": "CHAIN1", "mode": "word_chain", "status": "playing", "language": "en",
            "round": 2, "turn": "two", "requiredSyllable": "na", "lastWord": "banana",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()},
            "order": ["one", "two"], "usedWords": {"banana": True},
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "two", "banana")
        self.assertFalse(accepted)
        self.assertEqual(bomb["lastFeedback"]["kind"], "duplicate")

    def test_word_bomb_invalid_word_keeps_turn_until_timeout(self):
        bomb = {
            "code": "BOMB01", "status": "playing", "language": "en", "round": 1, "turn": "one", "prompt": "oo",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()}, "order": ["one", "two"],
            "usedWords": {}, "usedPrompts": ["oo"],
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "one", "inventedword")
        self.assertFalse(accepted)
        self.assertEqual(bomb["turn"], "one")
        self.assertEqual(bomb["players"]["one"]["hearts"], 3)

    def test_word_bomb_duplicate_word_has_specific_feedback(self):
        bomb = {
            "code": "BOMB01", "status": "playing", "language": "en", "round": 1, "turn": "one", "prompt": "oo",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()}, "order": ["one", "two"],
            "usedWords": {"book": True}, "usedPrompts": ["oo"],
        }
        with closing(server.connect_db()) as database, database:
            bomb, accepted = server.apply_bomb_answer(database, bomb, "one", "book")
        self.assertFalse(accepted)
        self.assertEqual(bomb["turn"], "one")
        self.assertEqual(bomb["lastFeedback"]["kind"], "duplicate")

    def test_word_bomb_timeout_removes_heart_and_moves_turn(self):
        bomb = {
            "code": "BOMB01", "status": "playing", "language": "en", "round": 1, "turn": "one", "prompt": "oo",
            "players": {"one": self.player_one.copy(), "two": self.player_two.copy()}, "order": ["one", "two"],
            "usedWords": {}, "usedPrompts": ["oo"], "deadline": 0,
        }
        with closing(server.connect_db()) as database, database:
            bomb = server.advance_bomb(database, bomb)
        self.assertEqual(bomb["players"]["one"]["hearts"], 2)
        self.assertEqual(bomb["turn"], "two")

    def test_word_bomb_public_state_hides_used_words(self):
        bomb = {"code": "BOMB01", "players": {}, "usedWords": {"book": True}, "usedPrompts": ["oo"]}
        public = server.public_bomb(bomb)
        self.assertNotIn("usedWords", public)
        self.assertNotIn("usedPrompts", public)
        self.assertIn("serverNow", public)

    def test_word_bomb_portuguese_dictionary_normalizes_accents(self):
        self.assertIn("maca", server.BOMB_WORDS["pt"])

    def test_word_bomb_accepts_portuguese_answer_with_or_without_accent(self):
        for answer in ("maca", "maçã"):
            bomb = {
                "code": "BOMB01", "status": "playing", "language": "pt", "round": 1, "turn": "one", "prompt": "ac",
                "players": {"one": self.player_one.copy(), "two": self.player_two.copy()}, "order": ["one", "two"],
                "usedWords": {}, "usedPrompts": ["ac"],
            }
            with closing(server.connect_db()) as database, database:
                _, accepted = server.apply_bomb_answer(database, bomb, "one", answer)
            self.assertTrue(accepted)

    def test_word_bomb_prompt_levels_keep_easy_pairs_friendly(self):
        easy = server.BOMB_PROMPTS["pt"]["easy"]
        hard = server.BOMB_PROMPTS["pt"]["hard"]
        self.assertTrue({"ba", "ca", "ta"}.issubset(easy))
        self.assertIn("st", hard)
        for difficulty in server.BOMB_DIFFICULTIES:
            self.assertNotIn("mm", server.BOMB_PROMPTS["pt"][difficulty])
            self.assertNotIn("cc", server.BOMB_PROMPTS["pt"][difficulty])

    def test_word_bomb_progression_advances_sublevels_and_difficulties(self):
        bomb = {"round": 0, "progression": {"stage": 0, "nextLevelAt": 1}}
        server.update_bomb_progression(bomb)
        self.assertEqual((bomb["difficulty"], bomb["sublevel"]), ("easy", 1))
        bomb["round"] = 2
        with patch("server.random.randint", return_value=1):
            server.update_bomb_progression(bomb)
        self.assertEqual((bomb["difficulty"], bomb["sublevel"]), ("easy", 2))
        bomb["round"] = 4
        with patch("server.random.randint", return_value=1):
            server.update_bomb_progression(bomb)
        self.assertEqual((bomb["difficulty"], bomb["sublevel"]), ("medium", 1))

    def test_word_bomb_progression_uses_five_to_seven_round_blocks(self):
        with patch("server.random.randint", return_value=6):
            bomb = server.update_bomb_progression({"round": 0})
        self.assertEqual(bomb["progression"]["nextLevelAt"], 6)
        self.assertEqual((bomb["difficulty"], bomb["sublevel"]), ("easy", 1))

    def test_word_bomb_keeps_current_turn_when_other_player_leaves(self):
        bomb = {
            "code": "BOMB01", "status": "playing", "language": "en", "round": 1, "turn": "one", "prompt": "oo",
            "players": {
                "one": self.player_one.copy(),
                "two": self.player_two.copy(),
                "three": {"uid": "three", "name": "PLAYER_THREE", "photo": "", "hearts": 3, "score": 0},
            },
            "order": ["one", "two", "three"], "usedWords": {}, "usedPrompts": ["oo"],
        }
        with closing(server.connect_db()) as database, database:
            server.write_bomb(database, bomb)
        handler = server.PoliHandler.__new__(server.PoliHandler)
        handler.send_json = lambda payload, status=200: payload
        handler.leave_bomb("BOMB01", {"uid": "two"}, {})
        with closing(server.connect_db()) as database:
            updated = server.read_bomb(database, "BOMB01")
        self.assertEqual(updated["turn"], "one")

    def test_word_bomb_can_validate_remote_prefix_chunk(self):
        server.REMOTE_BOMB_VOCABULARY = True
        response = io.BytesIO(json.dumps({"poliglota": True}).encode())
        with patch("server.urllib.request.urlopen", return_value=response):
            self.assertTrue(server.bomb_word_exists("pt", "poliglota"))

    def test_firebase_bomb_vocabulary_filters_invalid_keys(self):
        words = build_firebase_bomb_vocabulary.normalized_words(["etc.", "either ... or", "maçã", "guarda-chuva"])
        self.assertEqual(words, {"maca", "guardachuva"})
        build_firebase_bomb_vocabulary.validate_firebase_keys({"chunks": {"pt": {"ma": {"maca": True}}}})


if __name__ == "__main__":
    unittest.main()
