# ──────────────────────────────────────────────────────────────────────────────
# astrolol — shared base image
#
# Runs as root inside the container (standard for dev containers — the
# container boundary is the security perimeter, not the uid).  Pip and npm
# root-user warnings are silenced via environment variables.
#
# Two compose files consume this image:
#   docker-compose.yml      — production: source baked in, UI pre-built
#   docker-compose-dev.yml  — development: source bind-mounted, Vite HMR
# ──────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common nodejs npm
RUN apt-add-repository ppa:mutlaqja/ppa
# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        indi-bin astap-cli curl gsc gsc-data \
        python3 python3-pip python-is-python3 \
        && rm -rf /var/lib/apt/lists/*
RUN curl -L -o d05_star_database.deb\
    "https://master.dl.sourceforge.net/project/astap-program/star_databases/d05_star_database.deb" \
    && dpkg -i "d05_star_database.deb" \
    && rm -f "d05_star_database.deb"
# ── Python dependencies ───────────────────────────────────────────────────────
# Silence pip's root-user warning and version-check noise.
ENV PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY vendor /app/vendor
# Stub install: resolves and caches all deps in the image without needing the
# real source.  PYTHONPATH=/app (set below) makes the bind-mounted source
# importable at runtime without a separate "pip install -e ." on startup.
RUN mkdir -p astrolol && touch astrolol/__init__.py \
    && pip install --no-cache-dir -e ".[dev,indi]" --break-system-packages \
    && rm -rf astrolol astrolol.egg-info

# ── Node dependencies ─────────────────────────────────────────────────────────
# Installed here so the ui_node_modules named volume is seeded from the image
# on first run (Docker copies image content into an empty named volume).
# IMPORTANT: after any change to ui/package.json, run
#   docker compose -f docker-compose-dev.yml down -v && docker compose -f docker-compose-dev.yml up
# to drop the stale volume so it is reseeded from the new image.
COPY ui/package.json ui/package-lock.json ./ui/
RUN npm --prefix ./ui ci --silent

# ── Application source + UI build (production) ───────────────────────────────
# Copy the full source tree and build the UI.  In development the bind-mount
# shadows these files, so they are only used in the production image.
COPY . /app/
RUN npm --prefix ./ui run build

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONPATH=/app
WORKDIR /app
