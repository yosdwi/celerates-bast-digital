from logging.config import fileConfig

from alembic import context
from psycopg import conninfo
from sqlalchemy import create_engine, pool

from digital_bast.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def database_url() -> str:
    settings = get_settings()
    if settings.database_dsn is None:
        return config.get_main_option("sqlalchemy.url")
    return conninfo.make_conninfo(settings.database_dsn.get_secret_value())


def run_migrations_offline() -> None:
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        database_url().replace("postgresql://", "postgresql+psycopg://", 1),
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
