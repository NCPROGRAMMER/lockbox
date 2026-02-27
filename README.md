# 🔒 LockBox Create Demo (Web + Redis)

This demo shows how to run a **Flask web application backed by Redis** using **LockBox Create** — a Docker-style compose workflow that runs on LockBox’s isolated Alpine-based containers.

**No Docker daemon is required.**

---

## ✨ What This Demo Demonstrates

- Building images from local `app.lbox` files  
- Running multiple services (web + redis) with `lockbox-create.yml`  
- Named volumes that persist across container/image removal  
- Port forwarding from containers to the host  
- Absolute-path container startup (**required for LockBox v4.7+**)
- Health endpoint (`/healthz`) for quick service checks
- Redis host fallback logic for more reliable local runs
- Redis client/host reuse to reduce per-request connection overhead

---

## 📦 Requirements

### Windows
- Python **3.10+**
- WSL installed and working (`wsl --status`)
- LockBox installed and available as `lbox` in your PATH

### Linux
- Python **3.10+**
- Root access (LockBox uses `chroot` and mount namespaces)

---

## 📁 Project Structure

```text
LockBox_Demo/
├── app.py
├── requirements.txt
├── app.lbox
├── lockbox-create.yml
└── db/
    └── app.lbox
```

### Key Files

**`app.lbox`**  
Builds the Flask web image and starts the app using absolute paths:

```
/app/venv/bin/python /app/app.py
```

**`db/app.lbox`**  
Builds a Redis image and runs Redis bound to `0.0.0.0`.

**`lockbox-create.yml`**  
Defines the `web` and `redis-db` services and port mappings.

---

## 🧠 Why Absolute Paths Matter

LockBox v4.7 runs container commands from the **LockBox install directory**, not from the service build context.

Because of this, commands like:

```bash
python app.py
```

will fail, since `app.py` is not in the current working directory.

This demo fixes the issue by:
- Copying application files to `/app` inside the container
- Starting the application using **absolute paths**

This behavior is intentional and required for reliable startup.

---

## 🚀 Running the Demo

From the directory containing `lockbox-create.yml`, run:

```bash
lbox create up
```

Then open your browser:

```
http://localhost:8080
```

You should see a page showing a hit counter backed by Redis.

Quick health check:

```bash
curl http://localhost:8080/healthz
```

---

## 🛑 Stopping the Demo

To stop and remove all services:

```bash
lbox create down
```

This will stop and remove:
- The web container
- The Redis container
- The auto-update monitor (if enabled)

By default, named volumes persist. Add `-v` to remove project volumes:
```bash
lbox create down -v
```

---

## 🔧 LockBox Command Reference

### `lbox` Core Commands

| Command | Description |
|------|------------|
| `lbox build -t <tag> <path>` | Build an image from an `app.lbox` file |
| `lbox run <image>` | Run a container from an image |
| `lbox run --name <name>` | Run a container with a fixed name |
| `lbox run -p HOST:CONT` | Publish a port |
| `lbox run -v HOST:CONT` | Bind-mount a host directory |
| `lbox run -v NAME:CONT` | Mount a named volume stored under `LockBox/volumes/NAME` |
| `lbox run -e VAR=value` | Set environment variables |
| `lbox run -d` | Run container in detached mode |
| `lbox run --restart <policy>` | Restart policy: `no`, `always`, `on-failure`, `unless-stopped` |
| `lbox run -l key=value` | Attach labels to a container |
| `lbox run --network <name>` | Store the desired network mode name |
| `lbox run --service` | Register container as a host-managed service (systemd on Linux, Service Control Manager on Windows) |
| `lbox stop <id|name>` | Stop a running container |
| `lbox rm <id|name>` | Remove a container |
| `lbox volumes` | List named volumes |
| `lbox rm volumes <name...>` | Remove specific named volumes |
| `lbox rm volumes --all` | Remove all named volumes |
| `lbox restart <id|name>` | Recreate and restart a container using saved config |
| `lbox inspect <id|name>` | Show full container metadata as JSON |
| `lbox exec <id|name> "<cmd>"` | Execute a command inside a container |
| `lbox logs <id|name>` | Show container logs |
| `lbox logs -f <id|name>` | Follow container logs |
| `lbox ps` | List running containers |
| `lbox images` | List available images |

---

### `lbox create` (Compose-style)

| Command | Description |
|------|------------|
| `lbox create up` | Build and start all services |
| `lbox create up -d` | Start services in detached mode |
| `lbox create up --force-recreate` | Recreate running service containers |
| `lbox create up --no-recreate` | Keep already running service containers |
| `lbox create up --remove-orphans` | Remove project containers missing from compose file |
| `lbox create up --service` | Run project service containers as host-managed services |
| `lbox create down` | Stop and remove all services |
| `lbox create down -v` | Stop/remove services and remove project named volumes |
| `lbox create rm volumes` | Remove named volumes declared by compose file |
| `lbox create rm volumes --all` | Remove all LockBox named volumes |
| `lbox create down --rmi all` | Also remove all service images |
| `lbox create down --rmi local` | Remove only images built from `build:` definitions |
| `lbox create up -f file.yml` | Use a custom compose file |

`lbox create` automatically:
- Builds missing images
- Starts services in dependency order
- Applies ports, volumes, and environment variables
- Creates named volumes in `LockBox/volumes` (compose-style names are project-prefixed)
- Optionally launches the auto-update monitor

---

## 🔌 Ports

| Service | Host Port | Container Port |
|-------|-----------|----------------|
| Web   | 8080      | 5000           |
| Redis | 6379      | 6379           |

You can change these values in `lockbox-create.yml`.

---

## 🌐 Redis Networking Note

LockBox does **not** provide Docker-style internal DNS between services.

For this reason, Redis is exposed on the host, and the web app connects using:
- `127.0.0.1`
- The WSL gateway IP (on Windows)
- An optional `REDIS_HOST` environment variable

This keeps the demo predictable and portable across systems.

---

## 🧯 Troubleshooting

### Web container exits immediately
- Check logs:
  ```bash
  lbox logs <container-id>
  ```
- Verify `BOX_START` uses absolute paths

### Port already in use
- Change ports in `lockbox-create.yml`
- Or stop the conflicting service

---

## 📄 License

Demo code is provided for testing and experimentation with **LockBox**.
