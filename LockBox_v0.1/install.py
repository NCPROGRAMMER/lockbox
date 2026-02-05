import os, sys, subprocess, shutil
def main():
    print("[LockBox v0.1 Setup]...")
    subprocess.check_call([sys.executable, "-m", "venv", "venv"])
    pip = os.path.join("venv", "Scripts" if os.name=='nt' else "bin", "pip")
    subprocess.check_call([pip, "install", "click", "tabulate", "pyyaml"])
    for d in ["images", "containers", "state", "logs"]: os.makedirs(d, exist_ok=True)
    if os.path.exists("base_images/alpine.tar.gz"): shutil.copy("base_images/alpine.tar.gz", "images/alpine.tar.gz")

    cwd = os.getcwd()
    py = os.path.join(cwd, "venv", "Scripts" if os.name=='nt' else "bin", "python" + (".exe" if os.name=='nt' else ""))
    sc = os.path.join(cwd, "src", "lbox.py")

    if os.name == 'nt':
        if os.path.exists("fix_path.bat"): subprocess.call("fix_path.bat", shell=True)
        with open("lbox.bat", "w") as f: f.write(f'@"{py}" "{sc}" %*')
        with open("lbox", "w", newline='\n') as f: f.write(f'#!/bin/sh\n"{py}" "{sc}" "$@"')
    else:
        with open("lbox", "w") as f: f.write(f'#!/bin/bash\nif [ "$EUID" -ne 0 ]; then echo "Sudo req"; exit; fi\n"{py}" "{sc}" "$@"')
        subprocess.call(['chmod', '+x', 'lbox'])
    print("Done. Please restart terminal.")

if __name__=="__main__": main()
