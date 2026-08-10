"""Reading what a repository actually contains (PRD §8.2).

Hackathon write-ups are notoriously inflated — a project claims Redis, Kafka
and Kubernetes when the repo holds a Flask app and a JSON file. Judges check.
So before Haru describes a project, it reads it.

This module produces :class:`RepoFacts`: the languages, dependencies and
structure that are demonstrably present. The grounding check in
:mod:`haru.validation.grounding` then treats those as the boundary for any
claim about the project, exactly as the Brain's fact boundary works for claims
about the person.

Detection is evidence-based and deliberately conservative: a dependency is
"present" because it appears in a manifest, not because a README mentions it.
"""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: File extensions that indicate a language is actually used.
LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".jsx": "javascript",
    ".rs": "rust", ".go": "go", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".swift": "swift",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp",
    ".scala": "scala", ".ex": "elixir", ".exs": "elixir", ".clj": "clojure",
    ".hs": "haskell", ".lua": "lua", ".r": "r", ".m": "matlab",
    ".html": "html", ".css": "css", ".scss": "css", ".sql": "sql",
    ".sh": "shell", ".bash": "shell", ".ps1": "powershell",
}

#: Never walked into. Vendored code is not the author's work.
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
        "env", "dist", "build", "target", ".next", ".nuxt", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", "vendor", "site-packages", ".tox",
        "coverage", "htmlcov", ".idea", ".vscode",
    }
)

TEST_HINTS: frozenset[str] = frozenset({"test", "tests", "spec", "specs", "__tests__"})


@dataclass
class RepoFacts:
    """What a repository demonstrably contains."""

    root: Path
    name: str = ""
    languages: set[str] = field(default_factory=set)
    dependencies: set[str] = field(default_factory=set)
    manifests: set[str] = field(default_factory=set)
    readme: str = ""
    file_count: int = 0
    code_lines: int = 0
    has_tests: bool = False
    top_level: set[str] = field(default_factory=set)

    @property
    def evidence(self) -> set[str]:
        """Everything that may be claimed about this project.

        Includes the project's own name so a write-up can refer to what it is
        describing without that being treated as an unsupported claim.
        """
        names = {self.name, self.root.name} - {""}
        return self.languages | self.dependencies | names

    def supports(self, term: str) -> bool:
        from haru.validation.detect import canonical

        key = canonical(term)
        return any(canonical(item) == key for item in self.evidence)

    @property
    def primary_language(self) -> str | None:
        return next(iter(sorted(self.languages)), None) if self.languages else None

    def summary(self) -> str:
        parts = [f"{self.name or self.root.name}"]
        if self.languages:
            parts.append(f"{len(self.languages)} languages: {', '.join(sorted(self.languages))}")
        parts.append(f"{self.file_count} files, {self.code_lines:,} lines")
        if self.has_tests:
            parts.append("has tests")
        return " · ".join(parts)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _python_deps(root: Path) -> set[str]:
    found: set[str] = set()

    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(_read(pyproject))
        except tomllib.TOMLDecodeError:
            data = {}
        project = data.get("project", {})
        raw = list(project.get("dependencies", []))
        for group in (project.get("optional-dependencies") or {}).values():
            raw.extend(group)
        found.update(_bare_name(item) for item in raw)

    requirements = root / "requirements.txt"
    if requirements.exists():
        for line in _read(requirements).splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                found.add(_bare_name(line))

    return {name for name in found if name}


def _node_deps(root: Path) -> set[str]:
    manifest = root / "package.json"
    if not manifest.exists():
        return set()
    try:
        data = json.loads(_read(manifest))
    except json.JSONDecodeError:
        return set()
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        names.update((data.get(key) or {}).keys())
    return {n.split("/")[-1] for n in names}


def _bare_name(requirement: str) -> str:
    """Strip version specifiers and extras: ``uvicorn[standard]>=0.27`` → ``uvicorn``."""
    for separator in ("[", ">", "<", "=", "!", "~", ";", " "):
        requirement = requirement.split(separator)[0]
    return requirement.strip().lower()


def scan(root: Path | str, *, max_files: int = 4000) -> RepoFacts:
    """Walk a repository and record what is actually there."""
    base = Path(root)
    if not base.exists():
        raise FileNotFoundError(f"no repository at {base}")

    facts = RepoFacts(root=base, name=base.name)

    for entry in base.iterdir():
        if entry.name not in SKIP_DIRS and not entry.name.startswith("."):
            facts.top_level.add(entry.name)

    for readme in ("README.md", "readme.md", "README.rst", "README.txt", "README"):
        candidate = base / readme
        if candidate.exists():
            facts.readme = _read(candidate)
            break

    pyproject = base / "pyproject.toml"
    if pyproject.exists():
        facts.manifests.add("pyproject.toml")
        try:
            data = tomllib.loads(_read(pyproject))
            facts.name = data.get("project", {}).get("name") or facts.name
        except tomllib.TOMLDecodeError:
            pass
    if (base / "package.json").exists():
        facts.manifests.add("package.json")
    if (base / "requirements.txt").exists():
        facts.manifests.add("requirements.txt")
    for manifest in ("Cargo.toml", "go.mod", "Gemfile", "pom.xml", "build.gradle"):
        if (base / manifest).exists():
            facts.manifests.add(manifest)

    facts.dependencies |= _python_deps(base)
    facts.dependencies |= _node_deps(base)

    for path in base.rglob("*"):
        if facts.file_count >= max_files:
            break
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue

        language = LANGUAGE_BY_SUFFIX.get(path.suffix.lower())
        if language is None:
            continue

        facts.languages.add(language)
        facts.file_count += 1
        facts.code_lines += _read(path).count("\n")

        lowered = {part.lower() for part in path.parts}
        if lowered & TEST_HINTS or path.name.lower().startswith("test_"):
            facts.has_tests = True

    return facts
