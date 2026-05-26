from avadex.cli import _describe_exc


def test_uses_repr_when_str_empty():
    # A bare TimeoutError() stringifies to "" — must not log blank.
    assert _describe_exc(TimeoutError()) == "TimeoutError()"


def test_plain_message():
    assert _describe_exc(ValueError("boom")) == "boom"


def test_strips_whitespace_message():
    assert _describe_exc(RuntimeError("  spaced  ")) == "spaced"


def test_unwraps_exception_group():
    eg = ExceptionGroup("grp", [TimeoutError(), ConnectionError("refused")])
    out = _describe_exc(eg)
    assert "TimeoutError()" in out
    assert "refused" in out


def test_unwraps_nested_groups():
    inner = ExceptionGroup("inner", [ValueError("v")])
    outer = ExceptionGroup("outer", [inner, TimeoutError()])
    out = _describe_exc(outer)
    assert "v" in out
    assert "TimeoutError()" in out
