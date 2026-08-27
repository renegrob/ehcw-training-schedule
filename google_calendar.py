"""
Google Calendar auth, reusing the same AWS SSM-backed service account secret
as the aws-ical-sync project (same Google service account, already shared
with the target calendars).
"""

import json
import os

import boto3
from google.oauth2 import service_account
from googleapiclient.discovery import build

SSM_PARAM_NAME = os.environ.get("SSM_PARAM_NAME", "/ical-sync/google-service-account")


def get_service_account_info() -> dict:
    ssm = boto3.client("ssm")
    resp = ssm.get_parameter(Name=SSM_PARAM_NAME, WithDecryption=True)
    return json.loads(resp["Parameter"]["Value"])


def get_calendar_service():
    info = get_service_account_info()
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/calendar"]
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)
