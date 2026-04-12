# ──────────────────────────────────────────────────────────────────────────────
# astrolol — development image
#
# Runs as root inside the container (standard for dev containers — the
# container boundary is the security perimeter, not the uid).  Pip and npm
# root-user warnings are silenced via environment variables.
#
# The source tree is NOT baked in; it is bind-mounted at runtime so code
# changes take effect immediately without rebuilding.  Rebuilding is only
# needed when pyproject.toml or ui/package.json change.
# ──────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim

# ── System packages ───────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        indi-bin \
        nodejs \
        npm \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies ───────────────────────────────────────────────────────
# Silence pip's root-user warning and version-check noise.
ENV PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
# Stub install: resolves and caches all deps in the image without needing the
# real source.  PYTHONPATH=/app (set below) makes the bind-mounted source
# importable at runtime without a separate "pip install -e ." on startup.
RUN mkdir -p astrolol && touch astrolol/__init__.py \
    && pip install --no-cache-dir -e ".[dev,indi]" \
    && rm -rf astrolol astrolol.egg-info

# ── Node dependencies ─────────────────────────────────────────────────────────
# Installed here so the ui_node_modules named volume is seeded from the image
# on first run (Docker copies image content into an empty named volume).
COPY ui/package.json ui/package-lock.json ./ui/
RUN npm --prefix ./ui ci --silent

# ── Runtime environment ───────────────────────────────────────────────────────
ENV PYTHONPATH=/app
WORKDIR /app
