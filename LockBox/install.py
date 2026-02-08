import os, sys, subprocess, shutil

APP_VERSION = "v0.3"


def main():
    print(f"[LockBox {APP_VERSION} Setup]...")
    subprocess.check_call([sys.executable, "-m", "venv", "venv"])
    pip = os.path.join("venv", "Scripts" if os.name == 'nt' else "bin", "pip")
    subprocess.check_call([pip, "install", "click", "tabulate", "pyyaml"])

    for d in ["images", "containers", "state", "logs"]:
        os.makedirs(d, exist_ok=True)
    if os.path.exists("base_images/alpine.tar.gz"):
        shutil.copy("base_images/alpine.tar.gz", "images/alpine.tar.gz")

    if os.name == 'nt':
        if os.path.exists("fix_path.bat"):
            subprocess.call("fix_path.bat", shell=True)
        with open("lbox.bat", "w", newline='\r\n') as f:
            f.write('@echo off\n')
            f.write('set "SCRIPT_DIR=%~dp0"\n')
            f.write('"%SCRIPT_DIR%venv\\Scripts\\python.exe" "%SCRIPT_DIR%src\\lbox.py" %*\n')
        with open("lbox", "w", newline='\n') as f:
            f.write('#!/bin/sh\nDIR="$(cd "$(dirname "$0")" && pwd)"\n"$DIR/venv/Scripts/python.exe" "$DIR/src/lbox.py" "$@"\n')
    else:
        with open("lbox", "w", newline='\n') as f:
            f.write('#!/bin/bash\nif [ "$EUID" -ne 0 ]; then echo "Sudo req"; exit; fi\nDIR="$(cd "$(dirname "$0")" && pwd)"\n"$DIR/venv/bin/python" "$DIR/src/lbox.py" "$@"\n')
        subprocess.call(['chmod', '+x', 'lbox'])

    print("Done. Please restart terminal.")


if __name__ == "__main__":
    main()
