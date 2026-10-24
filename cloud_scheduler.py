"""Client for the Cloudflare Worker that publishes scheduled posts.

The Worker (cloud_scheduler/src/index.js) runs every minute in the cloud,
so scheduled posts go out while the Mac is asleep. This module talks to its
small HTTP API; CLOUD_SCHEDULER_URL and CLOUD_SCHEDULER_SECRET live in .env.
"""

import requests

from app_settings import get_setting


class CloudSchedulerError(RuntimeError):
    """Raised when the cloud scheduler cannot be reached or refuses a job."""


def cloud_configured():
    """True when the Worker's address and secret are in .env."""
    return bool(get_setting("CLOUD_SCHEDULER_URL") and get_setting("CLOUD_SCHEDULER_SECRET"))


class CloudScheduler:
    def __init__(self, url=None, secret=None, session=None):
        self._url = (url or get_setting("CLOUD_SCHEDULER_URL") or "").rstrip("/")
        self._secret = secret or get_setting("CLOUD_SCHEDULER_SECRET")
        if not self._url or not self._secret:
            raise CloudSchedulerError(
                "The cloud scheduler is not set up (CLOUD_SCHEDULER_URL and "
                "CLOUD_SCHEDULER_SECRET in .env)."
            )
        self._session = session or requests.Session()

    def _call(self, method, path, payload=None, params=None):
        try:
            response = self._session.request(
                method,
                f"{self._url}/{path.lstrip('/')}",
                json=payload,
                params=params,
                headers={"Authorization": f"Bearer {self._secret}"},
                timeout=30,
            )
        except requests.RequestException as error:
            raise CloudSchedulerError(
                f"Could not reach the cloud scheduler ({type(error).__name__})."
            ) from error
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code >= 400:
            raise CloudSchedulerError(
                f"Cloud scheduler returned HTTP {response.status_code}: "
                f"{data.get('error', 'no details')}"
            )
        return data

    def health(self):
        return self._call("GET", "health")

    def put_tokens(self, tokens):
        return self._call("PUT", "tokens", tokens)

    def put_job(self, post_id, job):
        return self._call("PUT", f"jobs/{post_id}", job)

    def delete_job(self, post_id):
        return self._call("DELETE", f"jobs/{post_id}")

    def get_jobs(self, post_ids):
        if not post_ids:
            return []
        return self._call("GET", "jobs", params={"ids": ",".join(post_ids)}).get("jobs", [])

    def run_now(self):
        return self._call("POST", "run")
