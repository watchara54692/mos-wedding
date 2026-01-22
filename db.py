import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")

pool = SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    dsn=DATABASE_URL,
    sslmode="require"
)


def get_conn():
    return pool.getconn()


def release_conn(conn):
    pool.putconn(conn)
