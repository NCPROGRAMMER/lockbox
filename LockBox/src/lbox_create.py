import click
import os
import signal
import subprocess
import sys
import time
import yaml


def register_create_commands(
    cli,
    eng,
    is_windows,
    state_dir,
    install_dir,
    get_id_by_name,
    image_exists,
    list_project_containers,
    remove_image_artifacts,
    get_container_ip,
):
    @cli.group()
    def create():
        pass

    @create.command()
    @click.option('--file', '-f', default='lockbox-create.yml')
    @click.option('--detach', '-d', is_flag=True)
    @click.option('--force-recreate', is_flag=True, help='Recreate containers even if they already exist.')
    @click.option('--no-recreate', is_flag=True, help='Do not recreate existing containers.')
    @click.option('--build/--no-build', default=True, help='Build images before starting containers.')
    @click.option('--remove-orphans', is_flag=True, help='Remove containers for this project that are not defined in the compose file.')
    def up(file, detach, force_recreate, no_recreate, build, remove_orphans):
        if force_recreate and no_recreate:
            raise click.UsageError("--force-recreate and --no-recreate cannot be used together.")

        if not os.path.exists(file):
            return print("YAML file not found.")

        with open(file, 'r') as f:
            config = yaml.safe_load(f)

        project_name = os.path.basename(os.getcwd()).lower().replace(' ', '')
        services = config.get('services', {})

        if remove_orphans:
            defined = {f"{project_name}_{name}" for name in services}
            for cname in list_project_containers(project_name):
                if cname not in defined:
                    print(f"Removing orphan container {cname}...")
                    eng.stop(cname)
                    eng.rm(cname)

        needs_monitor = False

        for name, svc in services.items():
            container_name = f"{project_name}_{name}"
            image_tag = svc.get('image', container_name)

            if 'build' in svc and build:
                print(f"Building {name}...")
                subprocess.call([sys.executable, sys.argv[0], "build", "-t", image_tag, svc.get('build', '.')])

            if not image_exists(image_tag):
                print(f"Error: Build failed for {name}. Image not found. Skipping.")
                continue

            existing_id = get_id_by_name(container_name)
            if existing_id and force_recreate:
                print(f"Recreating {container_name}...")
                eng.stop(container_name)
                eng.rm(container_name)
                existing_id = None

            if existing_id:
                if no_recreate:
                    print(f"Container {container_name} already running (no-recreate).")
                else:
                    print(f"Container {container_name} already running.")
            else:
                eng.run(
                    image_tag,
                    container_name,
                    svc.get('ports', []),
                    svc.get('volumes', []),
                    svc.get('environment', []),
                    True,
                    None,
                    restart_policy=svc.get('restart', 'no'),
                    labels=svc.get('labels', {}),
                    network=svc.get('network', 'bridge')
                )
                print(f"Started {container_name}")

            if svc.get('auto-update', {}).get('enabled'):
                needs_monitor = True

        print("Configuring Network (Waiting for IPs)...")

        hosts_map = {}
        for i in range(10):
            all_found = True
            for name in services:
                cname = f"{project_name}_{name}"
                cid = get_id_by_name(cname)
                if cid:
                    ip = get_container_ip(cid)
                    if ip and ip != '127.0.0.1':
                        hosts_map[name] = ip
                        hosts_map[cname] = ip
                    else:
                        all_found = False
            if all_found:
                break
            time.sleep(1)
            if i % 3 == 0:
                print(".", end="", flush=True)

        print("\nInjecting DNS records...")
        for name in services:
            cname = f"{project_name}_{name}"
            cid = get_id_by_name(cname)
            if cid:
                eng.inject_hosts(cid, hosts_map)

        print("Network Ready.")

        if needs_monitor:
            print("[*] Auto-Update enabled. Starting monitor...")
            pid_file = os.path.join(state_dir, f"monitor_{project_name}.pid")

            if os.path.exists(pid_file):
                print("Monitor already active.")
            else:
                startupinfo = None
                if is_windows:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= 1
                    startupinfo.wShowWindow = 0

                p = subprocess.Popen(
                    [sys.executable, sys.argv[0], "monitor-daemon", os.path.abspath(file), project_name],
                    cwd=install_dir,
                    creationflags=0x00000200,
                    startupinfo=startupinfo,
                    close_fds=True
                )
                with open(pid_file, 'w') as f:
                    f.write(str(p.pid))
                print(f"Monitor started (PID {p.pid})")

    @create.command()
    @click.option('--file', '-f', default='lockbox-create.yml')
    @click.option('--rmi', type=click.Choice(['none', 'local', 'all']), default='none', show_default=True, help='Remove images used by services.')
    @click.option('--remove-orphans', is_flag=True, help='Remove containers for this project that are not defined in the compose file.')
    def down(file, rmi, remove_orphans):
        if not os.path.exists(file):
            return
        with open(file, 'r') as f:
            config = yaml.safe_load(f)
        project_name = os.path.basename(os.getcwd()).lower().replace(' ', '')

        pid_file = os.path.join(state_dir, f"monitor_{project_name}.pid")
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    pid = int(f.read())
                os.kill(pid, signal.SIGTERM)
                print("Stopped Monitor.")
            except Exception:
                pass
            os.remove(pid_file)

        services = config.get('services', {})
        for name in services:
            cname = f"{project_name}_{name}"
            if get_id_by_name(cname):
                print(f"Stopping {cname}...")
                eng.stop(cname)
                eng.rm(cname)

        if remove_orphans:
            defined = {f"{project_name}_{name}" for name in services}
            for cname in list_project_containers(project_name):
                if cname not in defined:
                    print(f"Removing orphan container {cname}...")
                    eng.stop(cname)
                    eng.rm(cname)

        if rmi != 'none':
            for name, svc in services.items():
                if rmi == 'local' and 'build' not in svc:
                    continue
                image_tag = svc.get('image', f"{project_name}_{name}")
                if remove_image_artifacts(image_tag):
                    print(f"Removed image {image_tag}")

    return create
