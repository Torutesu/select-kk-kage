"""Prompt templates (Jinja2)."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


_PROMPTS_DIR = Path(__file__).parent
_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
)


def render(template_name: str, **context: object) -> str:
    """prompts/<template_name> を Jinja2 で render する。"""
    tmpl = _env.get_template(template_name)
    return tmpl.render(**context)


def list_prompts() -> list[str]:
    return sorted(p.name for p in _PROMPTS_DIR.glob("*.md.j2"))
