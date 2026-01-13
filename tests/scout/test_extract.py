import pytest
import json

from scout.extract import Extractor


class TestExtractorParsing:
    @pytest.fixture
    def extractor(self):
        return Extractor(model="gpt-4o", prompt_version="v1")

    def test_parse_valid_json(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "I hate this product",
                    "pain_statement": "Product is frustrating",
                    "signal_type": "complaint",
                    "intensity": 4,
                    "confidence": 0.9,
                    "entities": ["ProductX"],
                }
            ],
            "entities": ["ProductX", "CompanyY"],
            "follow_up_queries": ["ProductX alternatives"],
            "novelty": 0.8,
        })

        result = extractor._parse_response(content, "doc:123")

        assert len(result.snippets) == 1
        assert result.snippets[0].pain_statement == "Product is frustrating"
        assert result.snippets[0].signal_type == "complaint"
        assert result.snippets[0].intensity == 4
        assert result.snippets[0].confidence == 0.9
        assert result.entities == ["ProductX", "CompanyY"]
        assert result.follow_up_queries == ["ProductX alternatives"]
        assert result.novelty == 0.8

    def test_parse_json_with_code_fence(self, extractor):
        content = '''```json
{
    "snippets": [],
    "entities": ["Test"],
    "follow_up_queries": [],
    "novelty": 0.5
}
```'''

        result = extractor._parse_response(content, "doc:123")

        assert result.entities == ["Test"]
        assert result.novelty == 0.5

    def test_parse_json_with_simple_code_fence(self, extractor):
        content = '''```
{
    "snippets": [],
    "entities": [],
    "follow_up_queries": [],
    "novelty": 0.3
}
```'''

        result = extractor._parse_response(content, "doc:123")

        assert result.novelty == 0.3

    def test_parse_malformed_json_raises(self, extractor):
        content = "{ invalid json }"

        with pytest.raises(json.JSONDecodeError):
            extractor._parse_response(content, "doc:123")

    def test_parse_missing_snippets_field(self, extractor):
        content = json.dumps({
            "entities": ["Test"],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert len(result.snippets) == 0
        assert result.entities == ["Test"]

    def test_parse_invalid_intensity_clamped_high(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "complaint",
                    "intensity": 10,
                    "confidence": 0.5,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].intensity == 5

    def test_parse_invalid_intensity_clamped_low(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "complaint",
                    "intensity": -5,
                    "confidence": 0.5,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].intensity == 1

    def test_parse_invalid_intensity_non_numeric(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "complaint",
                    "intensity": "high",
                    "confidence": 0.5,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].intensity == 3

    def test_parse_invalid_signal_type_defaults(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "invalid_type",
                    "intensity": 3,
                    "confidence": 0.5,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].signal_type == "complaint"

    def test_parse_valid_signal_types(self, extractor):
        valid_types = [
            "complaint", "wish", "workaround", "switch",
            "bug", "pricing", "support", "integration", "workflow"
        ]

        for signal_type in valid_types:
            content = json.dumps({
                "snippets": [
                    {
                        "excerpt": "test",
                        "pain_statement": "test",
                        "signal_type": signal_type,
                        "intensity": 3,
                        "confidence": 0.5,
                        "entities": [],
                    }
                ],
                "entities": [],
                "follow_up_queries": [],
                "novelty": 0.5,
            })

            result = extractor._parse_response(content, "doc:123")

            assert result.snippets[0].signal_type == signal_type

    def test_parse_signal_type_case_insensitive(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "COMPLAINT",
                    "intensity": 3,
                    "confidence": 0.5,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].signal_type == "complaint"

    def test_parse_missing_entities_defaults_empty(self, extractor):
        content = json.dumps({
            "snippets": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.entities == []

    def test_parse_entities_non_list_defaults_empty(self, extractor):
        content = json.dumps({
            "snippets": [],
            "entities": "not a list",
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.entities == []

    def test_parse_novelty_out_of_range_high_clamped(self, extractor):
        content = json.dumps({
            "snippets": [],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 1.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.novelty == 1.0

    def test_parse_novelty_out_of_range_low_clamped(self, extractor):
        content = json.dumps({
            "snippets": [],
            "entities": [],
            "follow_up_queries": [],
            "novelty": -0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.novelty == 0.0

    def test_parse_novelty_missing_defaults(self, extractor):
        content = json.dumps({
            "snippets": [],
            "entities": [],
            "follow_up_queries": [],
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.novelty == 0.5

    def test_parse_confidence_clamped(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "complaint",
                    "intensity": 3,
                    "confidence": 2.0,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].confidence == 1.0

    def test_parse_follow_up_queries_truncated(self, extractor):
        content = json.dumps({
            "snippets": [],
            "entities": [],
            "follow_up_queries": ["q1", "q2", "q3", "q4", "q5", "q6", "q7"],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert len(result.follow_up_queries) == 5

    def test_parse_follow_up_queries_non_list_defaults_empty(self, extractor):
        content = json.dumps({
            "snippets": [],
            "entities": [],
            "follow_up_queries": "not a list",
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.follow_up_queries == []

    def test_parse_snippet_with_missing_fields_uses_defaults(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "minimal snippet",
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert len(result.snippets) == 1
        assert result.snippets[0].excerpt == "minimal snippet"
        assert result.snippets[0].pain_statement == ""
        assert result.snippets[0].signal_type == "complaint"
        assert result.snippets[0].intensity == 3
        assert result.snippets[0].confidence == 0.5

    def test_parse_multiple_snippets(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "first",
                    "pain_statement": "pain 1",
                    "signal_type": "complaint",
                    "intensity": 3,
                    "confidence": 0.8,
                    "entities": [],
                },
                {
                    "excerpt": "second",
                    "pain_statement": "pain 2",
                    "signal_type": "wish",
                    "intensity": 4,
                    "confidence": 0.9,
                    "entities": ["Product"],
                },
            ],
            "entities": ["Product"],
            "follow_up_queries": [],
            "novelty": 0.7,
        })

        result = extractor._parse_response(content, "doc:123")

        assert len(result.snippets) == 2
        assert result.snippets[0].pain_statement == "pain 1"
        assert result.snippets[1].pain_statement == "pain 2"
        assert result.snippets[1].signal_type == "wish"

    def test_parse_sets_extractor_provenance(self, extractor):
        content = json.dumps({
            "snippets": [
                {
                    "excerpt": "test",
                    "pain_statement": "test",
                    "signal_type": "complaint",
                    "intensity": 3,
                    "confidence": 0.5,
                    "entities": [],
                }
            ],
            "entities": [],
            "follow_up_queries": [],
            "novelty": 0.5,
        })

        result = extractor._parse_response(content, "doc:123")

        assert result.snippets[0].extractor_model == "gpt-4o"
        assert result.snippets[0].extractor_prompt_version == "v1"
        assert result.snippets[0].doc_id == "doc:123"


class TestExtractorHelpers:
    @pytest.fixture
    def extractor(self):
        return Extractor()

    def test_validate_signal_type_valid(self, extractor):
        assert extractor._validate_signal_type("complaint") == "complaint"
        assert extractor._validate_signal_type("WISH") == "wish"
        assert extractor._validate_signal_type(" bug ") == "bug"

    def test_validate_signal_type_invalid(self, extractor):
        assert extractor._validate_signal_type("invalid") == "complaint"
        assert extractor._validate_signal_type("") == "complaint"

    def test_clamp_within_range(self, extractor):
        assert extractor._clamp(5, 1, 10) == 5.0
        assert extractor._clamp(0.5, 0.0, 1.0) == 0.5

    def test_clamp_above_max(self, extractor):
        assert extractor._clamp(15, 1, 10) == 10.0
        assert extractor._clamp(1.5, 0.0, 1.0) == 1.0

    def test_clamp_below_min(self, extractor):
        assert extractor._clamp(-5, 1, 10) == 1.0
        assert extractor._clamp(-0.5, 0.0, 1.0) == 0.0

    def test_clamp_non_numeric_returns_midpoint(self, extractor):
        assert extractor._clamp("invalid", 1, 5) == 3.0
        assert extractor._clamp(None, 0.0, 1.0) == 0.5

    def test_empty_result(self, extractor):
        result = extractor._empty_result()

        assert result.snippets == []
        assert result.entities == []
        assert result.follow_up_queries == []
        assert result.novelty == 0.5
