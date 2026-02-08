#!/usr/bin/env python3
import click
import os
import sys
import shutil
import tarfile
import subprocess
import uuid
import platform
import socket
import threading
import time
import json
import yaml
import hashlib
import urllib.request
import re
import shlex
from datetime import datetime
from lbox_create import register_create_commands

# ==========================================
# CONFIGURATION
# ==========================================
IS_WINDOWS = (platform.system() == 'Windows')
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALL_DIR = os.path.dirname(ROOT_DIR) 
IMAGES_DIR = os.path.join(INSTALL_DIR, "images")
CONTAINERS_DIR = os.path.join(INSTALL_DIR, "containers")
STATE_DIR = os.path.join(INSTALL_DIR, "state")
LOGS_DIR = os.path.join(INSTALL_DIR, "logs")

for d in [IMAGES_DIR, CONTAINERS_DIR, STATE_DIR, LOGS_DIR]:
    if not os.path.exists(d): os.makedirs(d)

# ==========================================
# STATE & UTILS
# ==========================================
def save_state(cid, data):
    with open(os.path.join(STATE_DIR, f"{cid}.json"), 'w') as f: json.dump(data, f, indent=4)


def iter_states():
    """Yield container states from STATE_DIR, skipping malformed files."""
    for entry in os.scandir(STATE_DIR):
        if not entry.is_file() or not entry.name.endswith('.json'):
            continue
        try:
            with open(entry.path) as f:
                yield json.load(f)
        except Exception:
            continue


