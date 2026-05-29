"""SSM parameter resolution with multi-path fallback.

Each .tf_wrapper envvar with ``source: ssm`` may declare ``path`` as a single
string or a list of strings. The resolver tries each path in order, skipping
paths the caller cannot access (AccessDeniedException) or that do not exist
(ParameterNotFound). Other botocore errors propagate. If every path is
skipped, SsmPathsExhausted is raised with the attempted paths and the
caller's IAM identity to aid debugging.
"""
import logging
from typing import Dict, List, Optional

import boto3
from amplify_aws_utils.resource_helper import throttled_call
from botocore.exceptions import ClientError

from terrawrap.utils.aws import get_caller_arn

logger = logging.getLogger(__name__)

_FALLTHROUGH_ERROR_CODES = frozenset({"AccessDeniedException", "ParameterNotFound"})
_UNCACHED = object()
_MISS = object()


class SsmPathsExhausted(Exception):
    """Raised when no SSM path in the candidate list could be read."""

    def __init__(self, paths: List[str], caller_arn: str):
        self.paths = list(paths)
        self.caller_arn = caller_arn
        super().__init__(
            "Unable to read any of the SSM paths tried (in order): "
            + ", ".join(self.paths)
            + f". Caller identity: {self.caller_arn}. "
            + "Either the caller lacks ssm:GetParameter on these paths "
            + "or none exist in the current account/region."
        )


class SsmResolver:
    """Reads SSM parameters, caches successes AND misses, and falls through on access/missing errors."""

    def __init__(self, ssm_client=None, sts_client=None):
        self._cache: Dict[str, object] = {}
        self._ssm_client = ssm_client
        self._sts_client = sts_client
        self._caller_arn: Optional[str] = None

    def _ssm(self):
        if self._ssm_client is None:
            self._ssm_client = boto3.client("ssm")
        return self._ssm_client

    def _caller(self) -> str:
        if self._caller_arn is None:
            self._caller_arn = get_caller_arn(sts_client=self._sts_client)
        return self._caller_arn

    def resolve(self, paths: List[str]) -> str:
        """Return the first readable SSM parameter value from ``paths``."""
        if not paths:
            raise ValueError("ssm_resolver.resolve requires at least one path")
        for path in paths:
            cached = self._cache.get(path, _UNCACHED)
            if cached is _MISS:
                continue
            if cached is not _UNCACHED:
                return cached  # type: ignore[return-value]
            try:
                response = throttled_call(
                    self._ssm().get_parameter, Name=path, WithDecryption=True
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in _FALLTHROUGH_ERROR_CODES:
                    self._cache[path] = _MISS
                    logger.debug("SSM path %s skipped (%s); trying next", path, code)
                    continue
                raise
            value = response["Parameter"]["Value"]
            self._cache[path] = value
            return value
        raise SsmPathsExhausted(paths, self._caller())


_default_resolver = SsmResolver()


def resolve_ssm_paths(paths: List[str]) -> str:
    """Module-level convenience that uses the default cached resolver."""
    return _default_resolver.resolve(paths)
