from alembic import context
from app.db import Base, engine

if context.is_offline_mode():
    raise RuntimeError("Run migrations against the SQLite database")
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
