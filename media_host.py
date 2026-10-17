import mimetypes
from uuid import uuid4

from app_settings import SettingsError, require_settings


_R2_SETTINGS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_PUBLIC_BASE_URL",
)


class MediaHostError(RuntimeError):
    """Raised when media cannot be uploaded to public hosting."""


class R2MediaHost:
    """Temporary public hosting so Instagram can fetch approved media.

    Nothing is uploaded until publishing; review happens on the local file.
    """

    def __init__(self, client=None, settings=None):
        try:
            self._settings = settings or require_settings(*_R2_SETTINGS)
        except SettingsError as error:
            raise MediaHostError(str(error)) from error
        self._client = client or self._create_client()

    def _create_client(self):
        try:
            import boto3
        except ImportError as error:
            raise MediaHostError(
                "Uploading media needs boto3. Run: python3 -m pip install boto3"
            ) from error
        return boto3.client(
            "s3",
            endpoint_url=(
                f"https://{self._settings['R2_ACCOUNT_ID']}"
                ".r2.cloudflarestorage.com"
            ),
            aws_access_key_id=self._settings["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=self._settings["R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )

    def upload(self, path, content_id):
        """Upload a local file and return (object_key, public_url)."""
        key = f"instagram/{content_id}-{uuid4().hex[:12]}{path.suffix.lower()}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            self._client.upload_file(
                str(path),
                self._settings["R2_BUCKET"],
                key,
                ExtraArgs={"ContentType": content_type},
            )
        except Exception as error:  # boto3 raises several unrelated types.
            raise MediaHostError(f"Could not upload {path.name}: {error}") from error
        base_url = self._settings["R2_PUBLIC_BASE_URL"].rstrip("/")
        return key, f"{base_url}/{key}"

    def delete(self, key):
        try:
            self._client.delete_object(Bucket=self._settings["R2_BUCKET"], Key=key)
        except Exception as error:
            raise MediaHostError(f"Could not delete {key}: {error}") from error
