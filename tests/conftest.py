import os
import time

import docker
import pytest
from sqlalchemy import create_engine, MetaData
from sqlalchemy.engine.url import URL
from sqlalchemy.orm import Session

from classes import Base


# Constants
GIZMOSQL_PORT = 31337


# Function to wait for a specific log message indicating the container is ready
def wait_for_container_log(container, timeout=30, poll_interval=1, ready_message="GizmoSQL server - started"):
    start_time = time.time()
    while time.time() - start_time < timeout:
        # Get the logs from the container
        logs = container.logs().decode('utf-8')

        # Check if the ready message is in the logs
        if ready_message in logs:
            return True

        # Wait for the next poll
        time.sleep(poll_interval)

    raise TimeoutError(f"Container did not show '{ready_message}' in logs within {timeout} seconds.")


@pytest.fixture(scope="session")
def gizmosql_server():
    # Initialize Docker client
    client = docker.from_env()

    container = client.containers.run(
        image="gizmodata/gizmosql:latest",
        name="sqlalchemy-gizmosql-test",
        detach=True,
        remove=True,
        tty=True,
        init=True,
        ports={f"{GIZMOSQL_PORT}/tcp": GIZMOSQL_PORT},
        environment={"GIZMOSQL_USERNAME": "gizmosql_username",
                     "GIZMOSQL_PASSWORD": "gizmosql_password",
                     "TLS_ENABLED": "1",
                     "PRINT_QUERIES": "1"
                     },
        stdout=True,
        stderr=True
    )

    # Wait for the container to be ready
    wait_for_container_log(container)

    yield container

    print(f"Container logs: {container.logs().decode('utf-8')}")
    container.stop()


@pytest.fixture(scope="session")
def engine(gizmosql_server):
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
    engine = create_engine(url=url, echo=True)

    return engine


@pytest.fixture(scope="session")
def session_and_metadata(engine):
    # Create all tables defined in the ORM models (if they don't exist)
    Base.metadata.create_all(bind=engine)
    time.sleep(1)

    # Yield both the session and the metadata as a tuple
    with Session(bind=engine) as session:
        yield session, Base.metadata
