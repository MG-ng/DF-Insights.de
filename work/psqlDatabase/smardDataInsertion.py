from psycopg2 import sql
from psycopg2.extras import execute_values
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import DB_PARAMS
from Helper import FILTER, TABLE_NAME_SMARD, FLAG, Resolution, FilterTranslations, OTHER_THAN_SMARD_FILTER_IDs
from QuerySimple import get_timestamp_buckets
from databaseSetup import insert_optional_data_in_batches


BASE_URL = "https://www.smard.de/app"
MAX_BUFFERED_ROWS = 10_000
SMARD_FILTERS = [
    (filter_id, FilterTranslations[FILTER.inverse[filter_id]])
    for filter_id in FILTER.values()
    if filter_id not in OTHER_THAN_SMARD_FILTER_IDs
]
NUMERIC_COLUMN_COUNT = len(SMARD_FILTERS)


def _create_session():
    session = Session()
    # SMARD answers the occasional request with a 5xx or drops it; retry those with a backoff
    retries = Retry(total=5, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=("GET",))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session


_session = _create_session()


def fetch_json(url, allow_not_found=False):
    response = _session.get(url, timeout=60)
    if allow_not_found and response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def data_row(timestamp, is_bucket_timestamp, region, resolution, column_index=None, value=None):
    values = [None] * NUMERIC_COLUMN_COUNT
    if column_index is not None:
        values[column_index] = value
    return timestamp, is_bucket_timestamp, region, resolution, *values


def flush_rows(rows, data_column):
    if not rows:
        return
    if not insert_optional_data_in_batches(DB_PARAMS, TABLE_NAME_SMARD, rows, data_column):
        raise RuntimeError(f"Failed to insert SMARD rows for {data_column!r}")
    rows.clear()


def insert_timestamp_rows():
    for resolution_enum in Resolution:
        resolution = resolution_enum.value
        for column_index, (current_filter, data_column) in enumerate(SMARD_FILTERS):
            index_url = f"{BASE_URL}/chart_data/{current_filter}/DE/index_{resolution}.json"
            index_data = fetch_json(index_url, allow_not_found=True)
            if index_data is None:
                continue

            buffered_rows = []
            for timestamp in index_data["timestamps"]:
                buffered_rows.append(
                    data_row(timestamp, True, "DE", resolution, column_index, FLAG)
                )

                bucket_url = (
                    f"{BASE_URL}/chart_data/{current_filter}/DE/"
                    f"{current_filter}_DE_{resolution}_{timestamp}.json"
                )
                bucket_data = fetch_json(bucket_url)
                for point_timestamp, point_value in bucket_data["series"]:
                    if point_value is not None:
                        buffered_rows.append(
                            data_row(point_timestamp, False, "DE", resolution)
                        )

                if len(buffered_rows) >= MAX_BUFFERED_ROWS:
                    flush_rows(buffered_rows, data_column)

            flush_rows(buffered_rows, data_column)


def insert_filter_values():
    for column_index, (current_filter, data_column) in enumerate(SMARD_FILTERS):
        rows, _ = get_timestamp_buckets(DB_PARAMS, TABLE_NAME_SMARD, data_column)
        if rows is None:
            raise RuntimeError(f"Failed to load timestamp buckets for {data_column!r}")

        for timestamp, region, resolution in rows:
            bucket_url = (
                f"{BASE_URL}/chart_data/{current_filter}/{region}/"
                f"{current_filter}_{region}_{resolution}_{timestamp}.json"
            )
            bucket_data = fetch_json(bucket_url)
            row_data = [
                data_row(point_timestamp, False, region, resolution, column_index, point_value)
                for point_timestamp, point_value in bucket_data["series"]
            ]
            flush_rows(row_data, data_column)


# ---------------------------------------------------------------------------
# Incremental update: only the newest buckets, used by updateDatabase.py
# ---------------------------------------------------------------------------

