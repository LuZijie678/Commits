import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "code" / "generation"))

from repo_identity import canonicalize_repo_identity, describe_repo_identity


def test_repo_slug_case_is_canonicalized():
    assert canonicalize_repo_identity(" ArthurSonzogni/FTXUI ") == "arthursonzogni/ftxui"


def test_https_github_url_is_canonicalized():
    assert canonicalize_repo_identity("https://github.com/ArthurSonzogni/FTXUI") == "arthursonzogni/ftxui"


def test_ssh_github_url_is_canonicalized():
    assert canonicalize_repo_identity("git@github.com:ArthurSonzogni/FTXUI.git") == "arthursonzogni/ftxui"


def test_trailing_slash_dot_git_query_and_fragment_are_removed():
    assert canonicalize_repo_identity("https://github.com/ArthurSonzogni/FTXUI.git/?tab=readme#intro") == "arthursonzogni/ftxui"


def test_unparseable_repo_uses_fallback_status():
    info = describe_repo_identity("  EXAMPLE//Internal//Repo.git  ")
    assert info["canonical"] == "example/internal/repo"
    assert info["parse_status"] == "fallback_casefold"
