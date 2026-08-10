from __future__ import annotations

import json
import re
import sys
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from typer.testing import CliRunner

from fastapi_views.cli import cli, import_from_string

runner = CliRunner()

APP_MODULE = """
from fastapi import FastAPI

app = FastAPI(title="TmpApp")
not_an_app = object()
"""


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    module_name = "tmp_cli_app"
    (tmp_path / f"{module_name}.py").write_text(APP_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module_name


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


def normalize(text: str) -> str:
    return " ".join(ANSI_ESCAPE.sub("", text).split())


def test_import_from_string_success():
    result = import_from_string("fastapi:FastAPI")
    assert result is FastAPI


def test_import_from_string_missing_attribute():
    with pytest.raises(ImportError, match="has no object"):
        import_from_string("fastapi:NonExistentThing")


def test_import_from_string_missing_module():
    with pytest.raises(ModuleNotFoundError):
        import_from_string("nonexistent_module_xyz:Something")


def test_help_lists_docs_command():
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "docs" in result.output


def test_docs_help():
    result = runner.invoke(cli, ["docs", "--help"])

    assert result.exit_code == 0
    assert "Generate OpenAPI documentation" in normalize(result.output)


def test_docs_subcommand_writes_file(app_module, tmp_path):
    out = tmp_path / "spec.json"

    result = runner.invoke(cli, ["docs", f"{app_module}:app", "--out", str(out)])

    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text())
    assert data["info"]["title"] == "TmpApp"


def test_docs_default_out_path(app_module, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["docs", f"{app_module}:app"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "openapi.json").exists()


def test_docs_json(tmp_path):
    out = tmp_path / "openapi.json"
    app = FastAPI(title="TestApp")

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(cli, ["docs", "fake:app", "--out", str(out)])

    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "openapi" in data


def test_docs_yaml(tmp_path):
    pytest.importorskip("yaml")
    out = tmp_path / "openapi.yaml"
    app = FastAPI(title="TestApp")

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(
            cli, ["docs", "fake:app", "--out", str(out), "--format", "yaml"]
        )

    assert result.exit_code == 0
    assert out.exists()
    content = out.read_text()
    assert "openapi" in content


def test_docs_yaml_without_pyyaml(tmp_path, monkeypatch):
    out = tmp_path / "openapi.yaml"
    app = FastAPI(title="TestApp")
    monkeypatch.setitem(sys.modules, "yaml", None)

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(
            cli, ["docs", "fake:app", "--out", str(out), "--format", "yaml"]
        )

    assert result.exit_code == 2
    output = normalize(result.output)
    assert "PyYAML is required for '--format yaml'." in output
    assert "pip install pyyaml" in output
    assert not out.exists()


def test_docs_invalid_format(tmp_path):
    out = tmp_path / "openapi.txt"
    app = FastAPI()

    with patch("fastapi_views.cli.import_from_string", return_value=app):
        result = runner.invoke(
            cli, ["docs", "fake:app", "--out", str(out), "--format", "xml"]
        )

    assert result.exit_code != 0
    assert isinstance(result.exception, ValueError)


def test_docs_not_fastapi_app(app_module, tmp_path):
    out = tmp_path / "openapi.json"

    result = runner.invoke(cli, ["docs", f"{app_module}:not_an_app", "--out", str(out)])

    assert result.exit_code != 0
    assert isinstance(result.exception, TypeError)
    assert not out.exists()


def test_bare_app_argument_is_no_longer_supported(tmp_path):
    out = tmp_path / "openapi.json"

    result = runner.invoke(cli, ["fake:app", "--out", str(out)])

    assert result.exit_code == 2
    assert "No such command" in normalize(result.output)
    assert not out.exists()


def test_no_args_shows_help():
    result = runner.invoke(cli, [])

    assert result.exit_code != 0
    assert "docs" in result.output
