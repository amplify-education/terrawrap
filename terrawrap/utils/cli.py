"""Module for containing CLI convenience functions"""

from __future__ import print_function

import base64
import codecs
import gzip
import logging
import os
import subprocess
import tempfile
import time
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import requests
from amplify_aws_utils.resource_helper import Jitter
from aws_requests_auth.boto_utils import BotoAWSRequestsAuth
from requests.exceptions import HTTPError

from terrawrap.utils.git_utils import get_git_hash, get_git_root

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRIABLE_ERRORS = [
    "RequestError: send request failed",
    "unexpected EOF",
    "Throttling",
    "timeout while waiting for state",
    "ServiceUnavailable: Service Unavailable",
    "failed to decode query XML error response",
    "connection reset",
    "Connection reset",
    "Please try again.",
    "Client.Timeout exceeded",
    "Request limit for operation",
    "try again later",
    "handshake timeout",
    "SSL_ERROR_SYSCALL",
    "Api Rate Limit Exceeded",
    "TooManyUpdates",
    "409 Conflict",
    "504 Gateway Timeout",
]
AUDIT_POST_PATH = "/audit_info"
AUDIT_UPDATE_PATH = "/update_audit_info"
LOG_CHUNK_POST_PATH = "/log_chunk"
OUTPUT_COMPRESSION_THRESHOLD = 5 * 1024 * 1024
CHUNK_LINE_COUNT = 100
CHUNK_FLUSH_INTERVAL = 15.0
# After this many consecutive log-chunk POST failures in a single run, stop
# trying for the rest of it -- a broken/unreachable audit API otherwise means
# hundreds of doomed POSTs (one per flush) with zero backoff.
CHUNK_FAILURE_CIRCUIT_BREAKER = 3

# BotoAWSRequestsAuth wraps a boto3.Session, which caches and auto-refreshes
# credentials. Constructing a fresh one per call (previously done on every
# audit-info/log-chunk POST) defeats that caching: each construction
# re-resolves credentials from scratch, and at high concurrency
# (parallel_applies) that can saturate the container credential metadata
# endpoint (429s), which in turn starves Terraform's own credential
# resolution in the same task. Cached per audit_api_url (host) since the
# signing host differs per URL; effectively "once per process" since this
# module-level cache lives for the interpreter's lifetime.
_auth_cache: Dict[str, BotoAWSRequestsAuth] = {}


def _get_auth(audit_api_url: str) -> BotoAWSRequestsAuth:
    """Returns a cached BotoAWSRequestsAuth for the given audit API URL."""
    if audit_api_url not in _auth_cache:
        _auth_cache[audit_api_url] = BotoAWSRequestsAuth(
            aws_host=urlparse(audit_api_url).hostname,
            aws_region="us-west-2",
            aws_service="execute-api",
        )
    return _auth_cache[audit_api_url]


# get_git_root shells out to `git rev-parse --show-toplevel` via GitPython --
# a subprocess fork per call. _post_log_chunk previously called it on every
# chunk POST for a path that never changes within a single execute_command
# run (hundreds of forks per apply at CHUNK_LINE_COUNT's old cadence).
_git_root_cache: Dict[str, str] = {}


def _cached_git_root(path: str) -> str:
    """Returns a cached get_git_root(path) result."""
    if path not in _git_root_cache:
        _git_root_cache[path] = get_git_root(path)
    return _git_root_cache[path]


class Status(str, Enum):
    """Enum for status of execute_command"""

    SUCCESS = "SUCCESS"
    IN_PROGRESS = "IN PROGRESS"
    FAILED = "FAILED"


