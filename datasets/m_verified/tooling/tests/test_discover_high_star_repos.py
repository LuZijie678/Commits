import importlib.util
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "discover_high_star_repos.py"


def load_module():
    spec = importlib.util.spec_from_file_location("discover_high_star_repos", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class DiscoverHighStarReposTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_module()

    def test_resolve_search_queries_appends_query_file_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            query_file = Path(tmpdir) / "queries.txt"
            query_file.write_text(
                "# comment\n\nstars:1000..2000 fork:false archived:false language:Elixir\n"
                "stars:1000..2000 fork:false archived:false topic:compiler\n",
                encoding="utf-8",
            )

            queries = self.module.resolve_search_queries(query_file)

        self.assertEqual(queries[: len(self.module.SEARCH_QUERIES)], self.module.SEARCH_QUERIES)
        self.assertEqual(
            queries[-2:],
            [
                "stars:1000..2000 fork:false archived:false language:Elixir",
                "stars:1000..2000 fork:false archived:false topic:compiler",
            ],
        )

    def test_load_extra_target_rows_skips_excluded_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            targets_file = Path(tmpdir) / "targets.txt"
            targets_file.write_text(
                "owner/kept\nowner/excluded\nOWNER/KEPT\n",
                encoding="utf-8",
            )

            rows = self.module.load_extra_target_rows(
                targets_file,
                excluded={"owner/excluded"},
                existing={"owner/kept"},
            )

        self.assertEqual(rows, [])

    def test_load_extra_target_rows_builds_curated_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            targets_file = Path(tmpdir) / "targets.txt"
            targets_file.write_text("owner/new-one\nowner/new-two\n", encoding="utf-8")

            rows = self.module.load_extra_target_rows(
                targets_file,
                excluded=set(),
                existing={"owner/already"},
            )

        self.assertEqual([row["repo"] for row in rows], ["owner/new-one", "owner/new-two"])
        self.assertTrue(all(row["source"] == "extra_targets_file" for row in rows))
        self.assertTrue(all(row["query"] == "" for row in rows))

    def test_search_repos_retries_transient_network_errors(self) -> None:
        attempts = 0

        def fake_request_json(url: str, token: str, timeout: int):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise urllib.error.URLError("Connection refused")
            return {
                "items": [
                    {
                        "full_name": "owner/repo",
                        "stargazers_count": 123,
                        "language": "Python",
                    }
                ]
            }, {"X-RateLimit-Remaining": "42"}

        with mock.patch.object(self.module, "request_json", side_effect=fake_request_json):
            with mock.patch.object(self.module.time, "sleep"):
                items, headers, error, used_attempts = self.module.search_repos(
                    "stars:>10",
                    per_page=10,
                    page=1,
                    token="",
                    timeout=5,
                    attempts=3,
                    retry_sleep_sec=0.1,
                )

        self.assertEqual(used_attempts, 3)
        self.assertEqual(attempts, 3)
        self.assertEqual(error, "")
        self.assertEqual(headers.get("X-RateLimit-Remaining"), "42")
        self.assertEqual(items[0]["full_name"], "owner/repo")

    def test_search_repos_does_not_retry_non_retryable_http_error(self) -> None:
        http_error = urllib.error.HTTPError(
            url="https://api.github.com/search/repositories?q=stars%3A%3E10",
            code=422,
            msg="Unprocessable Entity",
            hdrs=None,
            fp=None,
        )

        with mock.patch.object(self.module, "request_json", side_effect=http_error) as mocked_request:
            with mock.patch.object(self.module.time, "sleep") as mocked_sleep:
                items, headers, error, used_attempts = self.module.search_repos(
                    "stars:>10",
                    per_page=10,
                    page=1,
                    token="",
                    timeout=5,
                    attempts=4,
                    retry_sleep_sec=0.1,
                )

        self.assertEqual(items, [])
        self.assertEqual(headers, {})
        self.assertEqual(used_attempts, 1)
        self.assertIn("HTTPError", error)
        mocked_request.assert_called_once()
        mocked_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
