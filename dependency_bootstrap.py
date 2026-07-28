"""Small stdlib-only bootstrap for Python requirements.

This runs before FastAPI and the other third-party modules are imported, which
lets ``python main.py`` repair a fresh environment on its first launch.
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys


def _requirements_satisfied(requirements_path: str) -> bool:
    try:
        from packaging.requirements import Requirement
    except ImportError:
        try:
            from pip._vendor.packaging.requirements import Requirement
        except ImportError:
            return False

    try:
        with open(requirements_path, "r", encoding="utf-8") as requirements_file:
            lines = requirements_file.readlines()
    except OSError:
        return False

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            requirement = Requirement(line)
            installed_version = importlib.metadata.version(requirement.name)
        except (ValueError, importlib.metadata.PackageNotFoundError):
            return False
        if requirement.specifier and installed_version not in requirement.specifier:
            return False
    return True


def ensure_python_requirements(project_directory: str) -> None:
    if os.environ.get(
        "KOOKAI_SKIP_PYTHON_BOOTSTRAP",
        "",
    ).lower() in {"1", "true", "yes", "on"}:
        return

    requirements_path = os.path.join(project_directory, "requirements.txt")
    if _requirements_satisfied(requirements_path):
        return

    print("Installing missing Python requirements for KookAI…", flush=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            requirements_path,
        ],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "KookAI could not install the Python packages in requirements.txt. "
            "Check the error above and verify that pip and internet access are available."
        )
