"""Build a double-clickable app for the current OS.

    macOS:   python build_app.py   ->  dist/Paper to Audio.app
    Windows: python build_app.py   ->  dist/Paper to Audio.exe

PyInstaller can't cross-compile, so run this once on each platform you want to support.
"""

import subprocess
import sys

NAME = "Paper to Audio"


def main():
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "-r", "requirements.txt", "pyinstaller"])
    args = [
        sys.executable, "-m", "PyInstaller", "paper_to_audio.py",
        "--name", NAME, "--windowed", "--noconfirm", "--clean",
        "--collect-all", "edge_tts", "--collect-data", "certifi",
    ]
    if sys.platform == "darwin":
        args += ["--osx-bundle-identifier", "org.paper2audio.app"]
    else:
        args += ["--onefile"]
    subprocess.check_call(args)
    print(f"\nBuilt: dist/{NAME}{'.app' if sys.platform == 'darwin' else '.exe' if sys.platform == 'win32' else ''}")


if __name__ == "__main__":
    main()
