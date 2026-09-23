from __future__ import annotations

from pathlib import PurePosixPath


LANGUAGE_BY_SUFFIX = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".m": "objective-c",
    ".mm": "objective-cpp",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".scala": "scala",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}

DOC_SUFFIXES = {".md", ".rst", ".txt", ".adoc"}
CONFIG_SUFFIXES = {".cfg", ".conf", ".ini", ".json", ".toml", ".yaml", ".yml"}
LOCKFILE_NAMES = {
    "cargo.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "poetry.lock",
    "yarn.lock",
}
BUILD_NAMES = {
    "build.gradle",
    "cmakelists.txt",
    "dockerfile",
    "makefile",
    "package.json",
    "pyproject.toml",
    "setup.py",
}


def infer_language(file_path: str) -> str | None:
    path = PurePosixPath(file_path)
    suffix = path.suffix.lower()
    return LANGUAGE_BY_SUFFIX.get(suffix)


def infer_file_role(file_path: str) -> str:
    path = PurePosixPath(file_path)
    lower_path = file_path.lower()
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}

    if name in LOCKFILE_NAMES:
        return "lockfile"
    if name in BUILD_NAMES or "cmake" in lower_path or "docker" in lower_path:
        return "build"
    if "generated" in parts or "vendor" in parts or "dist" in parts:
        return "generated"
    if "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py"):
        return "test"
    if name in {"readme.md", "changelog.md"} or path.suffix.lower() in DOC_SUFFIXES or "docs" in parts or "doc" in parts:
        return "doc"
    if (
        path.suffix.lower() in CONFIG_SUFFIXES
        or ".github" in parts
        or "config" in parts
        or "configs" in parts
        or name.startswith(".")
    ):
        return "config"
    return "source"


def role_flags(file_path: str) -> dict[str, bool]:
    role = infer_file_role(file_path)
    lower_path = file_path.lower()
    return {
        "is_test": role == "test",
        "is_doc": role == "doc",
        "is_config": role == "config" or "/config" in lower_path or "/configs" in lower_path or lower_path.endswith(".env"),
        "is_build": role == "build",
        "is_lockfile": role == "lockfile",
        "is_generated_like": role == "generated" or "/generated/" in lower_path or "/vendor/" in lower_path or "/dist/" in lower_path,
    }
