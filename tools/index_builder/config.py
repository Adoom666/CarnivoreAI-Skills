"""catalog.yml: the handful of settings the build job is allowed to read.

WHY A FILE AND NOT ENVIRONMENT VARIABLES. Every value here changes what
gets PUBLISHED, so every value belongs in the diff of a reviewed commit
under CODEOWNERS rather than in a repository setting one account can change
without a pull request. The variables the workflow does read from the
repository settings are the ones that name WHERE things go (the AWS role,
the region, the Amplify app), never what goes in them.

ABSENT IS NOT A DEFAULT for the one value that cannot be guessed. A missing
``min_serial`` is an error, because the serial floor is a rollback control
and a zero invented here would silently lower it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

#: What the file is called, at the repository root.
CONFIG_FILENAME = "catalog.yml"


@dataclass(frozen=True)
class CatalogConfig:
    """Everything catalog.yml carries, as one frozen value.

    - ``repo``: the ``owner/repo`` slug every release statement signs.
      It lives here rather than in an environment variable because it is
      part of signed bytes: read from the environment, a fork's build
      would mint statements that verify for a repository nobody publishes.
    - ``min_serial``: the floor for the very first deploy, when no live
      index exists to count from. Never used to lower a live serial.
    - ``staleness_days``: how old ``generated_at`` may be before the app
      shows the index as degraded. Carried here so the two sides can be
      compared by a human; the app holds its own copy.
    - ``review_model``: the OpenRouter model id the review step calls.
    - ``review_max_chars``: how much skill text is sent per version.
    """

    repo: str
    min_serial: int
    staleness_days: int
    review_model: str
    review_max_chars: int


def load_config(repo_root: Path) -> CatalogConfig:
    """Read and validate catalog.yml.

    Description: parses the file with a SAFE loader, requires every key to
      be present, and holds each one to its type. A key that is missing,
      empty or the wrong type raises: this file decides what is published
      and a quietly defaulted value here would be a published mistake.
    Inputs: repo_root (Path) - the repository root holding catalog.yml.
    Output: CatalogConfig.
    Raises: FileNotFoundError when the file is absent; ValueError when a
      key is missing or malformed.
    Example: load_config(Path(".")).repo -> "Adoom666/CarnivoreAI-Skills"
    """
    path = repo_root / CONFIG_FILENAME
    if not path.is_file():
        raise FileNotFoundError(f"{CONFIG_FILENAME} is missing at {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{CONFIG_FILENAME} must be a mapping")

    def integer(key: str, minimum: int) -> int:
        value = raw.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{CONFIG_FILENAME}: {key} must be an integer")
        if value < minimum:
            raise ValueError(f"{CONFIG_FILENAME}: {key} must be at least {minimum}")
        return value

    slug = raw.get("repo")
    if not isinstance(slug, str) or slug.count("/") != 1 or not all(slug.split("/")):
        raise ValueError(f"{CONFIG_FILENAME}: repo must read owner/name")

    model = raw.get("review_model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(f"{CONFIG_FILENAME}: review_model must be a non empty string")

    return CatalogConfig(
        repo=slug.strip(),
        min_serial=integer("min_serial", 0),
        staleness_days=integer("staleness_days", 1),
        review_model=model.strip(),
        review_max_chars=integer("review_max_chars", 1000),
    )
