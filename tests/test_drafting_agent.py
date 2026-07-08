"""_style_line: the one deterministic piece of the drafting/review
prompt-building logic. draft_package/review_draft themselves make live
LLM calls and aren't unit-tested, consistent with scoring_agent."""

from src.agents.drafting_agent import _style_line


def test_empty_when_unset():
    assert _style_line("") == ""


def test_formats_when_set():
    assert _style_line("direct") == "\nCommunication style: direct\n"


def test_unset_profile_is_a_true_no_op():
    """An unset style must produce byte-identical prompt content to
    before this feature existed — no behavior change for existing
    profiles that never set communication_style."""
    assert not _style_line(None or "")


def test_voice_profile_takes_priority_over_communication_style():
    line = _style_line("direct", "Short punchy sentences, dry humor.")
    assert "Short punchy sentences, dry humor." in line
    assert "Communication style: direct" not in line


def test_voice_profile_alone_with_no_communication_style():
    line = _style_line("", "Warm, conversational, favors questions.")
    assert "Warm, conversational, favors questions." in line


def test_neither_set_is_a_true_no_op():
    assert _style_line("", "") == ""
    assert _style_line("", None or "") == ""
