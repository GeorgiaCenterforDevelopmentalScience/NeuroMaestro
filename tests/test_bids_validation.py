import gzip
import json
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from neuromaestro.pipeline.utils import bids_validation
from neuromaestro.pipeline.utils.bids_validation import run_bids_validation

RUN = "neuromaestro.pipeline.utils.bids_validation.subprocess.run"
FIND = "neuromaestro.pipeline.utils.bids_validation._find_validator"
EXE = "/venv/bin/bids-validator-deno"


def _issue(severity, code, location=None, **extra):
    return {"severity": severity, "code": code, "location": location, **extra}


def _completed(issues=(), stdout=None, stderr="", returncode=0):
    out = json.dumps({"issues": {"issues": list(issues)}, "summary": {}}) if stdout is None else stdout
    return subprocess.CompletedProcess([EXE], returncode, stdout=out, stderr=stderr)


def _run(capsys, completed=None, side_effect=None):
    with patch(FIND, return_value=EXE), patch(RUN, return_value=completed, side_effect=side_effect) as run:
        run_bids_validation("/data/bids")
    return capsys.readouterr().out.splitlines(), run


class TestSummary:

    def test_errors_by_code_with_a_few_places_each(self, capsys):
        issues = [_issue("error", "NOT_INCLUDED", f"/sub-0{i}/junk.txt") for i in range(1, 6)]
        # one file can raise the same code more than once
        issues += [_issue("error", "EMPTY_FILE", "/sub-01/anat/a.nii.gz")] * 2
        issues += [_issue("warning", "NIFTI_UNIT", "/x")] * 3 + [_issue("warning", "README_FILE_SMALL", "/README")]
        lines, _ = _run(capsys, _completed(issues, returncode=16))
        assert lines == [
            "Running BIDS validation...",
            "BIDS validation: 7 error(s), 4 warning(s)",
            "  ERROR NOT_INCLUDED (5): /sub-01/junk.txt, /sub-02/junk.txt, /sub-03/junk.txt, ...",
            "  ERROR EMPTY_FILE (2): /sub-01/anat/a.nii.gz",
            "  warnings: NIFTI_UNIT 3, README_FILE_SMALL 1",
        ]

    def test_exactly_the_limit_of_places_has_no_ellipsis(self, capsys):
        issues = [_issue("error", "NOT_INCLUDED", f"/{i}.txt") for i in range(3)]
        lines, _ = _run(capsys, _completed(issues, returncode=16))
        assert lines[2] == "  ERROR NOT_INCLUDED (3): /0.txt, /1.txt, /2.txt"

    def test_issue_without_a_location_names_what_it_affects(self, capsys):
        issues = [_issue("error", "MISSING_DATASET_DESCRIPTION", affects=["/dataset_description.json"])]
        lines, _ = _run(capsys, _completed(issues, returncode=16))
        assert lines[1:] == [
            "BIDS validation: 1 error(s), 0 warning(s)",
            "  ERROR MISSING_DATASET_DESCRIPTION (1): /dataset_description.json",
        ]

    def test_warnings_alone_pass(self, capsys):
        lines, _ = _run(capsys, _completed([_issue("warning", "NIFTI_UNIT", "/x")] * 2))
        assert lines == ["Running BIDS validation...", "BIDS validation passed (2 warning(s))."]

    def test_clean_dataset_passes(self, capsys):
        lines, _ = _run(capsys, _completed())
        assert lines == ["Running BIDS validation...", "BIDS validation passed (0 warning(s))."]


class TestHowTheValidatorRuns:

    def test_command_timeout_and_cache_location(self, capsys):
        seen = {}

        def fake(cmd, **kwargs):
            seen.update(cmd=cmd, kwargs=kwargs, cache_existed=Path(kwargs["env"]["DENO_DIR"]).is_dir())
            return _completed()

        _run(capsys, side_effect=fake)
        assert seen["cmd"] == [EXE, "--json", "/data/bids"]
        kwargs = seen["kwargs"]
        assert (kwargs["timeout"], kwargs["capture_output"], kwargs["encoding"]) == (600, True, "utf-8")
        assert kwargs["env"]["DENO_NO_UPDATE_CHECK"] == "1"
        # a fresh local directory for the run, removed afterwards
        assert seen["cache_existed"]
        assert not Path(kwargs["env"]["DENO_DIR"]).exists()

    def test_the_rest_of_the_environment_is_passed_through(self, capsys, monkeypatch):
        monkeypatch.setenv("NM_PROBE", "kept")
        _, run = _run(capsys, _completed())
        assert run.call_args.kwargs["env"]["NM_PROBE"] == "kept"

    def test_found_next_to_the_interpreter_without_path(self, tmp_path, monkeypatch):
        windows = sys.platform == "win32"
        exe = tmp_path / ("bids-validator-deno.exe" if windows else "bids-validator-deno")
        exe.write_text("")
        exe.chmod(0o755)
        monkeypatch.setattr(sys, "executable", str(tmp_path / ("python.exe" if windows else "python")))
        monkeypatch.setenv("PATH", "")
        assert Path(bids_validation._find_validator()) == exe

    def test_missing_validator_skips_with_a_warning(self, capsys):
        with patch(FIND, return_value=None), patch(RUN) as run:
            run_bids_validation("/data/bids")
        assert capsys.readouterr().out.splitlines() == [
            "Warning: bids-validator-deno not found, BIDS validation skipped."]
        run.assert_not_called()


