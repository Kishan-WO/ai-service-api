"""Prompt registry: prompts are files, prompts/<name>/<version>.md, loaded by name and version."""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

_env = Environment(undefined=StrictUndefined)
_NAME = re.compile(r"[a-z][a-z0-9_]*")
_VERSION = re.compile(r"v[0-9]+")

class PromptNotFoundError(Exception):
    """The prompt name or version is not valid, or there is no such prompt file."""

@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    template: str

    def render(self, **variables: object) -> str:
        return _env.from_string(self.template).render(**variables)

@lru_cache
def get_prompt(name: str, version: str) -> Prompt:
    if not _NAME.fullmatch(name) or not _VERSION.fullmatch(version):
        raise PromptNotFoundError(f"invalid prompt reference {name!r} version {version!r}")
    path = PROMPTS_DIR / name / f"{version}.md"
    if not path.is_file():
        raise PromptNotFoundError(f"no prompt {name}@{version} (looked for {path})")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    return Prompt(name, version, text)