# pylint: disable=too-many-locals
def execute_command(
    args: Union[List[str], str],
    *pargs,
    print_output: bool = True,
    capture_stderr: bool = True,
    print_command: bool = False,
    retry: bool = False,
    timeout: int = 15 * 60,
    audit_api_url: Optional[Union[str, List[str]]] = None,
    **kwargs,
) -> Tuple[int, List[str]]:
    """
    Convenience function for executing a given command and optionally printing the output.
    :param args: List of arguments to execute, or a single string.
    :param pargs: Any additional positional arguments to Popen.
    :param print_output: True if the output of the command should be printed immediately. Defaults to True.
    :param capture_stderr: True if stderr should be captured. Defaults to True.
    :param print_command: True if the command should be printed before executing. Defaults to False.
    :param timeout: Max amount of time to keep retrying to execute command. Defaults to 15 minutes.
    :param retry: Retry a number of times if network errors. Defaults to False.
    :param audit_api_url: Audit API URL(s) to submit POST requests to. Accepts a single URL or a list
    of URLs; each URL receives the same audit info. Defaults to None so no data is sent.
    :param kwargs: Any additional keyword arguments to Popen.
    :return: A tuple of the exit code and output of the command.
    """
    try_count = 0

    audit_api_urls = [audit_api_url] if isinstance(audit_api_url, str) else list(audit_api_url or [])

    # It's possible for an envvar to be set to none, so exclude those envvars.
    if "env" in kwargs:
        kwargs["env"] = {key: value for key, value in kwargs["env"].items() if value is not None}

    # Get time - nanoseconds since epoch
    start_time = int(time.time())

    if audit_api_urls and kwargs["cwd"] and ("apply" in args or "destroy" in args):
        for url in audit_api_urls:
            try:
                # Call _post_audit_info for working directory, setting status to 'in progress'
                _post_audit_info(
                    audit_api_url=url,
                    path=kwargs["cwd"],
                    start_time=start_time,
                )
            except HTTPError as http_exception:
                logger.error("An error occurred while connecting to audit API: %s", http_exception)

    else:
        logger.info("No audit_api_url provided")

    should_stream = bool(audit_api_urls and kwargs["cwd"] and ("apply" in args or "destroy" in args))
    chunk_seq = 0
    consecutive_chunk_failures = 0
    streaming_disabled = False

    def _chunk_callback(content: str) -> None:
        nonlocal chunk_seq, consecutive_chunk_failures, streaming_disabled
        if streaming_disabled:
            chunk_seq += 1
            return

        any_succeeded = False
        for url in audit_api_urls:
            try:
                _post_log_chunk(
                    audit_api_url=url,
                    path=kwargs["cwd"],
                    start_time=start_time,
                    sequence=chunk_seq,
                    content=content,
                )
                any_succeeded = True
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Failed to post log chunk %d to %s: %s", chunk_seq, url, exc)
        chunk_seq += 1

        if any_succeeded:
            consecutive_chunk_failures = 0
            return

        consecutive_chunk_failures += 1
        if consecutive_chunk_failures >= CHUNK_FAILURE_CIRCUIT_BREAKER:
            streaming_disabled = True
            logger.warning(
                "Disabling live log-chunk streaming for the rest of this run after %d consecutive failures",
                consecutive_chunk_failures,
            )

    jitter = Jitter()
    time_passed = 0
    exit_code = 0
    stdout: List[str] = []
    while try_count < MAX_RETRIES if retry else 1:
        exit_code, stdout = _execute_command(
            args,
            print_output,
            capture_stderr,
            print_command,
            *pargs,
            on_chunk=_chunk_callback if should_stream else None,
            **kwargs,
        )

        try_count += 1

        network_errors = _get_retriable_errors(stdout)
        if exit_code != 0 and network_errors and retry:
            logger.warning(
                "Found network errors while running %s command: %s",
                args,
                network_errors,
            )
        else:
            # The command either succeeded or failed with a non network error. don't retry
            break

        if time_passed >= timeout:
            break

        time_passed = jitter.backoff()

    if audit_api_urls and kwargs["cwd"] and ("apply" in args or "destroy" in args):
        # Call _post_audit_info again, this time to update the 'in progress' entry with new status and output
        for url in audit_api_urls:
            try:
                _post_audit_info(
                    audit_api_url=url,
                    path=kwargs["cwd"],
                    exit_code=exit_code,
                    stdout=stdout,
                    start_time=start_time,
                    update=True,
                )
            except HTTPError as http_exception:
                logger.error("An error occurred while connecting to audit API: %s", http_exception)
    else:
        logger.info("No audit_api_url provided")

    if time_passed >= timeout:
        raise TimeoutError(f"Timed out retrying {args} command")

    return exit_code, stdout


