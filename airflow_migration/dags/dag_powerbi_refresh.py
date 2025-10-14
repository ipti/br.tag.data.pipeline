from __future__ import annotations

import os
import requests
from typing import List

import pendulum
from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from src.utils.logs.logging_functions import get_logger

POWER_BI_DATASET_IDS = [
    "21fa7616-c26e-41d6-a86e-f5efbc17101a",
    "58710fc3-8f85-4d5d-9876-2a36a04b0ab5",
]
TIMEZONE = "America/Sao_Paulo"


def refresh_power_bi_datasets_func(dataset_ids: List[str]) -> None:
    """
    Authenticates with the Power BI API and triggers a refresh for a list of datasets.

    This function reads credentials (client_id, username, password) from
    environment variables prefixed with 'POWERBI_'. It first obtains an

    access token and then iterates through the provided list of dataset IDs,
    sending a POST request to the refresh endpoint for each one.
    If any refresh request fails, it collects the failed IDs and raises an
    AirflowException at the end to mark the task as failed.

    Args:
        dataset_ids (List[str]): A list of Power BI dataset IDs to be refreshed.

    Raises:
        ValueError: If required environment variables are not set.
        AirflowException: If one or more dataset refreshes fail.
    """
    logger = get_logger("power_bi_refresher")
    logger.info("--- Starting Power BI refresh process ---")

    try:
        username = os.getenv("POWERBI_USERNAME")
        password = os.getenv("POWERBI_PASSWORD")
        client_id = os.getenv("POWERBI_CLIENT_ID")
        token_url = "https://login.windows.net/common/oauth2/token"

        if not all([username, password, client_id]):
            raise ValueError(
                "Environment variables POWERBI_USERNAME, POWERBI_PASSWORD, "
                "and POWERBI_CLIENT_ID must be set."
            )

    except Exception as e:
        logger.error(f"Failed to read environment variables: {e}")
        raise

    token_payload = {
        "grant_type": "password",
        "client_id": client_id,
        "resource": "https://analysis.windows.net/powerbi/api",
        "scope": "openid",
        "username": username,
        "password": password,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    logger.info("Requesting access token...")
    token_response = requests.post(token_url, data=token_payload, headers=headers)
    token_response.raise_for_status()

    access_token = token_response.json().get("access_token")
    if not access_token:
        raise ValueError("Access token not found in API response.")

    logger.info("Access token obtained successfully.")

    refresh_headers = {"Authorization": f"Bearer {access_token}"}

    failed_datasets = []
    for dataset_id in dataset_ids:
        refresh_url = (
            f"https://api.powerbi.com/v1.0/myorg/datasets/{dataset_id}/refreshes"
        )
        logger.info(f"Triggering refresh for dataset ID: {dataset_id}...")

        try:
            refresh_response = requests.post(
                refresh_url, headers=refresh_headers, timeout=60
            )
            refresh_response.raise_for_status()

            if refresh_response.status_code == 202:
                logger.info(f"Refresh successfully queued for dataset {dataset_id}.")
            else:
                logger.warning(
                    f"Unexpected status for dataset {dataset_id}: "
                    f"{refresh_response.status_code} - {refresh_response.text}"
                )
        except requests.exceptions.RequestException as e:
            logger.error(f"ERROR trying to refresh dataset {dataset_id}: {e}")
            failed_datasets.append(dataset_id)

    if failed_datasets:
        raise AirflowException(
            f"Failed to refresh the following datasets: {failed_datasets}"
        )

    logger.info("--- Power BI refresh process finished successfully ---")


with DAG(
    dag_id="daily_power_bi_refresh",
    start_date=pendulum.datetime(2025, 10, 8, tz=TIMEZONE),
    schedule="30 3 * * *",
    catchup=False,
    tags=["bi", "powerbi"],
    doc_md="""
    ### Daily Power BI Refresh DAG

    This DAG automates the daily refresh of key Power BI datasets.
    
    **Schedule:** Runs every day at 3:30 AM (America/Sao_Paulo time).
    
    **Functionality:**
    1.  Authenticates with the Power BI API using credentials stored in
        environment variables (`POWERBI_CLIENT_ID`, `POWERBI_USERNAME`, `POWERBI_PASSWORD`).
    2.  Triggers a POST request to the `/refreshes` endpoint for each dataset
        ID defined in the `POWER_BI_DATASET_IDS` list.
    3.  The task will fail if any of the refresh requests do not succeed.
    """,
) as dag:

    trigger_bi_refresh = PythonOperator(
        task_id="trigger_all_refreshes",
        python_callable=refresh_power_bi_datasets_func,
        op_kwargs={"dataset_ids": POWER_BI_DATASET_IDS},
    )
