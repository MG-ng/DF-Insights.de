from requests import get

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


def fetch_json(url, allow_not_found=False):
    response = get(url, timeout=60)
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


def main():
    print(f"Importing {len(SMARD_FILTERS)} raw SMARD filters.")
    insert_timestamp_rows()
    insert_filter_values()
    print("SMARD import completed successfully.")


if __name__ == "__main__":
    main()
