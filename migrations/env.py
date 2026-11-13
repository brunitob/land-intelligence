from alembic import context
from sqlalchemy import engine_from_config, pool

from patagonia_land.config import get_settings
from patagonia_land.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # Tablas internas de PostGIS/tiger no son nuestras.
    if type_ == "table" and reflected and compare_to is None:
        return False
    return True


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.",
                                     poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
