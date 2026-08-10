"""
test_output_checker.py

Tests for pipeline/utils/output_checker.py

Covers:
1. required_files check  — PASS / FAIL (missing) / FAIL (too small)
2. count_check           — PASS / FAIL (too few) / FAIL (too many)
3. get_pending_subjects  — returns only incomplete subjects
4. get_completed_subjects
5. warn_missing_configs  — tasks without config entries
6. check_all             — empty result when no config matches
"""

import pytest
import yaml
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_checks_yaml(tmp_path: Path, content: dict) -> str:
    p = tmp_path / "checks.yaml"
    with open(p, "w") as f:
        yaml.dump(content, f)
    return str(p)


def make_checker(tmp_path, config_content, work_dir=None):
    from neuro_pipeline.pipeline.utils.output_checker import OutputChecker
    cfg_path = write_checks_yaml(tmp_path, config_content)
    return OutputChecker(
        config_path=cfg_path,
        work_dir=str(work_dir or tmp_path),
        prefix="sub-",
        session="01",
    )


# ---------------------------------------------------------------------------
# 1. required_files
# ---------------------------------------------------------------------------

class TestRequiredFilesCheck:

    def test_pass_when_file_exists(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        (out / "sub-001.html").write_text("x")

        checker = make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": [{"pattern": "sub-{subject}.html"}],
            }
        }, work_dir=tmp_path)

        rows = checker.check_subject("mytask", "001")
        assert len(rows) == 1
        assert rows[0]["status"] == "PASS"

    def test_fail_when_file_missing(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()

        checker = make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": [{"pattern": "sub-{subject}.html"}],
            }
        }, work_dir=tmp_path)

        rows = checker.check_subject("mytask", "001")
        assert rows[0]["status"].startswith("FAIL")

    def test_fail_when_file_too_small(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        (out / "sub-001.html").write_bytes(b"x" * 10)  # 10 bytes, well under 1 KB

        checker = make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": [{"pattern": "sub-{subject}.html", "min_size_kb": 1}],
            }
        }, work_dir=tmp_path)

        rows = checker.check_subject("mytask", "001")
        assert "too small" in rows[0]["status"]

    def test_pass_when_file_meets_min_size(self, tmp_path):
        out = tmp_path / "output"
        out.mkdir()
        (out / "sub-001.html").write_bytes(b"x" * 2048)  # 2 KB

        checker = make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": [{"pattern": "sub-{subject}.html", "min_size_kb": 1}],
            }
        }, work_dir=tmp_path)

        rows = checker.check_subject("mytask", "001")
        assert rows[0]["status"] == "PASS"

    def test_plain_string_entry_accepted(self, tmp_path):
        """required_files entry can be a plain string (no min_size_kb)."""
        out = tmp_path / "output"
        out.mkdir()
        (out / "sub-001.html").write_text("ok")

        checker = make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": ["sub-{subject}.html"],
            }
        }, work_dir=tmp_path)

        rows = checker.check_subject("mytask", "001")
        assert rows[0]["status"] == "PASS"


# ---------------------------------------------------------------------------
# 2. count_check
# ---------------------------------------------------------------------------

