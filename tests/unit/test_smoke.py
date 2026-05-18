import re

import avadex


def test_package_version_is_semver():
    assert isinstance(avadex.__version__, str)
    assert re.fullmatch(r"\d+\.\d+\.\d+", avadex.__version__), (
        f"__version__ {avadex.__version__!r} is not X.Y.Z semver"
    )
