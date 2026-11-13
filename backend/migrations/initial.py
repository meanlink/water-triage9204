import logging
from sqlalchemy import text
from src.config.database import Base, engine
from src import models

# Columns added after the first release. Existing deployments are upgraded in place
# so historical batches and their analyses stay readable after the code catches up.
COLUMNS = {
    'datasets': {
        'parent_dataset_id': 'INTEGER REFERENCES datasets(id)',
        'revision': 'INTEGER NOT NULL DEFAULT 1',
        'merge_summary': 'JSON',
    },
}


def _existing_columns(connection, table):
    if engine.dialect.name == 'sqlite':
        return {row[1] for row in connection.execute(text(f'PRAGMA table_info("{table}")'))}
    return {row[0] for row in connection.execute(text(
        'SELECT column_name FROM information_schema.columns WHERE table_name = :name'
    ), {'name': table})}


def migrate():
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, wanted in COLUMNS.items():
            existing = _existing_columns(connection, table)
            for column, ddl in wanted.items():
                if column in existing:
                    continue
                if engine.dialect.name == 'sqlite':
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))
                else:
                    connection.execute(text(f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS {column} {ddl}'))
                logging.info('Upgraded %s.%s', table, column)


if __name__ == '__main__':
    migrate()
