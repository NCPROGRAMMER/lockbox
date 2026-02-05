\# 🔒 LockBox v0.1



LockBox is a lightweight, Python-based container runtime and orchestration tool designed as a standalone alternative to Docker. It enables building, running, and orchestrating containers on \*\*Windows (via WSL2)\*\* and \*\*Linux\*\* without requiring a heavy background daemon or cloud registry.



LockBox emphasizes simplicity, allowing users to build custom Linux-based operating systems from scratch using standard tarballs (Alpine Linux) and orchestrate them with a Compose-like syntax.



---



\## 🚀 Key Features



\* \*\*Zero-Dependency Engine:\*\* Written in pure Python; interacts directly with the OS kernel (chroot on Linux, WSL2 on Windows).

\* \*\*Custom Build Syntax:\*\* Uses `app.lbox` files (similar to Dockerfiles) to define container build steps.

\* \*\*LockBox Create:\*\* A built-in orchestrator (compatible with Docker Compose logic) to manage multi-container stacks.

\* \*\*Auto-Healing Network:\*\* Automatic DNS injection allows containers to resolve each other by name (e.g., `web` can ping `redis-db`).

\* \*\*Auto-Update Monitor:\*\* Built-in background daemon that detects local file changes or remote updates and automatically rebuilds/restarts containers (Hot Reloading).

\* \*\*Port Forwarding:\*\* Robust TCP proxying to expose container ports to the host machine.



---



\## 📦 Installation



\### Prerequisites

\* \*\*Python 3.8+\*\*

\* \*\*Windows:\*\* WSL2 must be enabled and installed.

\* \*\*Linux:\*\* Root privileges (sudo) are required for chroot operations.



\### Windows Setup

1\.  Extract the `LockBox\_v0.1.zip` file.

2\.  Open a terminal in the folder.

3\.  Run the setup script:

&nbsp;   setup.bat

4\.  Restart your terminal to refresh your PATH.

5\.  Verify installation:

&nbsp;   lbox --help



\### Linux Setup

1\.  Extract the `LockBox\_v0.1.zip` file.

2\.  Run the install script:

&nbsp;   chmod +x install\_linux.sh

&nbsp;   ./install\_linux.sh

3\.  Verify installation:

&nbsp;   sudo lbox --help



---



\## 🛠️ Usage Guide



\### 1. The `app.lbox` Format

LockBox uses its own configuration file to build images. It mimics Dockerfile syntax.



| Command | Description | Example |

| :--- | :--- | :--- |

| `BOX\_BASE` | The base OS tarball (currently supports `alpine`). | `BOX\_BASE alpine` |

| `BOX\_DIR` | Sets the working directory inside the container. | `BOX\_DIR /app` |

| `BOX\_COPY` | Copies files from host to container (recursive). | `BOX\_COPY . .` |

| `BOX\_EXEC` | Runs a shell command during the build. | `BOX\_EXEC apk add python3` |

| `BOX\_ENV` | Sets a persistent environment variable. | `BOX\_ENV FLASK\_ENV=dev` |

| `BOX\_START`| The command to run when the container starts. | `BOX\_START \["python", "app.py"]` |



\### 2. Basic Build \& Run



\*\*Build an image:\*\*

\# Syntax: lbox build -t <tag\_name> <path>

lbox build -t my-app .



\*\*Run a container:\*\*

\# Syntax: lbox run \[options] <image\_name> \[override\_command]

lbox run -p 8080:5000 -d my-app



\* `-p 8080:5000`: Maps host port 8080 to container port 5000.

\* `-d`: Runs in detached mode (background).



\### 3. Orchestration (LockBox Create)

LockBox can orchestrate entire stacks using a `lockbox-create.yml` file.



\*\*Example `lockbox-create.yml`:\*\*



services:

&nbsp; # Service 1: Web Server

&nbsp; web:

&nbsp;   build: .                  # Looks for app.lbox in current dir

&nbsp;   image: web-v1

&nbsp;   ports:

&nbsp;     - "8080:5000"

&nbsp;   environment:

&nbsp;     - APP\_ENV=production

&nbsp;   auto-update:

&nbsp;     enabled: true           # Hot Reload: Rebuilds if local files change



&nbsp; # Service 2: Database (Custom Build)

&nbsp; database:

&nbsp;   build: ./db               # Looks for app.lbox in /db subfolder

&nbsp;   image: redis-custom



\*\*Commands:\*\*

\* \*\*Start Stack:\*\* `lbox create up`

\* \*\*Stop Stack:\*\* `lbox create down`



---



\## ⚙️ Architecture \& Networking



\### Networking (DNS Injection)

LockBox v0.1 uses a \*\*"DNS Injection"\*\* strategy to allow containers to talk to each other:

1\.  \*\*Discovery:\*\* When `lbox create up` runs, the engine scans the OS (prioritizing `172.x.x.x` addresses on WSL) to find the IPs of all containers.

2\.  \*\*Injection:\*\* It pauses execution and writes these IP addresses into the `/etc/hosts` file of \*every\* running container in the stack.

3\.  \*\*Result:\*\* Your app can connect to `database` (the service name in YAML), and it resolves to the correct internal IP automatically.



\### Auto-Update Daemon

1\.  When `auto-update: enabled` is set in YAML, LockBox spawns a hidden background process.

2\.  It monitors the MD5 checksum of your local project files (or `ETag` for remote URLs).

3\.  If a change is detected, it triggers a `stop` -> `rm` -> `build` -> `run` cycle seamlessly.



---



\## 📂 Project Structure



LockBox/

├── src/

│   ├── lbox.py            # The Core Engine (CLI, Build, Runtime)

├── images/                # Built .tar images and .json metadata

├── containers/            # Active container filesystems (RootFS)

├── state/                 # PID files and running container state

├── logs/                  # Console logs for detached containers

└── base\_images/           # Cache for alpine.tar.gz

