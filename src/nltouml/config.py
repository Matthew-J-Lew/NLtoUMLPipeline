from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    templates_dir: Path


def repo_root() -> Path:
    # repo_root/src/nltouml/config.py -> repo_root
    return Path(__file__).resolve().parents[2]


def default_templates_dir() -> Path:
    return repo_root() / "templates"


def load_settings(templates_dir: str | None = None) -> Settings:
    # dotenv is loaded in CLI.
    key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_MODEL", "gpt-5")
    tdir = Path(templates_dir) if templates_dir else default_templates_dir()
    return Settings(openai_api_key=key, openai_model=model, templates_dir=tdir)
