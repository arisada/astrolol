# astrolol

Headless, modular, open-source astronomy platform. Runs on the machine attached to your telescope. Connect from any web browser, mobile app, or native client.

> Built out of frustration with Windows-only and buggy alternatives. Named honestly.

## Requirements

- Python 3.11+
- Linux (Raspberry Pi, mini-PC, or any machine at the scope)

## Install

```bash
git clone https://github.com/you/astrolol
cd astrolol
pip install -e ".[dev]"   # [dev] is required — it includes pytest, pytest-asyncio, etc.
```

## Run

```bash
python3 -m astrolol.main
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Test

```bash
python3 -m pytest tests/ -v
```

## Status

Early development. Not ready for use at the telescope.
