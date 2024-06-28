# SQLAlchemy Flight SQL ADBC Dialect 

Basic SQLAlchemy dialect for the [Flight SQL Server Example](https://github.com/voltrondata/flight-sql-server-example)

## Installation

### Option 1 - from PyPi
```sh
$ pip install sqlalchemy-flight-sql-adbc-dialect
```

### Option 2 - from source - for development
```shell
git clone https://github.com/prmoore77/sqlalchemy_flight_sql_adbc_dialect.git

cd sqlalchemy_flight_sql_adbc_dialect

# Create the virtual environment
python3 -m venv .venv

# Activate the virtual environment
. .venv/bin/activate

# Upgrade pip, setuptools, and wheel
pip install --upgrade pip setuptools wheel

# Install SQLAlchemy Flight SQL ADBC Dialect - in editable mode with dev dependencies
pip install --editable .[dev]
```

### Note
For the following commands - if you running from source and using `--editable` mode (for development purposes) - you will need to set the PYTHONPATH environment variable as follows:
```shell
export PYTHONPATH=$(pwd)/src
```

## Usage

Once you've installed this package, you should be able to just use it, as SQLAlchemy does a python path search

### Start a Flight SQL Server - example below - see https://github.com/voltrondata/flight-sql-server-example for more details
```bash
docker run --name flight-sql \
           --detach \
           --rm \
           --tty \
           --init \
           --publish 31337:31337 \
           --env TLS_ENABLED="1" \
           --env FLIGHT_PASSWORD="flight_password" \
           --env PRINT_QUERIES="1" \
           --pull missing \
           voltrondata/flight-sql:latest
```

### Connect with the SQLAlchemy Flight SQL ADBC Dialect
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


# Build the SQLAlchemy URL
url = URL(drivername="flight_sql",
          host="localhost",
          port=31337,
          database="default",
          username=os.getenv("FLIGHT_USERNAME", "flight_username"),
          password=os.getenv("FLIGHT_PASSWORD", "flight_password"),
          query={"disableCertificateVerification": "True", "useEncryption": "True"},
          )

# Create the engine and create the table
engine = create_engine(url=url)
Base.metadata.create_all(bind=engine)

# Reflect the metadata
metadata = MetaData()
metadata.reflect(bind=engine)

# Print out tables
for table_name in metadata.tables:
    print(f"Table name: {table_name}")

# Create a session
with Session(bind=engine) as session:
    # ORM
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
```

### Credits
Much code and inspiration was taken from repo: https://github.com/Mause/duckdb_engine
