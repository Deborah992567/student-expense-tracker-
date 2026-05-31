from logging.config import fileConfig
from alembic import context
from sqlalchemy import engine_from_config, pool
import os
import sys
from pathlib import Path

# make sure backend package is importable
if __package__ in {None, ''}:
    # ensure project root is on sys.path so `import backend` resolves
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from backend.config import get_settings
from backend.database import engine
from backend import models

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except Exception:
        # ignore missing/partial logging config sections when running in-project
        pass

target_metadata = models.Base.metadata

def run_migrations_online():
    connectable = engine
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    raise RuntimeError("Alembic offline mode not supported in this helper")
else:
    run_migrations_online()