def latest_data_timestamps(connection, region="DE"):
    """{resolution: {column: newest timestamp (ms) with a real value, or None}} for all raw SMARD columns."""
    aggregates = sql.SQL(", ").join(
        sql.SQL("MAX(unix_timestamp_ms) FILTER (WHERE {column} IS NOT NULL AND {column} <> %s)").format(
            column=sql.Identifier(column.lower())
        )
        for _, column in SMARD_FILTERS
    )
    query = sql.SQL("SELECT resolution::text, {aggregates} FROM {table} WHERE region = %s GROUP BY resolution").format(
        aggregates=aggregates,
        table=sql.Identifier(TABLE_NAME_SMARD),
    )
    with connection.cursor() as cursor:
        cursor.execute(query, [FLAG] * len(SMARD_FILTERS) + [region])
        result = {resolution.value: dict.fromkeys(column for _, column in SMARD_FILTERS) for resolution in Resolution}
        for resolution, *latest in cursor.fetchall():
            result[resolution] = {column: value for (_, column), value in zip(SMARD_FILTERS, latest)}
    return result


def buckets_to_refresh(bucket_timestamps, latest_ms, overlap_buckets=1):
    """Bucket start timestamps to fetch again: the bucket holding latest_ms, all newer ones, and
    `overlap_buckets` older ones (SMARD revises recent values). None means nothing is stored yet."""
    bucket_timestamps = sorted(bucket_timestamps)
    if latest_ms is None or not bucket_timestamps:
        return []
    containing = 0
    for index, bucket in enumerate(bucket_timestamps):
        if bucket <= latest_ms:
            containing = index
    return bucket_timestamps[max(0, containing - overlap_buckets):]


def upsert_column_values(connection, data_column, rows):
    """rows: (timestamp_ms, is_bucket_timestamp, region, resolution, value) with non-null values."""
    if not rows:
        return
    statement = sql.SQL("""
        INSERT INTO {table} (unix_timestamp_ms, is_bucket_timestamp, region, resolution, {column})
        VALUES %s
        ON CONFLICT (unix_timestamp_ms, region, resolution)
        DO UPDATE SET {column} = EXCLUDED.{column},
                      is_bucket_timestamp = {table}.is_bucket_timestamp OR EXCLUDED.is_bucket_timestamp
    """).format(table=sql.Identifier(TABLE_NAME_SMARD), column=sql.Identifier(data_column.lower()))
    with connection.cursor() as cursor:
        execute_values(
            cursor,
            statement.as_string(connection),
            rows,
            template="(%s, %s, %s::region_type, %s::resolution_type, %s)",
            page_size=1000,
        )


def update_recent_smard_data(connection, fetch=fetch_json, overlap_buckets=1, since_ms=None, log=print):
    """Fetch only the newest SMARD buckets of every raw filter and resolution and upsert them.

    since_ms: refetch everything from this timestamp on instead of starting at the newest stored value
    (also fills columns that have no data yet). Returns the number of values written.
    """
    region = "DE"  # the full import only loads DE as well
    latest = latest_data_timestamps(connection, region)
    written = 0
    for resolution_enum in Resolution:
        resolution = resolution_enum.value
        for current_filter, data_column in SMARD_FILTERS:
            index_data = fetch(f"{BASE_URL}/chart_data/{current_filter}/{region}/index_{resolution}.json",
                               allow_not_found=True)
            if index_data is None:
                continue
            start_ms = since_ms if since_ms is not None else latest[resolution][data_column]
            buckets = buckets_to_refresh(index_data["timestamps"], start_ms, overlap_buckets)
            if not buckets:
                if since_ms is None:
                    log(f"  {data_column} ({resolution}): no stored values yet, skipped. "
                        "Run databaseSetupAll.py or pass --since to load it.")
                continue

            column_written = 0
            for bucket in buckets:
                bucket_data = fetch(
                    f"{BASE_URL}/chart_data/{current_filter}/{region}/"
                    f"{current_filter}_{region}_{resolution}_{bucket}.json"
                )
                rows = [
                    (point_timestamp, point_timestamp == bucket, region, resolution, point_value)
                    for point_timestamp, point_value in bucket_data["series"]
                    if point_value is not None and (since_ms is None or point_timestamp >= since_ms)
                ]
                upsert_column_values(connection, data_column, rows)
                column_written += len(rows)
            connection.commit()
            written += column_written
            log(f"  {data_column} ({resolution}): {len(buckets)} bucket(s), {column_written} values")
    return written


def main():
    print(f"Importing {len(SMARD_FILTERS)} raw SMARD filters.")
    insert_timestamp_rows()
    insert_filter_values()
    print("SMARD import completed successfully.")


if __name__ == "__main__":
    main()
