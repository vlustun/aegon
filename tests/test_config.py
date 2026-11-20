"""Per-role model resolution: defaults, aliases and aegon.json overrides."""

from aegon.config import HAIKU, OPUS, SONNET, Settings, resolve_model


def test_default_models_match_cost_to_role():
    s = Settings()
    assert s.planner_model == OPUS  # reasoning over the whole task
    assert s.scaffolder_model == SONNET
    assert s.tester_model == SONNET
    assert s.fixer_model == SONNET


def test_resolve_model_maps_aliases_and_passes_full_ids_through():
    assert resolve_model("opus") == OPUS
    assert resolve_model("HAIKU") == HAIKU
    assert resolve_model(" sonnet ") == SONNET
    assert resolve_model("claude-opus-5-5") == OPUS
    assert resolve_model("some-future-model") == "some-future-model"


def test_with_models_overrides_only_named_roles():
    s = Settings().with_models({"planner": "sonnet", "fixer": "haiku"})
    assert s.planner_model == SONNET
    assert s.fixer_model == HAIKU
    # untouched roles keep their defaults
    assert s.scaffolder_model == SONNET
    assert s.tester_model == SONNET


def test_with_models_ignores_unknown_roles_and_blanks():
    base = Settings()
    s = base.with_models({"bogus": "opus", "planner": "   ", "tester": ""})
    assert s.planner_model == base.planner_model
    assert s.tester_model == base.tester_model


def test_with_models_is_a_noop_without_changes():
    base = Settings()
    assert base.with_models(None) is base
    assert base.with_models({}) is base
    assert base.with_models({"unknown": "opus"}) is base


def test_with_models_does_not_mutate_the_base():
    base = Settings()
    base.with_models({"planner": "haiku"})
    assert base.planner_model == OPUS
