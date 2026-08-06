import importlib
import sys
from pathlib import Path
from typing import Any

import typer
from fastapi import FastAPI

cli = typer.Typer(no_args_is_help=True)


if "." not in sys.path:
    sys.path.insert(0, ".")


def import_from_string(path: str) -> Any:
    module_name, _, obj = path.partition(":")
    module = importlib.import_module(module_name)
    try:
        return getattr(module, obj)
    except AttributeError:
        msg = f"{module_name} has no object {obj}"
        raise ImportError(msg) from None


@cli.callback(help="FastAPI Views command line interface")
def main() -> None: ...


@cli.command(help="Generate OpenAPI documentation from app object")
def docs(
    app: str = typer.Argument(..., help="FastAPI application object"),
    out: Path = typer.Option("./openapi.json", help="Output file path"),
    format: str = typer.Option(
        "json",
        help="Output format. Valid options are 'yaml' and 'json'(default)",
    ),
) -> None:
    app_obj = import_from_string(app)
    if not isinstance(app_obj, FastAPI):
        msg = f"{app} is not a FastAPI application object"
        raise TypeError(msg)
    openapi = app_obj.openapi()

    if format == "yaml":
        try:
            from yaml import safe_dump
        except ImportError:
            msg = (
                "PyYAML is required for '--format yaml'. "
                "Install it with 'pip install pyyaml' (or 'uv add pyyaml')."
            )
            raise typer.BadParameter(msg, param_hint="'--format'") from None

        data = safe_dump(openapi)
    elif format == "json":
        from json import dumps

        data = dumps(openapi, indent=4)
    else:
        msg = f"Invalid format: {format}"
        raise ValueError(msg)

    with open(out, "w") as f:
        f.write(data)

    typer.secho("OK", fg="green")
