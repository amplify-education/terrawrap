"""Module for containing CLI convenience functions"""
from __future__ import print_function

import subprocess
import tempfile
import logging
from typing import List

from amplify_aws_utils.resource_helper import Jitter

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRIABLE_ERRORS = ['RequestError: send request failed', 'unexpected EOF', 'Throttling',
                    'timeout while waiting for state', 'ServiceUnavailable: Service Unavailable',
                    'failed to decode query XML error response']


# pylint: disable=keyword-arg-before-vararg, too-many-locals
def execute_command(args, print_output=True, capture_stderr=True, print_command=False,
                    retry=False, timeout=15 * 60, *pargs, **kwargs):
    """
    Convenience function for executing a given command and optionally printing the output.
    :param args: List of arguments to execute.
    :param print_output: True if the output of the command should be printed immediately. Defaults to True.
    :param capture_stderr: True if stderr should be captured. Defaults to True.
    :param print_command: True if the command should be printed before executing. Defaults to False.
    :param timeout: Max amount of time to keep retrying to execute command. Defaults to 15 minutes.
    :param retry: Retry a number of times if network errors. Defaults to False.
    :param pargs: Any additional positional arguments to Popen.
    :param kwargs: Any additional keyword arguments to Popen.
    :return: A tuple of the exit code and output of the command.
    """
    max_tries = MAX_RETRIES if retry else 1
    try_count = 0

    jitter = Jitter()
    time_passed = 0
    exit_code = 0
    stdout = ''
    while try_count < max_tries:
        exit_code, stdout = _execute_command(args, print_output, capture_stderr, print_command,
                                             *pargs, **kwargs)

        try_count += 1

        network_errors = _get_retriable_errors(stdout)
        if network_errors and retry:
            logger.warning('Found network errors while running %s command: %s', args, network_errors)
        else:
            # The command either succeeded or failed with a non network error. don't retry
            break

        if time_passed >= timeout:
            raise TimeoutError('Timed out retrying %s command' % args)

        time_passed = jitter.backoff()

    return exit_code, stdout


def _execute_command(args, print_output, capture_stderr, print_command, *pargs, **kwargs):
    """
    Private function for executing a given command and optionally printing the output.
    :param args: List of arguments to execute.
    :param print_output: True if the output of the command should be printed immediately. Defaults to True.
    :param capture_stderr: True if stderr should be captured. Defaults to True.
    :param print_command: True if the command should be printed before executing. Defaults to False.
    :param pargs: Any additional positional arguments to Popen.
    :param kwargs: Any additional keyword arguments to Popen.
    :return: A tuple of the exit code and output of the command.
    """
    stdout_write, stdout_path = tempfile.mkstemp()
    stdout_read = open(stdout_path, "rb")

    if print_command:
        print("Executing: %s" % " ".join(args))

    process = subprocess.Popen(
        args,
        *pargs,
        stdout=stdout_write,
        stderr=stdout_write if capture_stderr else open('/dev/null', 'w'),
        **kwargs
    )

    while True:
        output = stdout_read.read(1).decode()

        if output == '' and process.poll() is not None:
            break

        if print_output and output:
            print(output, end="", flush=True)

    exit_code = process.poll()

    stdout_read.seek(0)
    stdout = [line.decode() for line in stdout_read.readlines()]

    return exit_code, stdout


def _get_retriable_errors(out: List[str]) -> List[str]:
    """Filter line output for retriable errors"""
    return [
        line for line in out
        if any(error in line for error in RETRIABLE_ERRORS)
    ]
