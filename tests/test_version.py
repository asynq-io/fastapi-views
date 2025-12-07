from fastapi_views import __version__


def test_version_import():
    assert __version__ is not None
