import re
import warnings
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Type

import sqlalchemy.exc
from adbc_driver_flightsql import dbapi as gizmosql, DatabaseOptions, ConnectionOptions
from sqlalchemy import pool
from sqlalchemy import types as sqltypes
from sqlalchemy.engine.default import DefaultDialect
from .sqlalchemy_interfaces import ReflectedColumn, ReflectedPrimaryKeyConstraint, ReflectedForeignKeyConstraint, \
    ReflectedCheckConstraint
from sqlalchemy.engine.url import URL
from adbc_driver_manager import OperationalError


__version__ = "0.0.22"

if TYPE_CHECKING:
    from sqlalchemy.base import Connection
    from sqlalchemy.engine.interfaces import _IndexDict


class GizmoSQLWarning(Warning):
    pass


class ConnectionWrapper:
    __c: "Connection"
    notices: List[str]
    autocommit = None
    closed = False

    def __init__(self, c: gizmosql.Connection) -> None:
        self.__c = c
        self.notices = list()

    def cursor(self) -> gizmosql.Cursor:
        return self.__c.cursor()

    def fetchmany(self, size: Optional[int] = None) -> List:
        return self.__c.fetchmany(size)

    @property
    def c(self) -> "Connection":
        warnings.warn(
            "Directly accessing the internal connection object is deprecated (please go via the __getattr__ impl)",
            DeprecationWarning,
        )
        return self.__c

    def __getattr__(self, name: str) -> Any:
        return getattr(self.__c, name)

    @property
    def connection(self) -> "Connection":
        return self

    def close(self) -> None:
        self.__c.close()

    @property
    def rowcount(self) -> int:
        return self.cursor().rowcount

    def executemany(
            self,
            statement: str,
            parameters: Optional[List[Dict]] = None,
            context: Optional[Any] = None,
    ) -> None:
        with self.cursor() as cur:
            cur.executemany(statement, parameters)
            _ = cur.fetchall()

    def execute(
            self,
            statement: str,
            parameters: Optional[Tuple] = None,
            context: Optional[Any] = None,
    ) -> None:
        try:
            if statement.lower() == "commit":  # this is largely for ipython-sql
                self.__c.commit()
            elif statement.lower() == "register":
                assert parameters and len(parameters) == 2, parameters
                view_name, df = parameters
                self.__c.register(view_name, df)
            else:
                with self.__c.cursor() as cur:
                    cur.execute(statement, parameters)
                    _ = cur.fetchall()
        except RuntimeError as e:
            if e.args[0].startswith("Not implemented Error"):
                raise NotImplementedError(*e.args) from e
            elif (
                    e.args[0]
                    == "TransactionContext Error: cannot commit - no transaction is active"
            ):
                return
            else:
                raise e


