"""
Upload the four synthetic CSVs under ./output/ to a BigQuery sandbox dataset.

The source dataset (`gtm_analytics`) holds **exactly** the four tables the
assignment specifies — sales_reps, accounts, contracts, daily_usage_logs —
and nothing else. The archetype label file written alongside them
(`_account_archetypes.csv`) is generator provenance / eval ground truth,
not a source-of-truth table; it stays on local disk and is consumed
directly by the eval harness and dashboard.

Env vars:
  GOOGLE_CLOUD_PROJECT   (required)  — e.g. my-gtm-sandbox
  BQ_DATASET             (optional)  — default: gtm_analytics
  BQ_LOCATION            (optional)  — default: US
  BQ_RECREATE            (optional)  — "1" to drop+recreate the dataset first

Auth:
  Run `gcloud auth application-default login` once before using this script.

Run: python upload_to_bq.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from google.cloud import bigquery
from google.api_core.exceptions import NotFound

import config as C

OUT_DIR = Path(__file__).parent / "output"


# -------- schemas ----------------------------------------------------------

SCHEMAS: dict[str, list[bigquery.SchemaField]] = {
    "sales_reps": [
        bigquery.SchemaField("rep_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("region", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("segment", "STRING", mode="REQUIRED"),
    ],
    "accounts": [
        bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("company_name", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("industry", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("rep_id", "STRING", mode="REQUIRED"),
    ],
    "contracts": [
        bigquery.SchemaField("contract_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("account_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("start_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("end_date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("annual_commit_dollars", "NUMERIC", mode="REQUIRED"),
        bigquery.SchemaField("included_monthly_compute_credits", "INT64", mode="REQUIRED"),
    ],
    "daily_usage_logs": [
        # log_id kept STRING for readability; account_id NULLABLE because
        # the injected "bad account_id" orphans are intentionally unknown.
        bigquery.SchemaField("log_id", "STRING", mode="REQUIRED"),
        bigquery.SchemaField("account_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
        bigquery.SchemaField("compute_credits_consumed", "NUMERIC", mode="REQUIRED"),
    ],
}

# daily_usage_logs is by far the biggest table. In a production project we'd
# partition by `date` (DAY or MONTH) for predicate pruning — but BQ Sandbox
# forces a 60-day partition expiration, which silently evicts any partition
# older than "today minus 60 days" immediately on load. For the sandbox we
# therefore only cluster (clustering has no expiration side-effect) and
# add partitioning back once we're on a billed project.
# Override with env var BQ_PARTITION=1 if you're NOT in sandbox.
_WANT_PARTITION = os.environ.get("BQ_PARTITION") == "1"
PARTITIONED_TABLES = {
    "daily_usage_logs": {
        "time_partitioning": bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.MONTH,
            field="date",
        ) if _WANT_PARTITION else None,
        "clustering_fields": ["account_id"],
    },
}


# -------- helpers ----------------------------------------------------------

def _get_client() -> bigquery.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        sys.exit("ERROR: set GOOGLE_CLOUD_PROJECT env var to your BQ sandbox project id.")
    return bigquery.Client(project=project)


def _ensure_dataset(client: bigquery.Client, dataset_id: str, location: str) -> None:
    ref = bigquery.DatasetReference(client.project, dataset_id)
    if os.environ.get("BQ_RECREATE") == "1":
        try:
            client.delete_dataset(ref, delete_contents=True, not_found_ok=True)
            print(f"  dropped existing dataset {client.project}.{dataset_id}")
        except Exception as e:
            print(f"  WARN: could not drop dataset: {e}")
    try:
        client.get_dataset(ref)
        print(f"  dataset exists: {client.project}.{dataset_id}")
    except NotFound:
        ds = bigquery.Dataset(ref)
        ds.location = location
        ds.description = "GTM North Star metric take-home — synthetic SaaS dataset"
        client.create_dataset(ds)
        print(f"  created dataset {client.project}.{dataset_id} in {location}")


def _load_csv(client: bigquery.Client, dataset_id: str, table_name: str,
              csv_path: Path) -> int:
    table_ref = bigquery.TableReference(
        bigquery.DatasetReference(client.project, dataset_id), table_name
    )

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.CSV,
        skip_leading_rows=1,
        schema=SCHEMAS[table_name],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        allow_quoted_newlines=True,
    )
    part = PARTITIONED_TABLES.get(table_name)
    if part:
        if part.get("time_partitioning"):
            job_config.time_partitioning = part["time_partitioning"]
        if part.get("clustering_fields"):
            job_config.clustering_fields = part["clustering_fields"]

    with csv_path.open("rb") as f:
        job = client.load_table_from_file(f, table_ref, job_config=job_config)
    job.result()  # raises on error

    table = client.get_table(table_ref)
    return table.num_rows


# -------- main -------------------------------------------------------------

def main():
    dataset_id = os.environ.get("BQ_DATASET", C.DEFAULT_DATASET)
    location = os.environ.get("BQ_LOCATION", C.DEFAULT_LOCATION)

    client = _get_client()
    print(f"Project:  {client.project}")
    print(f"Dataset:  {dataset_id}")
    print(f"Location: {location}\n")

    print("[1/2] Ensuring dataset ...")
    _ensure_dataset(client, dataset_id, location)

    # One-time cleanup: earlier versions of this script also uploaded an
    # `account_archetypes` table to the source dataset. The assignment
    # specifies 4 source tables, so we now keep archetype labels as local
    # generator provenance only. Drop the stale table if a prior run
    # left one behind — no-op on a fresh clone.
    legacy = bigquery.TableReference(
        bigquery.DatasetReference(client.project, dataset_id), "account_archetypes"
    )
    try:
        client.delete_table(legacy, not_found_ok=True)
        print("  (cleaned up legacy account_archetypes table if present)")
    except Exception as e:
        print(f"  WARN: could not drop legacy account_archetypes: {e}")

    print("\n[2/2] Loading CSVs ...")
    # The 4 brief-spec tables — and only these — land in BQ. The
    # generator also writes `_account_archetypes.csv` in the same output
    # directory, but that file is eval ground truth (which archetype the
    # generator injected per account), not a warehouse source table, so
    # it stays on local disk and is consumed directly by the eval harness
    # and dashboard.
    order = [
        ("sales_reps",       "sales_reps.csv"),
        ("accounts",         "accounts.csv"),
        ("contracts",        "contracts.csv"),
        ("daily_usage_logs", "daily_usage_logs.csv"),
    ]
    for table_name, filename in order:
        csv = OUT_DIR / filename
        if not csv.exists():
            sys.exit(f"ERROR: {csv} not found — run `python generate_data.py` first.")
        print(f"  loading {table_name} ({csv.stat().st_size/1e6:.1f} MB) ...", end=" ", flush=True)
        n = _load_csv(client, dataset_id, table_name, csv)
        print(f"{n:,} rows")

    print(f"\nDone. Tables loaded into {client.project}.{dataset_id}")
    print("Sanity query (copy into BQ console):")
    print(f"  SELECT COUNT(*) FROM `{client.project}.{dataset_id}.daily_usage_logs`;")


if __name__ == "__main__":
    main()
