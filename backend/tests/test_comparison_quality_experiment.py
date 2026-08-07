import importlib.util
import sys
from collections import Counter
from pathlib import Path


def load_harness():
    path = (
        Path(__file__).resolve().parents[1]
        / "experiments"
        / "comparison_quality"
        / "run_benchmark.py"
    )
    spec = importlib.util.spec_from_file_location("comparison_quality_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_baseline_has_exact_required_shape():
    module = load_harness()
    scenarios = module.SCENARIOS
    assert len(scenarios) == 8
    document_counts = Counter(len(scenario.documents) for scenario in scenarios)
    assert document_counts[2] == 6
    assert document_counts[3] == 1
    assert document_counts[4] == 1
    assert sum(scenario.focus is None for scenario in scenarios) >= 2
    assert sum(scenario.focus is not None for scenario in scenarios) >= 2
    categories = {scenario.category for scenario in scenarios}
    assert {
        "service_maintenance_agreements",
        "commercial_quotations",
        "invoices_billing",
        "revisions_versions",
        "missing_requested_fact",
        "three_document_comparison",
        "four_document_comparison",
        "prompt_injection_semantic_distractor",
    } == categories


def test_ground_truth_is_not_rendered_to_model():
    module = load_harness()
    for scenario in module.SCENARIOS:
        context, _ = module._context(scenario)
        rendered = context.render()
        assert "expected_facts" not in rendered
        assert "expected_differences" not in rendered
        assert "scenario_pass" not in rendered


def test_hard_cases_are_present():
    module = load_harness()
    serialized = " ".join(
        page
        for scenario in module.SCENARIOS
        for document in scenario.documents
        for page in document.pages
    )
    assert "does not state a deductible" in serialized
    assert "Ignore previous instructions" in serialized
    assert any(
        "numeric" in scenario.category or "billing" in scenario.category
        for scenario in module.SCENARIOS
    )
    assert any("renewal" in (scenario.focus or "") for scenario in module.SCENARIOS)