class TestCountCheck:

    def _make_files(self, directory: Path, names):
        for n in names:
            (directory / n).write_text("x")

    def test_pass_within_tolerance(self, tmp_path):
        out = tmp_path / "bids"
        out.mkdir()
        self._make_files(out, ["anat1.nii.gz", "anat2.nii.gz"])

        checker = make_checker(tmp_path, {
            "recon": {
                "output_path": str(out),
                "count_check": {
                    "anat": {"pattern": "*.nii.gz", "expected_count": 2, "tolerance": 1}
                },
            }
        })
        rows = checker.check_subject("recon", "001")
        assert rows[0]["status"] == "PASS"

    def test_fail_too_few(self, tmp_path):
        out = tmp_path / "bids"
        out.mkdir()

        checker = make_checker(tmp_path, {
            "recon": {
                "output_path": str(out),
                "count_check": {
                    "anat": {"pattern": "*.nii.gz", "expected_count": 2, "tolerance": 0}
                },
            }
        })
        rows = checker.check_subject("recon", "001")
        assert "too few" in rows[0]["status"]

    def test_fail_too_many(self, tmp_path):
        out = tmp_path / "bids"
        out.mkdir()
        self._make_files(out, [f"file{i}.nii.gz" for i in range(5)])

        checker = make_checker(tmp_path, {
            "recon": {
                "output_path": str(out),
                "count_check": {
                    "anat": {"pattern": "*.nii.gz", "expected_count": 2, "tolerance": 0}
                },
            }
        })
        rows = checker.check_subject("recon", "001")
        assert "too many" in rows[0]["status"]

    def test_missing_output_directory_fails_rather_than_raising(self, tmp_path):
        checker = make_checker(tmp_path, {
            "recon": {
                "output_path": str(tmp_path / "never_created"),
                "count_check": {
                    "anat": {"pattern": "*.nii.gz", "expected_count": 1, "tolerance": 0}
                },
            }
        })
        rows = checker.check_subject("recon", "001")
        assert rows[0]["status"].startswith("FAIL")


# ---------------------------------------------------------------------------
# 2b. group-scope tasks
#
# DAGExecutor branches on is_group() during resume, and test_resume.py mocks
# both methods out, so this is the only place the real behaviour is exercised.
# ---------------------------------------------------------------------------

