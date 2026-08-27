"""Tests for `offerleaks.services.company_normalization` (M7). Pure
functions -- no DB/Redis needed."""

from offerleaks.services.company_normalization import (
    is_freemail_domain,
    normalize_company_name,
    normalize_domain,
    resolve_identity_key,
)


def test_normalize_domain_strips_scheme_www_path_port():
    assert normalize_domain("https://www.Acme.com:8080/careers") == "acme.com"


def test_normalize_domain_is_case_insensitive():
    assert normalize_domain("ACME.COM") == normalize_domain("acme.com") == "acme.com"


def test_normalize_domain_handles_multi_label_tld():
    assert normalize_domain("www.acme.co.uk") == "acme.co.uk"


def test_normalize_domain_tolerates_an_email_by_mistake():
    assert normalize_domain("hr@acme.com") == "acme.com"


def test_normalize_domain_rejects_malformed_input():
    assert normalize_domain("not a domain") is None
    assert normalize_domain("") is None
    assert normalize_domain(None) is None
    assert normalize_domain("just-text") is None
    assert normalize_domain("a..com") is None


def test_normalize_company_name_strips_legal_suffix_and_case():
    assert normalize_company_name("Acme Corp.") == "acme"
    assert normalize_company_name("ACME CORPORATION") == "acme"
    assert normalize_company_name("acme inc") == "acme"


def test_normalize_company_name_equivalent_forms_match():
    assert normalize_company_name("Acme, Inc.") == normalize_company_name("acme inc")


def test_normalize_company_name_returns_none_for_punctuation_only():
    assert normalize_company_name("...") is None
    assert normalize_company_name(None) is None


def test_normalize_company_name_does_not_over_strip_a_name_that_is_only_a_suffix_word():
    # "Ltd" alone shouldn't normalize to an empty/None key.
    assert normalize_company_name("Ltd") == "ltd"


def test_is_freemail_domain():
    assert is_freemail_domain("gmail.com")
    assert is_freemail_domain("WWW.GMAIL.COM")
    assert not is_freemail_domain("acme.com")


def test_resolve_identity_key_prefers_domain_over_name():
    assert resolve_identity_key(domain="acme.com", company_name="Someone Else Ltd") == (
        "domain:acme.com"
    )


def test_resolve_identity_key_falls_back_to_name_when_no_domain():
    assert resolve_identity_key(domain=None, company_name="Acme Corp") == "name:acme"


def test_resolve_identity_key_equivalent_domains_produce_the_same_key():
    a = resolve_identity_key(domain="https://www.Acme.com/", company_name=None)
    b = resolve_identity_key(domain="ACME.COM", company_name=None)
    assert a == b


def test_resolve_identity_key_equivalent_names_produce_the_same_key():
    a = resolve_identity_key(domain=None, company_name="Acme Corp.")
    b = resolve_identity_key(domain=None, company_name="ACME CORPORATION")
    assert a == b


def test_resolve_identity_key_returns_none_when_nothing_resolvable():
    assert resolve_identity_key(domain=None, company_name=None) is None
    assert resolve_identity_key(domain="not a domain", company_name="...") is None
