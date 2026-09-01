import shutil
from pathlib import Path


def init_project_templates(config_dir: Path) -> list[str]:
    """Copy bundled config and script templates into config_dir.

    Script templates are placed at config_dir.parent/scripts/ to mirror
    the expected study layout: study_root/{config,scripts}/.

    Returns a list of copied item names for caller reporting.
    """
    pkg_root = Path(__file__).parent.parent.parent
    src_config = pkg_root / "config"

    config_dir.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []

    for fname in ("config.yaml", "hpc_config.yaml"):
        src = src_config / fname
        if src.exists():
            shutil.copy2(src, config_dir / fname)
            copied.append(fname)

    for subdir in ("project_config", "results_check"):
        src = src_config / subdir
        if src.exists():
            shutil.copytree(src, config_dir / subdir, dirs_exist_ok=True)
            copied.append(f"{subdir}/")

    template_scripts = pkg_root / "scripts" / "template"
    if template_scripts.exists():
        scripts_out = config_dir.parent / "scripts"
        scripts_out.mkdir(parents=True, exist_ok=True)
        shutil.copytree(template_scripts, scripts_out, dirs_exist_ok=True)
        copied.append("scripts/")

    return copied
