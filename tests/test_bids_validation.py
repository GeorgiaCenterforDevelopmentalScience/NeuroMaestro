import json

from neuromaestro.pipeline.utils.bids_validation import run_bids_validation


def _dataset(root, with_description=True):
    anat = root / "sub-01" / "anat"
    anat.mkdir(parents=True)
    (anat / "sub-01_T1w.nii.gz").touch()
    if with_description:
        (root / "dataset_description.json").write_text(json.dumps({"Name": "t", "BIDSVersion": "1.8.0"}))
    return root


class TestRunBidsValidation:

    def test_valid_dataset_passes(self, tmp_path, capsys):
        run_bids_validation(str(_dataset(tmp_path / "bids")))
        assert capsys.readouterr().out.splitlines() == ["Running BIDS validation...", "BIDS validation passed."]

    def test_invalid_dataset_warns_instead_of_raising(self, tmp_path, capsys):
        run_bids_validation(str(_dataset(tmp_path / "bids", with_description=False)))
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "Running BIDS validation..."
        assert lines[1].startswith("Warning: BIDS validation error: 'dataset_description.json' is missing")
        assert "BIDS validation passed." not in lines

    def test_index_is_cached_in_work_dir(self, tmp_path):
        work = tmp_path / "work"
        work.mkdir()
        run_bids_validation(str(_dataset(tmp_path / "bids")), str(work))
        assert (work / ".bids_cache.db" / "layout_index.sqlite").is_file()

    def test_no_work_dir_leaves_nothing_behind(self, tmp_path):
        ds = _dataset(tmp_path / "bids")
        before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
        run_bids_validation(str(ds))
        assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before
