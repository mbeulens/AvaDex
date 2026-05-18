import importlib.metadata

import avadex


def test_package_version_matches_metadata():
    assert avadex.__version__ == importlib.metadata.version("avadex")
