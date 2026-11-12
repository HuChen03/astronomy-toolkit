import unittest
from unittest.mock import Mock

from literature_digest_agent.classifier import (
    attach_failed_llm_classification,
    attach_rule_based_classification,
    normalize_taxonomy,
    validate_llm_classification,
    _classify_one_with_agent,
)


class ClassifierTests(unittest.TestCase):
    def test_rule_based_classification_uses_top_keyword_category(self):
        item = {
            "paper_id": "p1",
            "title": "Stable zinc anode",
            "keyword_categories": [
                {
                    "category_id": "battery",
                    "category": "Battery",
                    "matched_terms": ["zinc anode"],
                    "match_score": 3,
                }
            ],
            "recognized_keywords": ["zinc anode"],
            "extracted_keywords": ["zinc", "anode"],
        }
        result = attach_rule_based_classification(item)
        self.assertEqual(result["classification"]["primary_category"]["id"], "battery")
        self.assertFalse(result["classification"]["needs_human_review"])

    def test_llm_classification_must_use_predefined_category(self):
        taxonomy = normalize_taxonomy(
            {"categories": [{"id": "battery", "name": "Battery"}]}
        )
        result = validate_llm_classification(
            {"primary_category_id": "battery", "confidence": 0.8},
            taxonomy,
        )
        self.assertEqual(result["primary_category"]["id"], "battery")
        with self.assertRaises(ValueError):
            validate_llm_classification(
                {"primary_category_id": "invented", "confidence": 0.8},
                taxonomy,
            )

    def test_failed_llm_classification_uses_other_with_failed_status(self):
        taxonomy = normalize_taxonomy(
            {"categories": [{"id": "battery", "name": "Battery"}]}
        )
        result = attach_failed_llm_classification({"paper_id": "p1"}, taxonomy, "failed")
        self.assertEqual(result["classification"]["status"], "failed")
        self.assertEqual(result["classification"]["primary_category"]["id"], "other")

    def test_invalid_model_category_is_retried_once(self):
        taxonomy = normalize_taxonomy(
            {"categories": [{"id": "battery", "name": "Battery"}]}
        )
        agent = Mock()
        agent.classify.side_effect = [
            {"primary_category_id": "invented", "confidence": 0.8},
            {"primary_category_id": "battery", "confidence": 0.9},
        ]
        result = _classify_one_with_agent(agent, {"paper_id": "p1", "title": "Paper"}, taxonomy)
        self.assertEqual(agent.classify.call_count, 2)
        self.assertEqual(result["classification"]["primary_category"]["id"], "battery")


if __name__ == "__main__":
    unittest.main()
