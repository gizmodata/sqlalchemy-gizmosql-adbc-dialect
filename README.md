# SQLAlchemy [GizmoSQL](https://github.com/gizmodata/GizmoSQL) ADBC Dialect 

[<img src="https://img.shields.io/badge/GitHub-gizmodata%2Fsqlalchemy--gizmosql--adbc--dialect-blue.svg?logo=Github">](https://github.com/gizmodata/sqlalchemy-gizmosql-adbc-dialect)
[![sqlalchemy-gizmosql-adbc-dialect-ci](https://github.com/gizmodata/sqlalchemy-gizmosql-adbc-dialect/actions/workflows/ci.yml/badge.svg)](https://github.com/gizmodata/sqlalchemy-gizmosql-adbc-dialect/actions/workflows/ci.yml)
[![Supported Python Versions](https://img.shields.io/pypi/pyversions/sqlalchemy--gizmosql--adbc--dialect)](https://pypi.org/project/sqlalchemy-gizmosql-adbc-dialect/)
[![PyPI version](https://badge.fury.io/py/sqlalchemy-gizmosql-adbc-dialect.svg)](https://badge.fury.io/py/sqlalchemy-gizmosql-adbc-dialect)
[![PyPI Downloads](https://img.shields.io/pypi/dm/sqlalchemy-gizmosql-adbc-dialect.svg)](https://pypi.org/project/sqlalchemy-gizmosql-adbc-dialect/)

Basic SQLAlchemy dialect for [GizmoSQL](https://github.com/gizmodata/GizmoSQL)

## Installation

### Option 1 - from PyPi
```sh
$ pip install sqlalchemy-gizmosql-adbc-dialect
```

### Option 2 - from source - for development
```shell
git clone https://github.com/gizmodata/sqlalchemy-gizmosql-adbc-dialect

cd sqlalchemy-gizmosql-adbc-dialect

# Create the virtual environment
python3 -m venv .venv

# Activate the virtual environment
. .venv/bin/activate

# Upgrade pip, setuptools, and wheel
pip install --upgrade pip setuptools wheel

# Install SQLAlchemy GizmoSQL ADBC Dialect - in editable mode with dev dependencies
pip install --editable .[dev]
```

### Note
For the following commands - if you are running from source and using `--editable` mode (for development purposes) - you will need to set the PYTHONPATH environment variable as follows:
```shell
export PYTHONPATH=$(pwd)/src
```

## Usage

Once you've installed this package, you should be able to just use it, as SQLAlchemy does a python path search

### Start a GizmoSQL Server - example below - see https://github.com/gizmodata/GizmoSQL for more details
```bash
docker run --name gizmosql \
           --detach \
           --rm \
           --tty \
           --init \
           --publish 31337:31337 \
           --env TLS_ENABLED="1" \
           --env GIZMOSQL_PASSWORD="gizmosql_password" \
           --env PRINT_QUERIES="1" \
           --pull missing \
           gizmodata/gizmosql:latest
```

### Connect with the SQLAlchemy GizmoSQL ADBC Dialect
```python
import os
import logging

from sqlalchemy import create_engine, MetaData, Table, select, Column, text, Integer, String, Sequence
from sqlalchemy.orm import Session
from sqlalchemy.orm import declarative_base
from sqlalchemy.engine.url import URL

# Setup logging
logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)


Base = declarative_base()


class FakeModel(Base):  # type: ignore
    __tablename__ = "fake"

    id = Column(Integer, Sequence("fakemodel_id_sequence"), primary_key=True)
    name = Column(String)


def main():
    # Build the URL
    url = URL.create(drivername="gizmosql",
                     host="localhost",
                     port=31337,
                     username=os.getenv("GIZMOSQL_USERNAME", "gizmosql_username"),
                     password=os.getenv("GIZMOSQL_PASSWORD", "gizmosql_password"),
                     query={"disableCertificateVerification": "True",
                            "useEncryption": "True"
                            }
                     )

    print(f"Database URL: {url}")

    engine = create_engine(url=url)
    Base.metadata.create_all(bind=engine)

    metadata = MetaData()
    metadata.reflect(bind=engine)

    for table_name in metadata.tables:
        print(f"Table name: {table_name}")

    with Session(bind=engine) as session:

        # Try ORM
        session.add(FakeModel(id=1, name="Joe"))
        session.commit()

        joe = session.query(FakeModel).filter(FakeModel.name == "Joe").first()

        assert joe.name == "Joe"

        # Execute some raw SQL
        results = session.execute(statement=text("SELECT * FROM fake")).fetchall()
        print(results)

        # Try a SQLAlchemy table select
        fake: Table = metadata.tables["fake"]
        stmt = select(fake.c.name)

        results = session.execute(statement=stmt).fetchall()
        print(results)


if __name__ == "__main__":
    main()
```

### Credits
Much code and inspiration was taken from repo: https://github.com/Mause/duckdb_engine
