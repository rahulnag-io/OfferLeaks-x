"""Tests for `offerleaks.services.company_extraction` (M7). Pure
functions over plain text -- no DB/Redis needed."""

from offerleaks.services.company_extraction import extract_company_signals

LETTER_WITH_COMPANY_EMAIL = """
Offer Letter

Dear Priya,

On behalf of: Acme Technologies Inc.

We are pleased to offer you the position of Senior Engineer.

Please reach out to hr@acme.com with any questions, or cc
recruiting@acme.com.

Regards,
Acme Technologies Inc.
"""

LETTER_WITH_ONLY_FREEMAIL = """
Congratulations, you're hired! Reply to recruiter@gmail.com to accept.
No company name is mentioned anywhere in this message.
"""

LETTER_WITH_NO_EMAIL_OR_NAME = """
We are pleased to offer you a position at our organization. Please see
the attached documents for details of compensation and start date.
"""


def test_extracts_sender_domain_from_most_frequent_non_freemail_address():
    result = extract_company_signals(LETTER_WITH_COMPANY_EMAIL)
    assert result.sender_domain == "acme.com"


def test_extracts_company_name_from_letterhead_line():
    result = extract_company_signals(LETTER_WITH_COMPANY_EMAIL)
    assert result.company_name is not None
    assert "acme" in result.company_name.lower()


def test_freemail_only_document_has_no_sender_domain():
    result = extract_company_signals(LETTER_WITH_ONLY_FREEMAIL)
    assert result.sender_domain is None


def test_document_with_neither_signal_returns_both_none():
    result = extract_company_signals(LETTER_WITH_NO_EMAIL_OR_NAME)
    assert result.sender_domain is None
    assert result.company_name is None


def test_prefers_the_most_frequent_domain_when_multiple_appear():
    text = (
        "Contact hr@acme.com. Also cc recruiting@acme.com and "
        "legal@acme.com. A third party consultant used "
        "consultant@onceoff-agency.com for one message."
    )
    result = extract_company_signals(text)
    assert result.sender_domain == "acme.com"


# --- Fallbacks for documents with no usable email address at all
#     (audit finding: real internship/training-scheme letters --  the
#     exact kind most worth flagging -- often have neither a proper
#     email address nor a "company name:"/"on behalf of:"/legal-suffix
#     line) ---

NO_EMAIL_BUT_HAS_WEBSITE_AND_LETTERHEAD = """
YuvaIntern

Dear Priya,

Congratulations! We are pleased to offer you the Virtual Construction
Business Intelligence Internship.

This is a Power BI Certification Training Course covering hands-on
tasks, guided tutorials, and mentorship.

Please visit www.yuvaintern.com for onboarding details.
"""


def test_falls_back_to_a_bare_website_mention_when_no_email_present():
    result = extract_company_signals(NO_EMAIL_BUT_HAS_WEBSITE_AND_LETTERHEAD)
    assert result.sender_domain == "yuvaintern.com"


def test_falls_back_to_an_unlabeled_letterhead_first_line_for_company_name():
    result = extract_company_signals(NO_EMAIL_BUT_HAS_WEBSITE_AND_LETTERHEAD)
    assert result.company_name == "YuvaIntern"


def test_letterhead_fallback_skips_generic_header_phrases():
    text = "Offer Letter\n\nCongratulations!\n\nDear Sam,\n\nWe are pleased to offer you a role."
    result = extract_company_signals(text)
    assert result.company_name is None


def test_website_fallback_ignores_third_party_platform_domains():
    text = (
        "Please join our onboarding call at https://zoom.us/j/123456789 "
        "and fill out the form at https://forms.gle/abc123.\n"
        "No company name or proper email is mentioned anywhere."
    )
    result = extract_company_signals(text)
    assert result.sender_domain is None


def test_email_evidence_still_wins_over_a_website_mention_when_both_present():
    text = "Contact hr@realco.com for questions. Also see www.unrelated-marketing-site.io."
    result = extract_company_signals(text)
    assert result.sender_domain == "realco.com"


def test_document_with_truly_nothing_extractable_returns_both_none():
    text = (
        "Offer Letter\n\nDear Applicant,\n\nWe are pleased to offer you a "
        "position. Please review the attached terms and reply to confirm."
    )
    result = extract_company_signals(text)
    assert result.sender_domain is None
    assert result.company_name is None
