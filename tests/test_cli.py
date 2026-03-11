from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from fastapi_views.cli import cli, import_from_string

runner = CliRunner()


# ---- import_from_string ----


def test_import_from_string_success():
    result = import_from_string("fastapi:FastAPI")
    assert result is FastAPI


def test_import_from_string_missing_attribute():
    with pytest.raises(ImportError, match="has no object"):
        import_from_string("fastapi:NonExistentThing")


def test_import_from_string_missing_module():
    with pytest.raises(ModuleNotFoundError):
        import_from_string("nonexistent_module_xyz:Something")


# ---- docs command ----


def test_docs_json(tmp_path):
    out = tmp_path / "openapi.json"
    app = FastAPI(title="TestApp")

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(cli, ["fake:app", "--out", str(out)])

    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "openapi" in data


def test_docs_yaml(tmp_path):
    pytest.importorskip("yaml")
    out = tmp_path / "openapi.yaml"
    app = FastAPI(title="TestApp")

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(cli, ["fake:app", "--out", str(out), "--format", "yaml"])

    assert result.exit_code == 0
    assert out.exists()
    content = out.read_text()
    assert "openapi" in content


def test_docs_invalid_format(tmp_path):
    out = tmp_path / "openapi.txt"
    app = FastAPI()

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(cli, ["fake:app", "--out", str(out), "--format", "xml"])

    assert result.exit_code != 0


def test_docs_not_fastapi_app(tmp_path):
    out = tmp_path / "openapi.json"

    with patch("fastapi_views.cli.import_from_string", return_value=object()):
        result = runner.invoke(cli, ["fake:not_an_app", "--out", str(out)])

    assert result.exit_code != 0