def load_state(identifier):
    path = os.path.join(STATE_DIR, f"{identifier}.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None

    for data in iter_states():
        if data.get('name') == identifier:
            return data
    return None

def get_id_by_name(name):
    if not name: return None
    s = load_state(name)
    return s['id'] if s else None

def remove_state(cid):
    try:
        if os.path.exists(os.path.join(STATE_DIR, f"{cid}.json")): os.remove(os.path.join(STATE_DIR, f"{cid}.json"))
    except: pass

def run_quiet(cmd_list):
    try:
        subprocess.check_call(cmd_list, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except: return False

def check_port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('0.0.0.0', port))
        s.close()
        return True
    except OSError: return False

def calculate_file_hash(filepath):
    if not os.path.exists(filepath): return None
    hash_md5 = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_remote_header(url, header='Last-Modified'):
    try:
        req = urllib.request.Request(url, method='HEAD')
        with urllib.request.urlopen(req) as response:
            return response.headers.get(header) or response.headers.get('ETag')
    except: return None

def image_exists(tag):
    return any(
        os.path.exists(os.path.join(IMAGES_DIR, f"{tag}{ext}"))
        for ext in (".tar", ".tar.gz")
    )

def remove_image_artifacts(tag):
    removed = False
    for ext in (".tar", ".tar.gz"):
        image_path = os.path.join(IMAGES_DIR, f"{tag}{ext}")
        if os.path.exists(image_path):
            os.remove(image_path)
            removed = True
    return removed

def list_project_containers(project_name):
    prefix = f"{project_name}_"
    names = []
    for state in iter_states():
        name = state.get('name')
        if name and name.startswith(prefix):
            names.append(name)
    return names

def cleanup_container_resources(state):
    if not state:
        return

    _remove_container_service(state)

    cid = state.get('id')
    root = state.get('root')

    if IS_WINDOWS and cid:
        run_quiet(['wsl', '--terminate', cid])
        run_quiet(['wsl', '--unregister', cid])
    else:
        for mount in state.get('mounts', []):
            run_quiet(['umount', '-l', mount])
        if root:
            run_quiet(['umount', '-l', os.path.join(root, 'proc')])

    if root:
        shutil.rmtree(root, ignore_errors=True)
    if cid:
        remove_state(cid)

def spawn_internal_daemon(cid, log_handle=None):
    script = os.path.abspath(__file__)
    python_exe = sys.executable
    startupinfo = None
    creationflags = 0

    if IS_WINDOWS:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= 1
        startupinfo.wShowWindow = 0
        creationflags = 0x00000200

    proc = subprocess.Popen(
        [python_exe, script, "internal-daemon", cid],
        cwd=INSTALL_DIR,
        creationflags=creationflags,
        startupinfo=startupinfo,
        close_fds=True,
        start_new_session=True,
        stdout=log_handle if log_handle else subprocess.DEVNULL,
        stderr=subprocess.STDOUT if log_handle else subprocess.DEVNULL
    )
    return proc

def _normalize_service_name(value):
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', '-', str(value or '').strip())
    cleaned = cleaned.strip('-_.')
    return cleaned or f"lockbox-{uuid.uuid4().hex[:8]}"


def _container_service_name(state):
    if state.get('service_name'):
        return state['service_name']
    base = state.get('name') or state.get('id')
    return f"lockbox-{_normalize_service_name(base)}"


def _register_container_service(state):
    cid = state.get('id')
    if not cid:
        return False

    service_name = _container_service_name(state)
    script = os.path.abspath(__file__)
    python_exe = sys.executable

    try:
        if IS_WINDOWS:
            quoted = f'"{python_exe}" "{script}" internal-daemon {cid}'
            exists = subprocess.call(['sc', 'query', service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0
            if not exists:
                rc = subprocess.call(['sc', 'create', service_name, f'binPath= {quoted}', 'start= auto'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if rc != 0:
                    print(f"Warning: Could not create Windows service '{service_name}'.")
                    return False
            subprocess.call(['sc', 'start', service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            unit_name = f"{service_name}.service"
            unit_path = os.path.join('/etc/systemd/system', unit_name)
            exec_start = f"{shlex.quote(python_exe)} {shlex.quote(script)} internal-daemon {shlex.quote(cid)}"
            unit_contents = (
                "[Unit]\n"
                f"Description=LockBox container {state.get('name') or cid}\n"
                "After=network.target\n\n"
                "[Service]\n"
                "Type=simple\n"
                f"WorkingDirectory={INSTALL_DIR}\n"
                f"ExecStart={exec_start}\n"
                "Restart=always\n"
                "RestartSec=2\n\n"
                "[Install]\n"
                "WantedBy=multi-user.target\n"
            )
            with open(unit_path, 'w') as f:
                f.write(unit_contents)

            if subprocess.call(['systemctl', 'daemon-reload']) != 0:
                print(f"Warning: Failed to reload systemd for service '{unit_name}'.")
                return False
            if subprocess.call(['systemctl', 'enable', '--now', unit_name]) != 0:
                print(f"Warning: Failed to enable/start service '{unit_name}'.")
                return False

        state['service_enabled'] = True
        state['service_name'] = service_name
        state['service_platform'] = 'windows' if IS_WINDOWS else 'linux'
        save_state(cid, state)
        print(f"Service mode enabled: {service_name}")
        return True
    except Exception as e:
        print(f"Warning: Unable to configure service mode ({e}).")
        return False


def _stop_container_service(state):
    if not state or not state.get('service_enabled'):
        return

    service_name = state.get('service_name') or _container_service_name(state)
    try:
        if IS_WINDOWS:
            subprocess.call(['sc', 'stop', service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.call(['systemctl', 'stop', f"{service_name}.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def _remove_container_service(state):
    if not state or not state.get('service_enabled'):
        return

    service_name = state.get('service_name') or _container_service_name(state)
    try:
        if IS_WINDOWS:
            subprocess.call(['sc', 'stop', service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.call(['sc', 'delete', service_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            unit_name = f"{service_name}.service"
            unit_path = os.path.join('/etc/systemd/system', unit_name)
            subprocess.call(['systemctl', 'disable', '--now', unit_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(unit_path):
                os.remove(unit_path)
            subprocess.call(['systemctl', 'daemon-reload'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ==========================================
# ROBUST NETWORKING (FIXED FOR WSL 172.x)
# ==========================================
def get_container_ip(cid, log_file=None):
    if not cid: return None

    # 1. Python Probe (Most reliable)
    try:
        if IS_WINDOWS:
            # We explicitly ask for the non-localhost IP
            cmd = ['wsl', '-d', cid, 'python3', '-c', 
                   'import socket; print([ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if not ip.startswith("127.")][0])']
            output = subprocess.check_output(cmd).decode().strip()
            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", output):
                return output
    except: pass

    # 2. Raw ifconfig Parsing (Looking specifically for 172.x or 192.x)
    try:
        if IS_WINDOWS:
            cmd = ['wsl', '-d', cid, 'ifconfig']
            output = subprocess.check_output(cmd).decode()

            # Priority 1: Match 172.x.x.x (WSL default range)
            wsl_match = re.search(r'inet (?:addr:)?(172\.\d{1,3}\.\d{1,3}\.\d{1,3})', output)
            if wsl_match: return wsl_match.group(1)

            # Priority 2: Match any non-127 IP
            all_matches = re.findall(r'inet (?:addr:)?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', output)
            for ip in all_matches:
                if not ip.startswith("127."): return ip
    except: pass

    # 3. Last Resort: ip addr
    try:
        if IS_WINDOWS:
            cmd = ['wsl', '-d', cid, 'ip', 'addr']
            output = subprocess.check_output(cmd).decode()
            matches = re.findall(r'inet (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', output)
            for ip in matches:
                if not ip.startswith("127."): return ip
    except: pass

    if log_file: 
        log_file.write(f"[Network] Failed to resolve IP. Defaulting to 127.0.0.1\n")
    return '127.0.0.1' # Fallback, but likely to fail if not host net

def wait_for_port(ip, port, timeout=10):
    """Wait until the container port is actually listening before proxying"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((ip, port), timeout=1):
                return True
        except:
            time.sleep(0.5)
    return False

def start_port_forwarding(cid, mappings, stop_event, log_file):
    target_ip = '127.0.0.1'

    if IS_WINDOWS: 
        ip = get_container_ip(cid, log_file)
        if ip: 
            target_ip = ip
            log_file.write(f"[Network] Resolved IP: {target_ip}\n")

    for mapping in mappings:
        try:
            parts = mapping.split(':')
            host_port, container_port = int(parts[0]), int(parts[1])

            if not check_port_free(host_port):
                log_file.write(f"[FATAL] Port {host_port} is busy.\n")
                return False

            # Don't start proxy until Flask/Redis is actually ready
            if not wait_for_port(target_ip, container_port):
                 log_file.write(f"[Network] Warning: Container port {container_port} not open yet. Proxy might fail initially.\n")

            t = threading.Thread(target=tcp_proxy, args=(host_port, target_ip, container_port, stop_event, log_file))
            t.daemon = True
            t.start()
            log_file.write(f"[Network] Proxy: localhost:{host_port} <--> {target_ip}:{container_port}\n")
        except Exception as e:
            log_file.write(f"[Network] Error: {e}\n")
            return False
    log_file.flush()
    return True

def tcp_proxy(src, target_ip, dst, stop_event, log_file):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('0.0.0.0', src))
        server.listen(10)
        server.settimeout(1.0)
    except Exception as e: return

    while not stop_event.is_set():
        try:
            client, addr = server.accept()
            threading.Thread(target=handle_connection_retry, args=(client, target_ip, dst, log_file)).start()
        except socket.timeout: continue
        except: break
    server.close()

def parse_env_entries(envs):
    env_map = {}
    for entry in envs or []:
        if '=' in entry:
            key, value = entry.split('=', 1)
            env_map[key] = value
    return env_map

def normalize_run_options(ports, volumes, envs):
    return {
        "ports": list(ports or []),
        "volumes": list(volumes or []),
        "envs": list(envs or [])
    }

def handle_connection_retry(client, ip, port, log_file):
    target = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connected = False
    for attempt in range(5): 
        try:
            target.connect((ip, port))
            connected = True
            break
        except Exception: time.sleep(0.2)

    if not connected:
        client.close()
        return

    def forward(src, dst):
        try:
            while True:
                data = src.recv(32768)
                if not data: break
                dst.send(data)
        except: pass
        finally: 
            src.close()
            dst.close()

    t1 = threading.Thread(target=forward, args=(client, target))
    t2 = threading.Thread(target=forward, args=(target, client))
    t1.start(); t2.start()
    t1.join(); t2.join()

# ==========================================
# WINDOWS ENGINE
# ==========================================
class WindowsEngine:
    def check_reqs(self):
        try: subprocess.check_call(['wsl', '--status'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except: sys.exit("Error: WSL not ready.")

    def _copy_recursive(self, bid, src_path, dst_path, workdir):
        if not dst_path.startswith('/'):
            if workdir == "/": full_dst_root = f"/{dst_path}"
            else: full_dst_root = f"{workdir}/{dst_path}"
            full_dst_root = full_dst_root.replace("/./", "/").rstrip("/.")
        else:
            full_dst_root = dst_path

        subprocess.call(['wsl', '-d', bid, 'sh', '-c', f'mkdir -p "{full_dst_root}"'])

        if os.path.isfile(src_path):
            target_file = full_dst_root
            if dst_path == "." or dst_path.endswith("/") or dst_path.endswith("\\"):
                 base = os.path.basename(src_path)
                 target_file = f"{full_dst_root}/{base}"

            target_file = target_file.replace("\\", "/").replace("//", "/")
            parent_dir = os.path.dirname(target_file)
            subprocess.call(['wsl', '-d', bid, 'sh', '-c', f'mkdir -p "{parent_dir}"'])
            with open(src_path, 'rb') as f:
                subprocess.run(['wsl', '-d', bid, 'sh', '-c', f'cat > "{target_file}"'], stdin=f, check=True)

        elif os.path.isdir(src_path):
            for root, dirs, files in os.walk(src_path):
                if '.git' in dirs: dirs.remove('.git')
                if 'venv' in dirs: dirs.remove('venv')
                if '__pycache__' in dirs: dirs.remove('__pycache__')

                for file in files:
                    local_file = os.path.join(root, file)
                    rel_path = os.path.relpath(local_file, src_path)
                    container_file = f"{full_dst_root}/{rel_path}".replace("\\", "/").replace("//", "/")
                    cont_parent = os.path.dirname(container_file)
                    subprocess.call(['wsl', '-d', bid, 'sh', '-c', f'mkdir -p "{cont_parent}"'])
                    with open(local_file, 'rb') as f:
                         subprocess.run(['wsl', '-d', bid, 'sh', '-c', f'cat > "{container_file}"'], stdin=f, check=True)

    def build(self, tag, instructions, context):
        self.check_reqs()
        print(f"Building image '{tag}'...")
        bid = f"build_{uuid.uuid4().hex[:8]}"
        root = os.path.join(CONTAINERS_DIR, bid)
        os.makedirs(root)

        current_workdir = "/" 
        meta = {"cmd": None, "workdir": "/"}

        try:
            base = os.path.join(IMAGES_DIR, "alpine.tar.gz")
            if not os.path.exists(base): raise Exception("Base image missing.")
            run_quiet(['wsl', '--import', bid, root, base])
            run_quiet(['wsl', '-d', bid, 'sh', '-c', 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'])

            subprocess.call(['wsl', '-d', bid, 'sh', '-c', 'mkdir -p /app /root /tmp'])

            for step in instructions.get('STEPS', []):
                cmd, arg = step['cmd'], step['arg']

                if cmd == 'COPY':
                    parts = arg.split(' ')
                    if len(parts) >= 2:
                        dst = parts[-1]
                        src = " ".join(parts[:-1])
                        full_src = os.path.abspath(os.path.join(context, src))
                        if os.path.exists(full_src):
                            self._copy_recursive(bid, full_src, dst, current_workdir)
                elif cmd == 'EXEC':
                    print(f"   RUN {arg}")
                    try: subprocess.check_call(['wsl', '-d', bid, 'sh', '-c', arg])
                    except subprocess.CalledProcessError: raise
                elif cmd == 'ENV':
                    subprocess.check_call(['wsl', '-d', bid, 'sh', '-c', f"echo 'export {arg}' >> /etc/profile"])
                elif cmd == 'DIR':
                    subprocess.call(['wsl', '-d', bid, 'sh', '-c', f"mkdir -p {arg}"])
                    current_workdir = arg.strip()
                    meta["workdir"] = current_workdir
                elif cmd == 'START':
                    try:
                        meta["cmd"] = json.loads(arg)
                        if isinstance(meta["cmd"], list): meta["cmd"] = " ".join(meta["cmd"])
                    except: meta["cmd"] = arg

            dest = os.path.join(IMAGES_DIR, f"{tag}.tar")
            run_quiet(['wsl', '--export', bid, dest])

            with open(os.path.join(IMAGES_DIR, f"{tag}.json"), 'w') as f:
                json.dump(meta, f)

            print(f"Success: Built {tag}")
        except Exception as e:
            print(f"Build Failed: {e}")
        finally:
            run_quiet(['wsl', '--unregister', bid])
            shutil.rmtree(root, ignore_errors=True)

    def run(self, image, name, ports, volumes, envs, detach, cmd, restart_policy="no", labels=None, network="bridge", as_service=False):
        self.check_reqs()
        if name and get_id_by_name(name): 
            print(f"Note: Container '{name}' already exists. Skipping.")
            return

        for p in ports:
            if not check_port_free(int(p.split(':')[0])): return print(f"Error: Port {p} taken.")

        img_path = os.path.join(IMAGES_DIR, f"{image}.tar")
        if not os.path.exists(img_path): return print(f"Error: Image '{image}' not found.")

        workdir = "/"
        if not cmd:
            try: 
                meta = json.load(open(os.path.join(IMAGES_DIR, f"{image}.json")))
                cmd = meta.get("cmd")
                workdir = meta.get("workdir", "/")
            except: pass
        if not cmd: cmd = "/bin/sh"

        cid = f"{uuid.uuid4().hex[:12]}"
        root = os.path.join(CONTAINERS_DIR, cid)
        os.makedirs(root)

        try:
            subprocess.check_call(['wsl', '--import', cid, root, img_path], stdout=subprocess.DEVNULL)
            time.sleep(2.0)

            state = {
                "id": cid, "name": name, "image": image, "status": "starting", 
                "ports": ports, "volumes": volumes, "envs": envs, 
                "command": cmd,
                "workdir": workdir,
                "created": datetime.now().isoformat(),
                "root": root,
                "restart": restart_policy or "no",
                "restart_count": 0,
                "labels": labels or {},
                "network": network or "bridge",
                "service_enabled": bool(as_service),
                "service_name": None
            }
            save_state(cid, state)

            log_path = os.path.join(LOGS_DIR, f"{cid}.log")
            log_handle = open(log_path, 'a')
            log_handle.write(f"--- Init {name or cid} ---\n")
            log_handle.flush()

            if as_service:
                if not _register_container_service(state):
                    print("Warning: Falling back to non-service mode.")
                    state['service_enabled'] = False
                    state['service_name'] = None
                    save_state(cid, state)
                    spawn_internal_daemon(cid, log_handle)
            else:
                spawn_internal_daemon(cid, log_handle)

            print(f"Starting {name or cid}...", end="", flush=True)
            for _ in range(240): 
                time.sleep(0.25)
                s = load_state(cid)
                if not s: break
                if s['status'] == 'running':
                    print(" OK")
                    if not detach: self.logs(cid, follow=True)
                    return
                elif s['status'] == 'error':
                    print(" Failed.")
                    self.print_crash_logs(cid)
                    return
                print(".", end="", flush=True)

            print(" Timeout.")
            self.stop(cid)

        except Exception as e:
            print(f"Run Error: {e}")
            self.force_cleanup(cid)

    def print_crash_logs(self, cid):
        lp = os.path.join(LOGS_DIR, f"{cid}.log")
        if os.path.exists(lp):
            print(f"--- LOGS ---")
            with open(lp, 'r') as f: print(f.read())

    def stop(self, ident):
        s = load_state(ident)
        if not s: return print("Not found.")
        cid = s['id']
        _stop_container_service(s)
        run_quiet(['wsl', '--terminate', cid])
        s['status'] = 'exited'
        save_state(cid, s)
        print(f"Stopped {cid}")

    def rm(self, ident):
        s = load_state(ident)
        if not s: return print("Not found.")
        cid = s['id']
        print(f"Removing {cid}...")
        _remove_container_service(s)
        self.stop(ident)
        time.sleep(1)
        for i in range(5):
            if run_quiet(['wsl', '--unregister', cid]): break
            time.sleep(1)
        shutil.rmtree(os.path.join(CONTAINERS_DIR, cid), ignore_errors=True)
        remove_state(cid)
        print("Done.")

    def force_cleanup(self, cid):
        cleanup_container_resources(load_state(cid) or {"id": cid, "root": os.path.join(CONTAINERS_DIR, cid)})

    def exec(self, ident, cmd, interactive):
        s = load_state(ident)
        if not s: return print("Container not found.")
        subprocess.call(['wsl', '-d', s['id'], 'sh', '-c', cmd])

    def logs(self, ident, follow):
        s = load_state(ident)
        if not s: return print("Container not found.")
        cid = s['id']
        lp = os.path.join(LOGS_DIR, f"{cid}.log")
        if not os.path.exists(lp): return print("(No logs)")
        with open(lp, 'r') as f:
            if not follow: print(f.read())
            else:
                f.seek(0, 2)
                try:
                    while True:
                        l = f.readline()
                        if not l:
                            time.sleep(0.1)
                            if load_state(cid)['status'] != 'running': break
                            continue
                        print(l, end='')
                except: pass

    def ps(self):
        print(f"{'CONTAINER ID':<15} {'NAME':<15} {'IMAGE':<15} {'STATUS':<10} {'PORTS'}")
        for d in iter_states():
            if d.get('status') == 'running':
                name = d.get('name') or "-"
                ports = ",".join(d.get('ports', []))
                print(f"{d['id']:<15} {name:<15} {d['image']:<15} {d['status']:<10} {ports}")

    def inject_hosts(self, cid, hosts_map):
        """Updates /etc/hosts"""
        for hostname, ip in hosts_map.items():
            try:
                entry = f"\n{ip} {hostname}"
                cmd = f"printf '{entry}' >> /etc/hosts"
                subprocess.call(['wsl', '-d', cid, 'sh', '-c', cmd])
            except: pass

# ==========================================
# LINUX ENGINE
# ==========================================
class LinuxEngine:
    def check_reqs(self):
        if os.geteuid() != 0: sys.exit("Error: Run as sudo.")

    def _copy_recursive(self, root, src_path, dst_path):
        if os.path.isfile(src_path):
            if dst_path == "." or dst_path.endswith("/"):
                dst_path = os.path.join(dst_path, os.path.basename(src_path))
            full_dst = os.path.join(root, dst_path.lstrip('/'))
            os.makedirs(os.path.dirname(full_dst), exist_ok=True)
            shutil.copy2(src_path, full_dst)
        elif os.path.isdir(src_path):
            full_dst_root = os.path.join(root, dst_path.lstrip('/'))
            if dst_path == "." or dst_path == "./":
                subprocess.call(['cp', '-r', src_path + '/.', root])
            else:
                subprocess.call(['cp', '-r', src_path, full_dst_root])

    def build(self, tag, instructions, context):
        self.check_reqs()
        print(f"Building '{tag}'...")
        bid = f"build_{uuid.uuid4().hex[:8]}"
        root = os.path.join(CONTAINERS_DIR, bid)
        os.makedirs(root)
        meta = {"cmd": None, "workdir": "/"}
        try:
            base = os.path.join(IMAGES_DIR, "alpine.tar.gz")
            if not os.path.exists(base): raise Exception("Base image missing.")
            with tarfile.open(base) as t: t.extractall(root)
            with open(os.path.join(root, 'etc/resolv.conf'), 'w') as f: f.write("nameserver 8.8.8.8\\n")

            for step in instructions.get('STEPS', []):
                cmd, arg = step['cmd'], step['arg']
                if cmd == 'COPY':
                    parts = arg.split(' ')
                    if len(parts) >= 2:
                        dst = parts[-1]
                        src = " ".join(parts[:-1])
                        full_src = os.path.join(context, src)
                        if os.path.exists(full_src):
                            self._copy_recursive(root, full_src, dst)
                elif cmd == 'EXEC':
                    print(f"   RUN {arg}")
                    subprocess.check_call(['chroot', root, '/bin/sh', '-c', arg])
                elif cmd == 'ENV':
                    subprocess.check_call(['chroot', root, '/bin/sh', '-c', f"echo 'export {arg}' >> /etc/profile"])
                elif cmd == 'DIR':
                    meta["workdir"] = arg.strip()
                    os.makedirs(os.path.join(root, arg.lstrip('/')), exist_ok=True)
                elif cmd == 'START':
                    try:
                        meta["cmd"] = json.loads(arg)
                        if isinstance(meta["cmd"], list): meta["cmd"] = " ".join(meta["cmd"])
                    except: meta["cmd"] = arg

            with tarfile.open(os.path.join(IMAGES_DIR, f"{tag}.tar"), "w") as t: t.add(root, arcname=".")
            with open(os.path.join(IMAGES_DIR, f"{tag}.json"), 'w') as f: json.dump(meta, f)
            print(f"Success: Built {tag}")
        except Exception as e: print(f"Build Failed: {e}")
        finally: shutil.rmtree(root, ignore_errors=True)

    def run(self, image, name, ports, volumes, envs, detach, cmd, restart_policy="no", labels=None, network="bridge", as_service=False):
        self.check_reqs()
        if name and get_id_by_name(name): return print(f"Error: Name '{name}' taken.")
        for p in ports:
            if not check_port_free(int(p.split(':')[0])): return print(f"Error: Port {p} taken.")

        img_path = os.path.join(IMAGES_DIR, f"{image}.tar")
        if not os.path.exists(img_path): return print("Image missing.")

        workdir = "/"
        if not cmd:
            try: 
                meta = json.load(open(os.path.join(IMAGES_DIR, f"{image}.json")))
                cmd = meta.get("cmd")
                workdir = meta.get("workdir", "/")
            except: pass
        if not cmd: cmd = "/bin/sh"

        cid = f"{uuid.uuid4().hex[:12]}"
        root = os.path.join(CONTAINERS_DIR, cid)
        os.makedirs(root)
        try:
            with tarfile.open(img_path) as t: t.extractall(root)
            with open(os.path.join(root, 'etc/resolv.conf'), 'w') as f: f.write("nameserver 8.8.8.8\\n")
            state = {
                "id": cid, "name": name, "image": image, "status": "starting",
                "ports": ports, "volumes": volumes, "envs": envs,
                "command": cmd,
                "workdir": workdir,
                "created": datetime.now().isoformat(),
                "root": root,
                "restart": restart_policy or "no",
                "restart_count": 0,
                "labels": labels or {},
                "network": network or "bridge",
                "service_enabled": bool(as_service),
                "service_name": None
            }
            save_state(cid, state)

            lp = os.path.join(LOGS_DIR, f"{cid}.log")
            lf = open(lp, 'a')
            lf.write(f"--- Init {cid} ---\\n"); lf.flush()

            if as_service:
                if not _register_container_service(state):
                    print("Warning: Falling back to non-service mode.")
                    state['service_enabled'] = False
                    state['service_name'] = None
                    save_state(cid, state)
                    spawn_internal_daemon(cid, lf)
            else:
                spawn_internal_daemon(cid, lf)

            print("Starting...", end="", flush=True)
            for _ in range(40):
                time.sleep(0.25)
                s = load_state(cid)
                if not s: break
                if s['status'] == 'running':
                    print(" OK")
                    if not detach: self.logs(cid, follow=True)
                    return
                if s['status'] == 'error': return print(" Failed.")
                print(".", end="", flush=True)
            print(" Timeout.")
        except: shutil.rmtree(root, ignore_errors=True)

    def stop(self, ident):
        s = load_state(ident)
        if not s: return
        cid = s['id']
        _stop_container_service(s)
        s['status'] = 'exited'
        save_state(cid, s)
        print(f"Stopped {cid}")

    def rm(self, ident):
        s = load_state(ident)
        if not s: return
        _remove_container_service(s)
        self.stop(ident)
        if 'mounts' in s:
            for m in s['mounts']: run_quiet(['umount', '-l', m])
        run_quiet(['umount', '-l', os.path.join(s['root'], 'proc')])
        shutil.rmtree(s['root'], ignore_errors=True)
        remove_state(s['id'])
        print("Done.")

    def exec(self, ident, cmd, interactive):
        s = load_state(ident)
        if not s: return
        subprocess.call(['chroot', s['root'], '/bin/sh', '-c', cmd])

    def logs(self, ident, follow):
        s = load_state(ident)
        if not s: return
        lp = os.path.join(LOGS_DIR, f"{s['id']}.log")
        if os.path.exists(lp):
            with open(lp, 'r') as f: print(f.read())

    def ps(self):
        print(f"{'CONTAINER ID':<15} {'NAME':<15} {'IMAGE':<15} {'STATUS':<10} {'PORTS'}")
        for d in iter_states():
            if d.get('status') == 'running':
                print(f"{d['id']:<15} {d.get('name') or '-':<15} {d['image']:<15} {d['status']:<10} {','.join(d.get('ports',[]))}")

    def inject_hosts(self, cid, hosts_map):
        pass

# ==========================================
# DAEMON COMMAND (INTERNAL)
# ==========================================
@click.command(name='internal-daemon', hidden=True)
@click.argument('cid')
def internal_daemon(cid):
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    while True:
        s = load_state(cid)
        if not s:
            return print(f"Fatal: State missing {cid}")

        print(f"[Daemon] Init {cid} at {datetime.now()}")
        stop = threading.Event()

        if s.get('ports'):
            if not start_port_forwarding(cid, s['ports'], stop, sys.stdout):
                s['status'] = 'error'
                save_state(cid, s)
                return

        exit_code = 0
        try:
            cmd = s.get('command') or "sleep infinity"
            workdir = s.get('workdir', '/')

            s['status'] = 'running'
            save_state(cid, s)

            print(f"[Daemon] WorkDir: {workdir}")
            print(f"[Daemon] Running: {cmd}")

            if IS_WINDOWS:
                for v in s.get('volumes', []):
                    h, c = v.rsplit(':', 1)
                    wh = os.path.abspath(h).replace('\\','/')
                    drive, rest = os.path.splitdrive(wh)
                    if drive: wh = f"/mnt/{drive[0].lower()}{rest}"
                    subprocess.call(['wsl', '-d', cid, 'sh', '-c', f'mkdir -p {c} && mount --bind "{wh}" "{c}"'])

                for e in s.get('envs', []):
                    subprocess.call(['wsl', '-d', cid, 'sh', '-c', f"echo 'export {e}' >> /etc/profile"])

                subprocess.call(['wsl', '-d', cid, 'sh', '-c', 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'])
                full_cmd = f"cd {workdir} && {cmd}"
                exit_code = subprocess.call(['wsl', '-d', cid, 'sh', '-c', full_cmd])
            else:
                mp = []
                for v in s.get('volumes', []):
                    h, c = v.rsplit(':', 1)
                    t = os.path.join(s['root'], c.lstrip('/'))
                    os.makedirs(t, exist_ok=True)
                    subprocess.call(['mount', '--bind', h, t])
                    mp.append(t)
                proc = os.path.join(s['root'], 'proc')
                os.makedirs(proc, exist_ok=True)
                subprocess.call(['mount', '-t', 'proc', '/proc', proc])
                s['mounts'] = mp
                save_state(cid, s)

                full_cmd = f"cd {workdir} && {cmd}"
                exit_code = subprocess.call(['chroot', s['root'], '/bin/sh', '-c', full_cmd])

        except Exception as e:
            print(f"Crash: {e}")
            exit_code = 1
        finally:
            stop.set()

        s = load_state(cid)
        if not s:
            return

        restart_policy = s.get('restart', 'no')
        restart_count = s.get('restart_count', 0)
        should_restart = False

        if restart_policy == 'always':
            should_restart = True
        elif restart_policy == 'on-failure' and exit_code != 0:
            should_restart = True
        elif restart_policy.startswith('unless-stopped'):
            should_restart = s.get('status') != 'exited'

        if should_restart and s.get('status') != 'exited':
            s['restart_count'] = restart_count + 1
            s['status'] = 'restarting'
            save_state(cid, s)
            print(f"[Daemon] Restarting {cid} (count={s['restart_count']})")
            time.sleep(1)
            continue

        s['status'] = 'exited'
        save_state(cid, s)
        return

@click.command(name='monitor-daemon', hidden=True)
@click.argument('config_path')
@click.argument('project_name')
def monitor_daemon(config_path, project_name):
    print(f"--- Auto-Update Monitor Started for {project_name} ---")

    last_state = {} 

    while True:
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

            services = config.get('services', {})

            for name, svc in services.items():
                au = svc.get('auto-update', {})
                if not au.get('enabled'): continue

                container_name = f"{project_name}_{name}"
                cid = get_id_by_name(container_name)

                if not cid: continue

                # CHECK FOR UPDATES
                url = au.get('url')
                should_update = False

                if url:
                    # Remote Check
                    current_header = get_remote_header(url)
                    if current_header and last_state.get(name) != current_header:
                        print(f"[Update] Remote change detected for {name}")
                        last_state[name] = current_header
                        if last_state.get(f"{name}_init"): should_update = True
                        last_state[f"{name}_init"] = True
                else:
                    # Local Check
                    build_path = svc.get('build', '.')
                    lbox_file = os.path.join(build_path, 'app.lbox')
                    if not os.path.exists(lbox_file): lbox_file = os.path.join(build_path, 'lbox')

                    if os.path.exists(lbox_file):
                        current_hash = calculate_file_hash(lbox_file)
                        if last_state.get(name) != current_hash:
                            print(f"[Update] Local change detected for {name}")
                            last_state[name] = current_hash
                            if last_state.get(f"{name}_init"): should_update = True
                            last_state[f"{name}_init"] = True

                if should_update:
                    print(f"[*] Recreating {container_name}...")

                    eng = WindowsEngine() if IS_WINDOWS else LinuxEngine()
                    image_tag = svc.get('image', container_name)

                    if url:
                        print(f"   Downloading {url}...")
                        dest = os.path.join(IMAGES_DIR, f"{image_tag}.tar")
                        urllib.request.urlretrieve(url, dest)
                    else:
                        subprocess.call([sys.executable, sys.argv[0], "build", "-t", image_tag, svc.get('build', '.')])

                    eng.stop(container_name)
                    time.sleep(2) 
                    eng.rm(container_name)

                    ports = svc.get('ports', [])
                    vols = svc.get('volumes', [])
                    envs = svc.get('environment', [])

                    eng.run(
                        image_tag,
                        container_name,
                        ports,
                        vols,
                        envs,
                        True,
                        None,
                        restart_policy=svc.get('restart', 'no'),
                        labels=svc.get('labels', {}),
                        network=svc.get('network', 'bridge')
                    )
                    print(f"[OK] {container_name} updated.")

        except Exception as e:
            print(f"[Monitor Error] {e}")

        time.sleep(10)

# ==========================================
# CLI DISPATCH
# ==========================================
@click.group()
def cli(): pass
eng = WindowsEngine() if IS_WINDOWS else LinuxEngine()

@click.command()
@click.option('-t', required=True)
@click.argument('path', default='.')
def build(path, t):
    fp = os.path.join(path, 'lbox') if os.path.exists(os.path.join(path, 'lbox')) else os.path.join(path, 'app.lbox')
    if not os.path.exists(fp): return print("No lbox file.")
    d = {'BASE':None,'STEPS':[]}
    with open(fp) as f:
        for l in f:
            p = l.strip().split(' ', 1)
            if not p or l.startswith('#'): continue
            if p[0]=='BOX_BASE': d['BASE']=p[1]
            elif p[0] in ['BOX_COPY','BOX_EXEC']: d['STEPS'].append({'cmd':p[0][4:], 'arg':p[1]})
            elif p[0]=='BOX_ENV': d['STEPS'].append({'cmd':'ENV', 'arg':p[1]})
            elif p[0]=='BOX_START': d['STEPS'].append({'cmd':'START', 'arg':p[1]})
            elif p[0]=='BOX_DIR': d['STEPS'].append({'cmd':'DIR', 'arg':p[1]})
    eng.build(t, d, path)

@click.command()
@click.argument('image')
@click.option('--name')
@click.option('--port', '-p', multiple=True)
@click.option('--volume', '-v', multiple=True)
@click.option('--env', '-e', multiple=True)
@click.option('--detach', '-d', is_flag=True)
@click.option('--restart', type=click.Choice(['no', 'always', 'on-failure', 'unless-stopped']), default='no')
@click.option('--label', '-l', multiple=True, help='Set metadata labels key=value')
@click.option('--network', default='bridge')
@click.option('--service/--no-service', default=False, help='Register container as a host-managed service.')
@click.argument('cmd', required=False)
def run(image, name, port, volume, env, detach, restart, label, network, service, cmd):
    labels = parse_env_entries(label)
    eng.run(image, name, port, volume, env, detach, cmd, restart_policy=restart, labels=labels, network=network, as_service=service)

@click.command()
@click.argument('identifier')
def stop(identifier): eng.stop(identifier)

@click.command()
@click.argument('identifier')
def restart(identifier):
    s = load_state(identifier)
    if not s:
        return print("Container not found.")

    runtime = normalize_run_options(s.get('ports'), s.get('volumes'), s.get('envs'))
    config = {
        "image": s.get('image'),
        "name": s.get('name'),
        "command": s.get('command'),
        "restart": s.get('restart', 'no'),
        "labels": s.get('labels', {}),
        "network": s.get('network', 'bridge'),
        "service_enabled": s.get('service_enabled', False)
    }

    eng.rm(identifier)
    eng.run(
        config['image'],
        config['name'],
        runtime['ports'],
        runtime['volumes'],
        runtime['envs'],
        True,
        config['command'],
        restart_policy=config['restart'],
        labels=config['labels'],
        network=config['network'],
        as_service=config['service_enabled']
    )

@click.command()
@click.argument('identifier')
def inspect(identifier):
    s = load_state(identifier)
    if not s:
        return print("Container not found.")
    print(json.dumps(s, indent=2, sort_keys=True))

@click.command()
@click.argument('identifier')
def rm(identifier): eng.rm(identifier)

@click.command()
@click.argument('identifier')
@click.argument('cmd')
@click.option('-it', '--interactive', is_flag=True)
def exec(identifier, cmd, interactive): eng.exec(identifier, cmd, interactive)

@click.command()
@click.argument('identifier')
@click.option('--follow', '-f', is_flag=True)
def logs(identifier, follow): eng.logs(identifier, follow)

@click.command()
def ps(): eng.ps()

@click.command()
def images():
    for f in os.listdir(IMAGES_DIR):
        if f.endswith('.tar') or f.endswith('.tar.gz'): print(f)

create = register_create_commands(
    cli,
    eng,
    IS_WINDOWS,
    STATE_DIR,
    INSTALL_DIR,
    get_id_by_name,
    image_exists,
    list_project_containers,
    remove_image_artifacts,
    get_container_ip,
)

for c in [build, run, stop, restart, inspect, rm, exec, ps, images, logs, internal_daemon, monitor_daemon]:
    cli.add_command(c)

if __name__ == '__main__': cli()
