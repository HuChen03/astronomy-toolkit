import unittest

from literature_digest_agent.keywords import KeywordCategory, classify_by_keywords, extract_keywords, rerank_items


class KeywordTests(unittest.TestCase):
    def test_keyword_match_is_prioritized_over_upstream_score(self):
        categories = [KeywordCategory(id="kagome", name="Kagome", terms=("kagome",), weight=5)]
        result = rerank_items(
            [
                {"paper_id": "high", "title": "Unrelated", "score": 100},
                {"paper_id": "match", "title": "Kagome superconductor", "score": 0.1},
            ],
            categories,
        )
        self.assertEqual(result[0]["paper_id"], "match")
        self.assertTrue(result[0]["keyword_matched"])

    def test_title_match_scores_higher_than_abstract_match(self):
        category = KeywordCategory(id="battery", name="Battery", terms=("zinc ion battery",), weight=2)
        _, title_score = classify_by_keywords({"title": "Zinc-ion battery anodes"}, [category])
        _, abstract_score = classify_by_keywords(
            {"title": "Anode study", "abstract": "A zinc ion battery experiment"},
            [category],
        )
        self.assertGreater(title_score, abstract_score)

    def test_all_match_mode_requires_every_term(self):
        category = KeywordCategory(
            id="narrow",
            name="Narrow",
            terms=("zinc", "dendrite"),
            match_mode="all",
        )
        matches, score = classify_by_keywords({"title": "Zinc anodes"}, [category])
        self.assertEqual(matches, [])
        self.assertEqual(score, 0)

    def test_extract_keywords_returns_ranked_terms(self):
        keywords = extract_keywords(
            {
                "title": "Stable zinc anode",
                "abstract": "Zinc zinc dendrite suppression for battery anode.",
            },
            max_terms=3,
        )
        self.assertIn("zinc", keywords)
        self.assertLessEqual(len(keywords), 3)


if __name__ == "__main__":
    unittest.main()
