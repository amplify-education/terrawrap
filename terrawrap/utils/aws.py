"""Shared AWS utility helpers."""
import logging

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

_STS_CONFIG = Config(
    connect_timeout=3,
    read_timeout=3,
    retries={"max_attempts": 0},
)

_UNKNOWN_SENTINEL = "<unknown — sts:GetCallerIdentity failed>"


def get_caller_arn(sts_client=None) -> str:
    """Return the caller's ARN via STS, or a sentinel string on failure.

    :param sts_client: Optional pre-constructed STS client (for testing).
    :return: The caller ARN string, or ``_UNKNOWN_SENTINEL`` on any STS error.
    """
    if sts_client is None:
        sts_client = boto3.client("sts", config=_STS_CONFIG)
    try:
        return sts_client.get_caller_identity()["Arn"]
    except (ClientError, BotoCoreError) as exc:
        logger.warning("Failed to resolve caller identity: %s", exc)
        return _UNKNOWN_SENTINEL
