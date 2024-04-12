import importlib
import sys
from pathlib import Path
from typing import Any

import typer
from fastapi import FastAPI

cli = typer.Typer()


if "." not in sys.path:
    sys.path.insert(0, ".")


def import_from_string(path: str) -> Any:
    module_name, _, obj = path.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, obj)
    except AttributeError:
        raise ImportError(f"{module_name} has no object {obj}") from None


@cli.command(help="Generate OpenAPI documentation from app object")
def docs(
    app: str = typer.Argument(..., help="FastAPI application object"),
    out: Path = typer.Option("./openapi.json", help="Output file path"),
    format: str = typer.Option(
        "json", help="Output format. Valid options are 'yaml' and 'json'(default)"
    ),
):
    app_obj = import_from_string(app)
    if not isinstance(app_obj, FastAPI):
        raise ValueError(f"{app} is not a FastAPI application object")
    openapi = app_obj.openapi()

    if format == "yaml":
        from yaml import safe_dump

        data = safe_dump(openapi)
    elif format == "json":
        from json import dumps

        data = dumps(openapi, indent=4)
    else:
        raise ValueError(f"Invalid format: {format}")

    with open(out, "w") as f:
        f.write(data)

    typer.secho("OK", fg="green")


@cli.callback()
def callback():
    pass
