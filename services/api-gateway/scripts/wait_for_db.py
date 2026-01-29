import os
import time
from urllib.parse import urlparse

import psycopg2


def _to_sync_url(url: str) -> str:
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    return url


def _parse(url: str):
    parsed = urlparse(url)
    return {
        "dbname": parsed.path.lstrip("/"),
        "user": parsed.username,
        "password": parsed.password,
        "host": parsed.hostname,
        "port": parsed.port or 5432,
    }


def main():
    raw_url = os.getenv("DATABASE_URL_SYNC") or os.getenv("DATABASE_URL")
    if not raw_url:
        raise SystemExit("DATABASE_URL or DATABASE_URL_SYNC is not set")

    url = _to_sync_url(raw_url)
    params = _parse(url)
    timeout = int(os.getenv("DB_WAIT_TIMEOUT", "60"))
    start = time.time()

    while True:
        try:
            conn = psycopg2.connect(**params)
            conn.close()
            print("DB is ready")
            return
        except Exception as exc:
            if time.time() - start > timeout:
                raise SystemExit(f"DB not ready after {timeout}s: {exc}")
            time.sleep(2)


if __name__ == "__main__":
    main()
