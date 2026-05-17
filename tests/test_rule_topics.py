from __future__ import annotations

import unittest

from bot.event_cog import _RULE_HELP_TOPICS, _RULE_RESPONSES, _RULE_TOPIC_LOOKUP, _normalize_rule_topic


class TestRuleTopics(unittest.TestCase):
    def test_help_topics_match_expected_order(self) -> None:
        self.assertEqual(
            _RULE_HELP_TOPICS,
            "age, dm, respect, spam, catfish, ai, school, intro, oneintro, verify, scammer, coercion, dox",
        )

    def test_canonical_topic_lookup(self) -> None:
        canonical = _RULE_TOPIC_LOOKUP.get(_normalize_rule_topic("CatFish"))
        self.assertEqual(canonical, "catfish")
        self.assertIn("## Rule 5: NO CATFISHING 🎣", _RULE_RESPONSES[canonical])

    def test_alias_lookup_is_case_insensitive(self) -> None:
        self.assertEqual(_RULE_TOPIC_LOOKUP.get(_normalize_rule_topic("DMRequests")), "dm")
        self.assertEqual(_RULE_TOPIC_LOOKUP.get(_normalize_rule_topic("One-Intro")), "oneintro")
        self.assertEqual(_RULE_TOPIC_LOOKUP.get(_normalize_rule_topic("UNVERIFIED")), "verify")

    def test_unknown_topic_returns_no_match(self) -> None:
        self.assertIsNone(_RULE_TOPIC_LOOKUP.get(_normalize_rule_topic("not-a-rule")))


if __name__ == "__main__":
    unittest.main()
