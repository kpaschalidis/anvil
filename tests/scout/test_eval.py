import json
from pathlib import Path
from dataclasses import dataclass

from tests.scout.eval_queries import EVAL_QUERIES


@dataclass
class EvalResult:
    query_id: str
    topic: str
    passed: bool
    checks: dict
    details: dict


def evaluate_session(session_results: dict, query_config: dict) -> EvalResult:
    checks = {}
    details = {}

    doc_count = len(session_results.get("documents", []))
    min_docs = query_config["min_docs"]
    checks["min_docs"] = {
        "expected": min_docs,
        "actual": doc_count,
        "passed": doc_count >= min_docs,
    }

    snippet_count = len(session_results.get("snippets", []))
    min_snippets = query_config["min_snippets"]
    checks["min_snippets"] = {
        "expected": min_snippets,
        "actual": snippet_count,
        "passed": snippet_count >= min_snippets,
    }

    found_entities: set[str] = set()
    for snippet in session_results.get("snippets", []):
        found_entities.update(snippet.get("entities", []))

    expected_entities = set(e.lower() for e in query_config["expected_entities"])
    found_lower = set(e.lower() for e in found_entities)
    entity_overlap = found_lower & expected_entities
    checks["entities"] = {
        "expected": list(query_config["expected_entities"]),
        "found": list(entity_overlap),
        "all_found": list(found_entities)[:20],
        "passed": len(entity_overlap) >= 1,
    }

    found_types: set[str] = set()
    for snippet in session_results.get("snippets", []):
        found_types.add(snippet.get("signal_type", ""))

    expected_types = set(query_config["expected_signal_types"])
    type_overlap = found_types & expected_types
    checks["signal_types"] = {
        "expected": list(expected_types),
        "found": list(type_overlap),
        "all_found": list(found_types),
        "passed": len(type_overlap) >= 1,
    }

    overall_passed = all(c["passed"] for c in checks.values())

    details["sample_snippets"] = [
        {
            "pain_statement": s.get("pain_statement", ""),
            "signal_type": s.get("signal_type", ""),
            "intensity": s.get("intensity", 0),
        }
        for s in session_results.get("snippets", [])[:5]
    ]

    return EvalResult(
        query_id=query_config["id"],
        topic=query_config["topic"],
        passed=overall_passed,
        checks=checks,
        details=details,
    )


def run_evaluation(session_dir: Path) -> EvalResult | None:
    state_path = session_dir / "state.json"
    if not state_path.exists():
        return None

    with open(state_path) as f:
        state = json.load(f)

    topic = state.get("topic", "")

    query_config = None
    for q in EVAL_QUERIES:
        if q["topic"].lower() == topic.lower():
            query_config = q
            break

    if not query_config:
        return None

    docs_path = session_dir / "raw.jsonl"
    documents = []
    if docs_path.exists():
        with open(docs_path) as f:
            for line in f:
                if line.strip():
                    documents.append(json.loads(line))

    snippets_path = session_dir / "snippets.jsonl"
    snippets = []
    if snippets_path.exists():
        with open(snippets_path) as f:
            for line in f:
                if line.strip():
                    snippets.append(json.loads(line))

    session_results = {
        "documents": documents,
        "snippets": snippets,
    }

    return evaluate_session(session_results, query_config)


def print_eval_report(results: list[EvalResult]) -> None:
    print("\n" + "=" * 60)
    print("EVALUATION REPORT")
    print("=" * 60)

    passed_count = sum(1 for r in results if r.passed)
    total_count = len(results)

    print(f"\nOverall: {passed_count}/{total_count} queries passed ({100*passed_count/total_count:.0f}%)\n")

    for result in results:
        status = "✓ PASS" if result.passed else "✗ FAIL"
        print(f"\n{status}: {result.query_id}")
        print(f"  Topic: {result.topic}")

        for check_name, check_data in result.checks.items():
            check_status = "✓" if check_data["passed"] else "✗"
            if check_name in ("min_docs", "min_snippets"):
                print(f"  {check_status} {check_name}: {check_data['actual']}/{check_data['expected']}")
            else:
                print(f"  {check_status} {check_name}: found {len(check_data.get('found', []))} of {len(check_data['expected'])}")

    print("\n" + "=" * 60)
    print(f"PASS RATE: {100*passed_count/total_count:.0f}%")
    if passed_count >= 16:
        print("✓ Target met (>= 80%)")
    else:
        print(f"✗ Target not met (need {16 - passed_count} more passing)")
    print("=" * 60 + "\n")
