"""The rule catalog and its wiring into agent instructions."""

from app.schemas.review import ReviewCategory
from app.services.agent_service import AgentService
from app.services.review_rules import RULE_SETS, all_rule_sets, get_rule_set


def test_every_category_has_a_rule_set():
    assert set(RULE_SETS) == set(ReviewCategory)


def test_rule_sets_are_populated():
    for rs in all_rule_sets():
        assert rs.display_name and rs.description
        assert len(rs.rules) >= 5
        assert rs.retrieval_query.strip()


def test_security_rules_cover_key_attacks():
    rules_text = " ".join(get_rule_set(ReviewCategory.SECURITY).rules).lower()
    for keyword in ("injection", "xss", "path travers", "secret", "auth",
                    "deserial", "ssrf", "csrf"):
        assert keyword in rules_text, f"security rules missing: {keyword}"


def test_style_rules_cover_dead_code_and_structure():
    rules_text = " ".join(get_rule_set(ReviewCategory.STYLE).rules).lower()
    for keyword in ("dead code", "unused", "duplicat", "naming"):
        assert keyword in rules_text, f"style rules missing: {keyword}"


def test_reviewer_instructions_built_from_rules():
    instr = AgentService.reviewer(ReviewCategory.SECURITY).instructions
    assert "RULES" in instr
    assert "SQL" in instr and "XSS" in instr
    # every rule appears in the instructions
    for rule in get_rule_set(ReviewCategory.SECURITY).rules:
        assert rule[:30] in instr
