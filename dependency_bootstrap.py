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
    pip_cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
    ]
    # Use --user if not in a virtual environment to prevent permission errors
    if sys.prefix == sys.base_prefix:
        pip_cmd.append("--user")
    pip_cmd.extend(["-r", requirements_path])

    result = subprocess.run(
        pip_cmd,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "KookAI could not install the Python packages in requirements.txt. "
            "Check the error above and verify that pip and internet access are available."
        )


def check_video_binaries() -> dict[str, bool]:
    """Check availability of system CLI tools required for video processing."""
    import shutil
    import sys
    import os
    import glob

    # Auto-add WinGet FFmpeg path if installed on Windows
    if os.name == "nt" and shutil.which("ffmpeg") is None:
        winget_pkg_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
        ffmpeg_bins = glob.glob(os.path.join(winget_pkg_dir, "**", "ffmpeg.exe"), recursive=True)
        if ffmpeg_bins:
            bin_dir = os.path.dirname(ffmpeg_bins[0])
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")

    ytdlp_present = shutil.which("yt-dlp") is not None
    if not ytdlp_present:
        try:
            import yt_dlp
            ytdlp_present = True
        except ImportError:
            ytdlp_present = False

    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "yt-dlp": ytdlp_present,
    }


def ensure_video_binaries_warning() -> None:
    """Check and auto-install missing video tools (ffmpeg, yt-dlp) if available."""
    import shutil
    import sys
    import platform
    
    binaries = check_video_binaries()
    missing = [b for b, present in binaries.items() if not present]
    if not missing:
        return

    # Auto-attempt ffmpeg installation if missing
    if "ffmpeg" in missing or "ffprobe" in missing:
        print("FFmpeg is missing for video processing. Attempting automatic installation...", flush=True)
        try:
            if platform.system() == "Windows" and shutil.which("winget"):
                print("Installing FFmpeg via winget...", flush=True)
                subprocess.run(
                    ["winget", "install", "Gyan.FFmpeg", "--accept-package-agreements", "--accept-source-agreements", "--silent"],
                    check=False,
                )
            elif platform.system() == "Darwin" and shutil.which("brew"):
                print("Installing FFmpeg via brew...", flush=True)
                subprocess.run(["brew", "install", "ffmpeg"], check=False)
        except Exception as e:
            print(f"Auto-install warning: {e}", flush=True)

    # Re-check status
    binaries = check_video_binaries()
    still_missing = [b for b, present in binaries.items() if not present]
    if still_missing:
        print(
            f"Note: Some video processing tools are missing: {', '.join(still_missing)}. "
            "Video URL/file analysis feature will be limited until installed "
            "(macOS: brew install ffmpeg yt-dlp | Windows: winget install Gyan.FFmpeg yt-dlp.yt-dlp).",
            flush=True,
        )
    else:
        print("Video processing tools (ffmpeg, yt-dlp) are ready!", flush=True)

