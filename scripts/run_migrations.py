#!/usr/bin/env python
"""Helper script to run Alembic migrations via `python scripts/run_migrations.py`."""

from __future__ import annotations

from alembic.config import main as alembic_main


def run():
    """Run the Alembic upgrade command."""
    alembic_main(argv=["upgrade", "head"])


if __name__ == "__main__":
    run()
