import logging
import mimetypes
from pathlib import Path

logger = logging.getLogger(__name__)


def publish(output_dir, bucket) -> None:
    # Imported here rather than at module scope: publishing to S3 is the legacy
    # AWS path, but `pylitical/__init__.py` re-exports this function, so a
    # top-level import made the whole AWS SDK a hard requirement for rendering
    # a static page destined for Cloudflare.
    try:
        import boto3  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError(
            "publish() needs boto3. Install it, or unset OUTPUT_BUCKET to skip "
            "S3 publishing (Cloudflare Pages deploys are handled by wrangler)."
        ) from exc

    s3 = boto3.client("s3")
    for path in sorted(Path(output_dir).iterdir()):
        if not path.is_file():
            continue
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        s3.upload_file(
            str(path),
            bucket,
            path.name,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info("Uploaded s3://%s/%s (%s)", bucket, path.name, content_type)