class TestFailuresOnlyWarn:

    def test_timeout(self, capsys):
        lines, _ = _run(capsys, side_effect=subprocess.TimeoutExpired(EXE, 600))
        assert lines[1:] == ["Warning: BIDS validation timed out after 600 s, skipped."]

    def test_cannot_start(self, capsys):
        lines, _ = _run(capsys, side_effect=PermissionError("denied"))
        assert lines[1:] == ["Warning: BIDS validation could not start: denied"]

    def test_virtual_memory_limit_is_named(self, capsys):
        # what V8 prints when ulimit -v is too low, ending in SIGTRAP
        crash = _completed(stdout="", stderr="\n#\n# Fatal process out of memory: Oilpan: CagedHeap reservation.\n",
                           returncode=-5)
        lines, _ = _run(capsys, crash)
        assert lines[1:] == [
            "Warning: BIDS validation gave no result (exit code -5), skipped.",
            "  The validator could not reserve virtual memory. A ulimit -v below about 33 GB prevents it from starting.",
        ]

    def test_other_failures_show_the_first_stderr_line(self, capsys):
        lines, _ = _run(capsys, _completed(stdout="not json", stderr="\nerror: bad flag\nmore\n", returncode=2))
        assert lines[1:] == ["Warning: BIDS validation gave no result (exit code 2), skipped.", "  error: bad flag"]

    def test_unexpected_json_shape(self, capsys):
        lines, _ = _run(capsys, _completed(stdout=json.dumps({"summary": {}}), returncode=0))
        assert lines[1:] == ["Warning: BIDS validation gave no result (exit code 0), skipped."]


# ---------------------------------------------------------------------------
# The real validator on hand-built datasets
# ---------------------------------------------------------------------------

NIFTI1_HEADER = "<i10s18sihcb8h3f4h8f3fhbb4f2i80s24s2h6f12f16s4s"


def _nifti(path):
    # smallest file the validator reads as NIfTI-1: 2x2x2 int16, mm and seconds
    header = struct.pack(
        NIFTI1_HEADER,
        348, b"", b"", 0, 0, b"r", 0,
        3, 2, 2, 2, 1, 1, 1, 1,
        0.0, 0.0, 0.0,
        0, 4, 16, 0,
        1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0,
        352.0, 1.0, 0.0,
        0, 0, 10,
        0.0, 0.0, 0.0, 0.0,
        0, 0,
        b"", b"",
        1, 1,
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
        1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
        b"", b"n+1\x00",
    )
    with gzip.open(path, "wb") as f:
        f.write(header + b"\x00" * 4 + b"\x00" * 16)


def _dataset(root, description=True, junk=False):
    anat = root / "sub-01" / "anat"
    anat.mkdir(parents=True)
    _nifti(anat / "sub-01_T1w.nii.gz")
    (root / "README").write_text("probe dataset\n")
    if description:
        (root / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.10.0"}))
    if junk:
        (anat / "whatever.nii.gz").write_bytes(b"")
    return str(root)


real_validator = pytest.mark.skipif(bids_validation._find_validator() is None,
                                    reason="bids-validator-deno is not installed")


@real_validator
class TestRealValidator:

    def test_valid_dataset_passes(self, tmp_path, capsys):
        run_bids_validation(_dataset(tmp_path / "bids"))
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "Running BIDS validation..."
        assert lines[1].startswith("BIDS validation passed (")
        assert len(lines) == 2

    def test_non_bids_file_is_reported(self, tmp_path, capsys):
        run_bids_validation(_dataset(tmp_path / "bids", junk=True))
        lines = capsys.readouterr().out.splitlines()
        assert lines[1].startswith("BIDS validation: ")
        assert "  ERROR NOT_INCLUDED (1): /sub-01/anat/whatever.nii.gz" in lines

    def test_missing_description_is_reported(self, tmp_path, capsys):
        run_bids_validation(_dataset(tmp_path / "bids", description=False))
        lines = capsys.readouterr().out.splitlines()
        assert "  ERROR MISSING_DATASET_DESCRIPTION (1): /dataset_description.json" in lines
