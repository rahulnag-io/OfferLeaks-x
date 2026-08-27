"""Verifies every RQ job function referenced *by string path* (the way
`.enqueue("module.path.func", ...)` calls do throughout `services/`)
actually resolves to a real, importable, callable function.

RQ resolves these strings at *job-execution* time, not at import/
type-check time -- a typo in one of these paths would only surface when
a worker actually tries to run the job, which is exactly the kind of
silent failure this test exists to catch ahead of time.
"""

import importlib

_JOB_FUNCTION_PATHS = [
    "offerleaks.worker.process_analysis",
    "offerleaks.worker.process_company_refresh",
]


def test_all_enqueued_job_function_paths_resolve_to_real_callables():
    for path in _JOB_FUNCTION_PATHS:
        module_path, _, func_name = path.rpartition(".")
        module = importlib.import_module(module_path)
        func = getattr(module, func_name, None)
        assert func is not None, f"{path} does not resolve to anything importable"
        assert callable(func), f"{path} resolved to a non-callable: {func!r}"


def test_job_function_paths_match_what_is_actually_passed_to_enqueue():
    """Cross-checks the hardcoded list above against the actual string
    literals passed to `.enqueue(...)` in the source, so this test can't
    silently drift out of sync with the real call sites (e.g. if a third
    enqueue call is added later and nobody updates `_JOB_FUNCTION_PATHS`
    above)."""
    import inspect

    from offerleaks.services import analysis_service, company_profile_service

    found_paths = set()
    for module in (analysis_service, company_profile_service):
        source = inspect.getsource(module)
        for path in _JOB_FUNCTION_PATHS:
            if f'"{path}"' in source:
                found_paths.add(path)

    assert found_paths == set(_JOB_FUNCTION_PATHS), (
        "mismatch between the job paths this test checks and what's actually "
        f"enqueued in source: checked={set(_JOB_FUNCTION_PATHS)} found={found_paths}"
    )
