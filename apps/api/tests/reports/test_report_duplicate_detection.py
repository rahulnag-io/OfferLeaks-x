"""Duplicate-detection accuracy tests (M8). Pure unit tests -- no DB, no
AI -- against `services/report_duplicate_detection.py` directly.
"""

from offerleaks.services.report_duplicate_detection import (
    is_duplicate_description,
    normalize_report_text,
    similarity_ratio,
)


def test_normalize_report_text_lowercases_and_collapses_whitespace():
    assert (
        normalize_report_text("  They Asked ME for   $500\nUP-FRONT!!  ")
        == "they asked me for 500 up front"
    )


def test_identical_descriptions_are_a_duplicate():
    a = normalize_report_text(
        "Recruiter asked me to pay a $200 registration fee before the interview."
    )
    b = normalize_report_text(
        "Recruiter asked me to pay a $200 registration fee before the interview."
    )
    assert is_duplicate_description(a, b) is True


def test_materially_similar_descriptions_are_a_duplicate():
    a = normalize_report_text(
        "The recruiter asked me to pay a $200 registration fee "
        "before my interview could be scheduled."
    )
    b = normalize_report_text(
        "This recruiter asked me to pay a $200 registration fee before the interview was scheduled."
    )
    assert is_duplicate_description(a, b) is True


def test_clearly_distinct_descriptions_are_not_a_duplicate():
    a = normalize_report_text(
        "They asked for a $500 upfront payment before I could start training."
    )
    b = normalize_report_text(
        "The offer letter used a Gmail address and had no company letterhead at all."
    )
    assert is_duplicate_description(a, b) is False


def test_similarity_ratio_is_symmetric():
    a = normalize_report_text("asked for bank details immediately")
    b = normalize_report_text("asked for my bank details right away")
    assert similarity_ratio(a, b) == similarity_ratio(b, a)


def test_empty_strings_are_not_treated_as_meaningfully_similar_to_real_text():
    assert is_duplicate_description("", "a real complaint about a scam offer") is False


def test_two_empty_strings_are_trivially_identical():
    assert is_duplicate_description("", "") is True