class TestGroupScope:

    def _config(self, out, scope=None):
        task = {
            "output_path": str(out),
            "required_files": ["group_report.html"],
        }
        if scope is not None:
            task["scope"] = scope
        return {"mriqc_post": task}

    def test_scope_group_is_recognised(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        checker = make_checker(tmp_path, self._config(out, scope="group"))
        assert checker.is_group("mriqc_post") is True

    def test_task_without_scope_is_not_group(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        checker = make_checker(tmp_path, self._config(out))
        assert checker.is_group("mriqc_post") is False

    def test_unconfigured_task_is_not_group(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        checker = make_checker(tmp_path, self._config(out, scope="group"))
        assert checker.is_group("ghost_task") is False

    def test_check_group_passes_when_the_file_exists(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "group_report.html").write_text("ok")
        checker = make_checker(tmp_path, self._config(out, scope="group"))
        rows = checker.check_group("mriqc_post")
        assert len(rows) == 1
        assert rows[0]["status"] == "PASS"

    def test_check_group_fails_when_the_file_is_missing(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        checker = make_checker(tmp_path, self._config(out, scope="group"))
        assert checker.check_group("mriqc_post")[0]["status"].startswith("FAIL")

    def test_check_group_labels_the_subject_as_group(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "group_report.html").write_text("ok")
        checker = make_checker(tmp_path, self._config(out, scope="group"))
        assert checker.check_group("mriqc_post")[0]["subject"] == "GROUP"

    def test_check_all_evaluates_a_group_task_once(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "group_report.html").write_text("ok")
        checker = make_checker(tmp_path, self._config(out, scope="group"))
        df = checker.check_all(["mriqc_post"], ["001", "002", "003"])
        # one row for the whole task, not one per subject
        assert len(df) == 1
        assert set(df["subject"]) == {"GROUP"}

    def test_check_all_still_fans_out_for_a_non_group_task(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "group_report.html").write_text("ok")
        checker = make_checker(tmp_path, self._config(out))
        df = checker.check_all(["mriqc_post"], ["001", "002", "003"])
        assert len(df) == 3
        assert set(df["subject"]) == {"001", "002", "003"}


# ---------------------------------------------------------------------------
# 3 & 4. get_pending / get_completed
# ---------------------------------------------------------------------------

class TestPendingCompleted:

    def _checker_with_subjects(self, tmp_path, passing_subjects):
        out = tmp_path / "output"
        out.mkdir()
        for sub in passing_subjects:
            (out / f"sub-{sub}.html").write_text("ok")

        return make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": ["sub-{subject}.html"],
            }
        })

    def test_completed_subjects_returned(self, tmp_path):
        checker = self._checker_with_subjects(tmp_path, ["001", "002"])
        completed = checker.get_completed_subjects("mytask", ["001", "002", "003"])
        assert "001" in completed
        assert "002" in completed
        assert "003" not in completed

    def test_pending_is_complement_of_completed(self, tmp_path):
        checker = self._checker_with_subjects(tmp_path, ["001"])
        pending = checker.get_pending_subjects("mytask", ["001", "002", "003"])
        assert "001" not in pending
        assert "002" in pending
        assert "003" in pending

    def test_all_pending_when_no_outputs(self, tmp_path):
        checker = self._checker_with_subjects(tmp_path, [])
        pending = checker.get_pending_subjects("mytask", ["001", "002"])
        assert pending == ["001", "002"]

    def test_unconfigured_task_returns_empty_completed(self, tmp_path):
        checker = self._checker_with_subjects(tmp_path, ["001"])
        completed = checker.get_completed_subjects("unknown_task", ["001"])
        assert completed == []


# ---------------------------------------------------------------------------
# 5. warn_missing_configs
# ---------------------------------------------------------------------------

class TestWarnMissingConfigs:

    def test_warns_for_unconfigured_tasks(self, tmp_path):
        checker = make_checker(tmp_path, {"recon": {
            "output_path": str(tmp_path),
            "required_files": [],
        }})
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            missing = checker.warn_missing_configs(["recon", "ghost_task"])
        assert "ghost_task" in missing
        assert any("ghost_task" in str(warning.message) for warning in w)

    def test_no_warning_when_all_configured(self, tmp_path):
        checker = make_checker(tmp_path, {"mytask": {
            "output_path": str(tmp_path),
            "required_files": [],
        }})
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            missing = checker.warn_missing_configs(["mytask"])
        assert missing == []
        assert not w


# ---------------------------------------------------------------------------
# session="*" wildcard (used by check-outputs when --session is omitted)
# ---------------------------------------------------------------------------

class TestSessionWildcard:

    def test_wildcard_matches_any_session(self, tmp_path):
        """session='*' glob should find files across ses-01 and ses-02."""
        from neuro_pipeline.pipeline.utils.output_checker import OutputChecker

        for ses in ("01", "02"):
            d = tmp_path / f"ses-{ses}"
            d.mkdir()
            (d / "sub-001_bold.nii.gz").write_text("x")

        cfg_path = tmp_path / "checks.yaml"
        import yaml
        cfg_path.write_text(yaml.dump({
            "mytask": {
                "output_path": str(tmp_path / "ses-{session}"),
                "required_files": ["sub-{subject}_bold.nii.gz"],
            }
        }))

        checker = OutputChecker(
            config_path=str(cfg_path),
            work_dir=str(tmp_path),
            prefix="sub-",
            session="*",
        )
        rows = checker.check_subject("mytask", "001")
        assert len(rows) == 1
        assert rows[0]["status"] == "PASS"
        assert rows[0]["session"] == "*"

    def test_wildcard_fails_when_no_files(self, tmp_path):
        """session='*' still reports FAIL when no files match any session."""
        from neuro_pipeline.pipeline.utils.output_checker import OutputChecker
        import yaml

        cfg_path = tmp_path / "checks.yaml"
        cfg_path.write_text(yaml.dump({
            "mytask": {
                "output_path": str(tmp_path / "ses-{session}"),
                "required_files": ["sub-{subject}_bold.nii.gz"],
            }
        }))

        checker = OutputChecker(
            config_path=str(cfg_path),
            work_dir=str(tmp_path),
            prefix="sub-",
            session="*",
        )
        rows = checker.check_subject("mytask", "001")
        assert rows[0]["status"].startswith("FAIL")


# ---------------------------------------------------------------------------
# 6. check_all — empty DataFrame when nothing configured
# ---------------------------------------------------------------------------

class TestCheckAll:

    def test_empty_dataframe_when_no_matching_tasks(self, tmp_path):
        checker = make_checker(tmp_path, {})
        df = checker.check_all(["recon", "rest_preprocess"], ["001", "002"])
        assert df.empty

    def test_dataframe_has_expected_columns(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        (out / "sub-001.html").write_text("x")

        checker = make_checker(tmp_path, {
            "mytask": {
                "output_path": str(out),
                "required_files": ["sub-{subject}.html"],
            }
        })
        df = checker.check_all(["mytask"], ["001"])
        assert not df.empty
        for col in ("task", "subject", "session", "check_type", "status"):
            assert col in df.columns


# ---------------------------------------------------------------------------
# run_output_checks — shared by the CLI and the GUI
# ---------------------------------------------------------------------------

class TestRunOutputChecks:
    """The CLI and the GUI both call this, so session handling and task
    resolution cannot drift apart between them.
    """

    @staticmethod
    def _setup(tmp_path, sessions_with_file):
        """Build a tree where only the listed sessions contain the file."""
        for ses in ("01", "02"):
            d = tmp_path / "BIDS" / "sub-001" / f"ses-{ses}" / "anat"
            d.mkdir(parents=True)
            if ses in sessions_with_file:
                (d / "sub-001_T1w.nii.gz").write_bytes(b"x" * 2048)

        cfg = tmp_path / "checks.yaml"
        cfg.write_text(yaml.dump({
            "recon": {
                "output_path": "{work_dir}/BIDS/{prefix}{subject}/ses-{session}/",
                "required_files": ["anat/*.nii.gz"],
            }
        }))
        return str(cfg)

    def _run(self, tmp_path, sessions, sessions_with_file=("01",), **kw):
        from neuro_pipeline.pipeline.utils.output_checker import run_output_checks
        cfg = self._setup(tmp_path, sessions_with_file)
        return run_output_checks(
            config_path=cfg, work_dir=str(tmp_path), sessions=sessions,
            subjects=["001"], prefix="sub-", **kw
        )

    def test_each_session_evaluated_separately(self, tmp_path):
        # Only ses-01 has the file; ses-02 must not be rescued by it
        df, _, _ = self._run(tmp_path, ["01", "02"])
        by_session = dict(zip(df["session"], df["status"]))
        assert by_session["01"] == "PASS"
        assert by_session["02"].startswith("FAIL")

    def test_missing_session_is_not_masked(self, tmp_path):
        df, _, _ = self._run(tmp_path, ["02"])
        assert len(df) == 1
        assert df.iloc[0]["status"].startswith("FAIL")

    def test_real_session_value_recorded(self, tmp_path):
        df, _, _ = self._run(tmp_path, ["01", "02"])
        assert set(df["session"]) == {"01", "02"}
        assert "*" not in set(df["session"])

    def test_returns_checked_task_names(self, tmp_path):
        _, checked, _ = self._run(tmp_path, ["01"])
        assert checked == ["recon"]

    def test_unknown_task_reported_as_unconfigured(self, tmp_path):
        _, checked, unconfigured = self._run(tmp_path, ["01"], tasks=["recon", "ghost"])
        assert checked == ["recon"]
        assert unconfigured == ["ghost"]

    def test_task_filter_restricts_checks(self, tmp_path):
        df, checked, _ = self._run(tmp_path, ["01"], tasks=["recon"])
        assert checked == ["recon"]
        assert set(df["task"]) == {"recon"}

    def test_empty_sessions_raises(self, tmp_path):
        with pytest.raises(ValueError, match="session"):
            self._run(tmp_path, [])

    def test_empty_subjects_raises(self, tmp_path):
        from neuro_pipeline.pipeline.utils.output_checker import run_output_checks
        cfg = self._setup(tmp_path, ("01",))
        with pytest.raises(ValueError, match="subject"):
            run_output_checks(config_path=cfg, work_dir=str(tmp_path),
                              sessions=["01"], subjects=[], prefix="sub-")

    def test_no_configured_tasks_returns_empty_frame(self, tmp_path):
        df, checked, _ = self._run(tmp_path, ["01"], tasks=["ghost"])
        assert checked == []
        assert df.empty
        assert "status" in df.columns
