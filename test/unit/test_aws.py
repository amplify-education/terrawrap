"""Tests for terrawrap.utils.aws shared helpers."""
from unittest import TestCase
from unittest.mock import MagicMock

from botocore.exceptions import ClientError, NoCredentialsError

from terrawrap.utils.aws import get_caller_arn, _UNKNOWN_SENTINEL


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "stubbed"}},
        operation_name="GetCallerIdentity",
    )


class TestGetCallerArn(TestCase):
    """Unit tests for get_caller_arn."""

    def test_happy_path_returns_arn(self):
        """Returns the ARN string when STS succeeds."""
        sts = MagicMock()
        sts.get_caller_identity.return_value = {
            "Arn": "arn:aws:sts::123456789012:assumed-role/Role/session"
        }

        result = get_caller_arn(sts_client=sts)

        self.assertEqual("arn:aws:sts::123456789012:assumed-role/Role/session", result)
        sts.get_caller_identity.assert_called_once()

    def test_client_error_returns_sentinel(self):
        """Returns the sentinel string on a ClientError from STS."""
        sts = MagicMock()
        sts.get_caller_identity.side_effect = _client_error("InvalidClientTokenId")

        result = get_caller_arn(sts_client=sts)

        self.assertEqual(_UNKNOWN_SENTINEL, result)

    def test_no_credentials_returns_sentinel(self):
        """Returns the sentinel string when no AWS credentials are configured."""
        sts = MagicMock()
        sts.get_caller_identity.side_effect = NoCredentialsError()

        result = get_caller_arn(sts_client=sts)

        self.assertEqual(_UNKNOWN_SENTINEL, result)

    def test_sentinel_substrings(self):
        """Sentinel string contains '<unknown' and 'sts:GetCallerIdentity failed'."""
        self.assertIn("<unknown", _UNKNOWN_SENTINEL)
        self.assertIn("sts:GetCallerIdentity failed", _UNKNOWN_SENTINEL)

    def test_warning_logged_on_failure(self):
        """A warning is emitted when the STS call fails."""
        sts = MagicMock()
        sts.get_caller_identity.side_effect = NoCredentialsError()

        with self.assertLogs("terrawrap.utils.aws", level="WARNING") as ctx:
            get_caller_arn(sts_client=sts)

        messages = "\n".join(ctx.output)
        self.assertIn("Failed to resolve caller identity", messages)