def _execute_command(
    args: Union[List[str], str],
    print_output: bool,
    capture_stderr: bool,
    print_command: bool,
    *pargs,
    on_chunk: Optional[Callable[[str], None]] = None,
    **kwargs,
) -> Tuple[int, List[str]]:
    """
    Private function for executing a given command and optionally printing the output.
    :param args: List of arguments to execute, or a single string.
    :param print_output: True if the output of the command should be printed immediately. Defaults to True.
    :param capture_stderr: True if stderr should be captured. Defaults to True.
    :param print_command: True if the command should be printed before executing. Defaults to False.
    :param pargs: Any additional positional arguments to Popen.
    :param on_chunk: Optional callback invoked with buffered output chunks for live streaming.
    :param kwargs: Any additional keyword arguments to Popen.
    :return: A tuple of the exit code and output of the command.
    """
    stdout_write, stdout_path = tempfile.mkstemp()
    with open(stdout_path, "rb") as stdout_read, open("/dev/null", "w", encoding="utf-8") as dev_null:
        if print_command:
            print(f"Executing: {' '.join(args)}")

        kwargs["stdout"] = stdout_write
        kwargs["stderr"] = stdout_write if capture_stderr else dev_null

        # pylint: disable=consider-using-with
        process = subprocess.Popen(args, *pargs, **kwargs)

        buf: List[str] = []
        line_count = 0
        last_flush = time.time()

        # Terraform's output (e.g. the box-drawing characters in its error
        # formatting) contains multi-byte UTF-8 sequences. Decoding one raw
        # byte at a time would mangle those into replacement characters, so
        # feed bytes through an incremental decoder that buffers only the
        # 1-3 bytes of a single in-progress character - not whole lines -
        # preserving the immediate, un-buffered flush that interactive
        # terraform prompts (which don't end in a newline) rely on.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            raw_byte = stdout_read.read(1)
            is_eof = raw_byte == b"" and process.poll() is not None
            output = decoder.decode(raw_byte, final=is_eof)

            if print_output and output:
                print(output, end="", flush=True)

            if on_chunk and output:
                buf.append(output)
                if output == "\n":
                    line_count += 1
                now = time.time()
                if line_count >= CHUNK_LINE_COUNT or now - last_flush >= CHUNK_FLUSH_INTERVAL:
                    on_chunk("".join(buf))
                    buf = []
                    line_count = 0
                    last_flush = now

            if is_eof:
                break

        if on_chunk and buf:
            on_chunk("".join(buf))

        exit_code = process.poll()

        stdout_read.seek(0)
        stdout = [line.decode(errors="replace") for line in stdout_read.readlines()]

        # ignoring mypy error below because it thinks exit_code can sometimes be None
        # we know that will never be the case because the above While loop will keep looping forever
        # until exit_code is not None
        return exit_code, stdout  # type: ignore


def _get_retriable_errors(out: List[str]) -> List[str]:
    """Filter line output for retriable errors"""
    return [line for line in out if any(error in line for error in RETRIABLE_ERRORS)]


def _post_audit_info(
    audit_api_url: str,
    path: str,
    start_time: int,
    exit_code: Optional[int] = None,
    stdout: Optional[List[str]] = None,
    update: bool = False,
):
    root = _cached_git_root(path)
    sha = get_git_hash(path)

    path = path.replace(root, "")

    status = (
        Status.IN_PROGRESS if exit_code is None else (Status.SUCCESS if exit_code == 0 else Status.FAILED)
    )

    logger.info("Attempting to send data to Audit API: %s - %s", path, status)

    url = (audit_api_url + AUDIT_UPDATE_PATH) if update else (audit_api_url + AUDIT_POST_PATH)

    auth = _get_auth(audit_api_url)

    stdout_str = "".join(stdout) if stdout else ""

    payload = {
        "directory": path,
        "start_time": start_time,
        "status": status,
        "git_hash": sha,
        # Echo the CodeBuild build id so terraform-audit-api can correlate a
        # UI-triggered apply back to its PENDING placeholder row. Empty string
        # (not None) for pipeline/local applies with no CodeBuild build: the API
        # deserializes build_id as a required str and rejects null, and treats ""
        # as "no correlation" (reconcile is skipped).
        "build_id": os.environ.get("CODEBUILD_BUILD_ID") or "",
    }

    if len(stdout_str) > OUTPUT_COMPRESSION_THRESHOLD:
        compressed = gzip.compress(stdout_str.encode("utf-8"))
        payload["output"] = ""
        payload["output_compressed"] = base64.b64encode(compressed).decode("ascii")
        logger.info(
            "Compressed output for %s: %s -> %s bytes",
            path,
            len(stdout_str),
            len(compressed),
        )
    else:
        payload["output"] = stdout_str

    try:
        response = requests.post(
            url=url,
            auth=auth,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        logger.info("Successfully posted data to provided url: %s", audit_api_url)
    except requests.exceptions.RequestException:
        logger.error("Unable to post data to provided url: %s", audit_api_url)


def _post_log_chunk(
    audit_api_url: str,
    path: str,
    start_time: int,
    sequence: int,
    content: str,
) -> None:
    """POST a single log chunk to the audit API during an apply."""
    root = _cached_git_root(path)
    directory = path.replace(root, "")

    auth = _get_auth(audit_api_url)

    response = requests.post(
        url=audit_api_url + LOG_CHUNK_POST_PATH,
        auth=auth,
        json={
            "directory": directory,
            "start_time": start_time,
            "sequence": sequence,
            "content": content,
        },
        timeout=10,
    )
    response.raise_for_status()
