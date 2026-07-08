import logging
import mimetypes
from pathlib import Path

import boto3

logger = logging.getLogger(__name__)


def publish(output_dir, bucket) -> None:
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