class GizmoSQLDialect(DefaultDialect):
    name = "gizmosql"
    driver = "adbc"
    _has_events = False
    supports_statement_cache = True
    supports_comments = False
    supports_sane_rowcount = False
    supports_server_side_cursors = False
    postfetch_lastrowid = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    def create_connect_args(self, url):
        opts = url.translate_connect_args()
        username = opts.get('username', None)
        password = opts.get('password', None)
        host = opts.get('host', None)
        port = opts.get('port', None)
        database = opts.get('database', None)

        # Get Query parameters
        query_dict = dict(url.query)
        use_encryption = query_dict.pop('useEncryption', None)
        disable_certificate_verification = query_dict.pop('disableCertificateVerification', None)
        args = dict()
        kwargs = dict(host=host,
                      port=port,
                      database=database,
                      username=username,
                      password=password,
                      use_encryption=use_encryption,
                      disable_certificate_verification=disable_certificate_verification,
                      **query_dict
                      )

        # Assuming the connection arguments for your custom DB
        return (args, kwargs)

    def connect(self, *args, **kwargs) -> "Connection":
        protocol: str = "grpc"

        use_encryption: bool = (kwargs.pop("use_encryption", "False") or "False").lower() == "true"

        if use_encryption:
            protocol += "+tls"

        disable_certificate_verification: bool = (kwargs.pop("disable_certificate_verification", "False") or "False").lower() == "true"

        uri = f"{protocol}://{kwargs.pop('host')}:{kwargs.pop('port')}"

        database = kwargs.pop('database', None)
        username = kwargs.pop('username')
        password = kwargs.pop('password')

        db_kwargs = {DatabaseOptions.TLS_SKIP_VERIFY.value: str(disable_certificate_verification).lower()}

        if database is not None:
            db_kwargs["database"] = database
        if username is not None:
            db_kwargs["username"] = username
        if password is not None:
            db_kwargs["password"] = password

        # Add any remaining query args as connection kwargs (RPC headers)
        conn_kwargs = dict()
        for key, value in kwargs.items():
            conn_kwargs[f"{ConnectionOptions.RPC_CALL_HEADER_PREFIX.value}{key}"] = value

        conn = gizmosql.connect(uri=uri,
                                db_kwargs=db_kwargs,
                                conn_kwargs=conn_kwargs
                                )

        # Add a notices attribute for the PostgreSQL / DuckDB dialect...
        setattr(conn, "notices", ["n/a"])

        return ConnectionWrapper(conn)

    def on_connect(self) -> None:
        pass

    @classmethod
    def get_pool_class(cls, url: URL) -> Type[pool.Pool]:
        return pool.QueuePool

    @classmethod
    def import_dbapi(cls):
        return gizmosql

    @classmethod
    def dbapi(cls):
        return cls.import_dbapi()

    def _get_server_version_info(self, connection: "Connection") -> Tuple[int, int]:
        return (8, 0)

    def get_default_isolation_level(self, connection: "Connection") -> None:
        raise NotImplementedError()

    def do_execute(self, cursor, statement, parameters, context=None):
        cursor.execute(statement, parameters)
        if context.isddl or context.compiled.statement.is_dml:
            _ = cursor.fetchall()

    def do_rollback(self, connection: "Connection") -> None:
        with connection.cursor() as cur:
            cur.execute("rollback")
            try:
                _ = cur.fetchall()
            except OperationalError as e:
                if "TransactionContext Error: cannot rollback - no transaction is active" in e.args[0]:
                    pass

    def do_begin(self, connection: "Connection") -> None:
        with connection.cursor() as cur:
            cur.execute("begin")
            _ = cur.fetchall()

    def do_commit(self, connection: "Connection") -> None:
        with connection.cursor() as cur:
            cur.execute("commit")
            _ = cur.fetchall()

    def get_schema_names(
            self,
            connection: "Connection",
            **kw: Any,
    ) -> Any:
        s = """
            SELECT DISTINCT table_schema AS schema_name
              FROM information_schema.tables
             WHERE table_catalog = current_database()
             ORDER BY 1 ASC
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s)
            rs = cur.fetchall()

        return [row[0] for row in rs]

    def get_table_names(
            self,
            connection: "Connection",
            schema: Optional[Any] = None,
            include: Optional[Any] = None,
            **kw: Any,
    ) -> Any:
        s = """
            SELECT table_name 
              FROM information_schema.tables
             WHERE table_catalog = current_database()
               AND table_type = 'BASE TABLE'
               AND table_schema = ?
            ORDER BY 1 ASC
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main"])
            rs = cur.fetchall()

        return [row[0] for row in rs]

    def get_columns(
            self,
            connection: "Connection",
            table_name: str,
            schema: Optional[str] = None,
            **kw: Any,
    ) -> List[ReflectedColumn]:
        s = """
            SELECT column_name
                 , data_type
                 , is_nullable
                 , column_default
              FROM information_schema.columns
             WHERE table_catalog = current_database()
               AND table_schema = ?
               AND table_name = ?
            ORDER BY ordinal_position ASC
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main",
                                                 table_name
                                                 ]
                        )
            rs = cur.fetchall()

        columns = []
        for column_name, data_type, is_nullable, column_default in rs:
            columns.append(ReflectedColumn(name=column_name,
                                           type=self._get_column_type(data_type=data_type),
                                           nullable=(is_nullable == "YES"),
                                           default=column_default
                                           )
                           )

        return columns

    @staticmethod
    def _get_column_type(data_type: str):
        # Map database-specific data types to SQLAlchemy types
        if data_type == 'VARCHAR':
            return sqltypes.String
        elif data_type == 'INTEGER':
            return sqltypes.Integer
        elif data_type == 'DATE':
            return sqltypes.Date
        elif data_type == 'DATETIME':
            return sqltypes.DateTime
        elif data_type == "TIMESTAMP":
            return sqltypes.TIMESTAMP
        elif data_type == "TIME":
            return sqltypes.TIME
        elif data_type == "BIGINT":
            return sqltypes.BigInteger
        elif data_type == "TINYINT":
            return sqltypes.SmallInteger
        elif re.match(pattern="^DECIMAL", string=data_type):
            return sqltypes.Numeric
        elif data_type == "DOUBLE":
            return sqltypes.Float
        elif data_type == "BOOLEAN":
            return sqltypes.Boolean
        elif re.match(pattern="^STRUCT", string=data_type):
            return sqltypes.JSON
        else:
            # Try a catch-all for any other data types
            try:
                return getattr(sqltypes, data_type)
            except AttributeError:
                raise ValueError(f"Unsupported column type: {data_type}")

    def get_view_names(
            self,
            connection: "Connection",
            schema: Optional[Any] = None,
            include: Optional[Any] = None,
            **kw: Any,
    ) -> Any:
        s = """
            SELECT table_name
              FROM information_schema.tables
             WHERE table_catalog = current_database()
               AND table_type = 'VIEW'
               AND table_schema = ?
             ORDER BY 1
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main"])
            rs = cur.fetchall()

        return [row[0] for row in rs]

    def has_table(
        self,
        connection: "Connection",
        table_name: str,
        schema: Optional[str] = None,
        **kw: Any,
    ) -> bool:
        s = """
            SELECT 1
              FROM information_schema.tables
             WHERE table_catalog = current_database()
               AND table_schema = ?
               AND table_name = ?
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main",
                                                 table_name
                                                 ]
                        )
            row = cur.fetchone()

        return row is not None

    def get_pk_constraint(
            self,
            connection: "Connection",
            table_name: str,
            schema: Optional[str] = None,
            **kw: Any,
    ) -> ReflectedPrimaryKeyConstraint:
        return_value = None
        s = """
            SELECT constraint_name
                 , constraint_column_names
              FROM duckdb_constraints()
             WHERE constraint_type = 'PRIMARY KEY'
               AND database_name = current_database()
               AND schema_name = ?
               AND table_name = ?
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main",
                                                 table_name
                                                 ]
                        )
            row = cur.fetchall()

        for constraint_name, constrained_columns in row:
           return_value = ReflectedPrimaryKeyConstraint(name=constraint_name,
                                                        constrained_columns=constrained_columns
                                                        )

        return return_value

    def get_foreign_keys(
        self,
        connection: "Connection",
        table_name: str,
        schema: Optional[str] = None,
        **kw: Any,
    ) -> List[ReflectedForeignKeyConstraint]:
        return_value = []
        s = """
            SELECT
                 referenced_table          AS pk_table_name
               , table_name                AS fk_table_name
               , constraint_name
               , constraint_column_names   AS constrained_columns
               , schema_name               AS referred_schema
               , referenced_table          AS referred_table
               , referenced_column_names   AS referred_columns
            FROM duckdb_constraints()
            WHERE constraint_type = 'FOREIGN KEY'
              AND database_name = current_database()
              AND schema_name = ?
              AND table_name = ?
            ORDER BY constraint_name ASC
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main",
                                                 table_name
                                                 ]
                        )
            rs = cur.fetchall()

        for _, _, constraint_name, constrained_columns, referred_schema, referred_table, referred_columns in rs:
            return_value.append(ReflectedForeignKeyConstraint(name=constraint_name,
                                                              constrained_columns=constrained_columns,
                                                              referred_schema=referred_schema,
                                                              referred_table=referred_table,
                                                              referred_columns=referred_columns
                                                              )
                                )

        return return_value

    def get_check_constraints(
        self,
        connection: "Connection",
        table_name: str,
        schema: Optional[str] = None,
        **kw: Any,
    ) -> List[ReflectedCheckConstraint]:
        return_value = []
        s = """
            SELECT constraint_name
                 , expression AS sqltext
            FROM duckdb_constraints()
            WHERE constraint_type = 'CHECK'
              AND database_name = current_database()
              AND schema_name = ?
              AND table_name = ?
            """
        with connection.connection.cursor() as cur:
            cur.execute(operation=s, parameters=[schema if schema is not None else "main",
                                                 table_name
                                                 ]
                        )
            rs = cur.fetchall()

        for constraint_name, sqltext in rs:
            return_value.append(ReflectedCheckConstraint(name=constraint_name,
                                                         sqltext=sqltext
                                                         )
                                )

        return return_value
    def get_indexes(
            self,
            connection: "Connection",
            table_name: str,
            schema: Optional[str] = None,
            **kw: Any,
    ) -> List["_IndexDict"]:
        warnings.warn(
            "GizmoSQL ADBC SQLAlchemy driver doesn't yet support reflection on indices",
            GizmoSQLWarning,
        )
        return []
