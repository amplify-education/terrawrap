"""Tests for SSM multi-path resolution."""
from unittest import TestCase
from unittest.mock import MagicMock

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from botocore.stub import Stubber

from terrawrap.utils.ssm_resolver import SsmResolver, SsmPathsExhausted


CALLER_ARN = "arn:aws:sts::123456789012:assumed-role/Engineer/test-session"
STUB_REGION = "us-west-2"  # botocore Stubber requires a region; value is inert


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "stubbed"}},
        operation_name="GetParameter",
    )


class TestSsmResolverHappyPath(TestCase):
    """Resolves the first readable path and short-circuits remaining paths."""

    def setUp(self):
        self.ssm = boto3.client("ssm", region_name=STUB_REGION)
        self.stub = Stubber(self.ssm)
        self.sts = MagicMock()
        self.sts.get_caller_identity.return_value = {"Arn": CALLER_ARN}
        self.resolver = SsmResolver(ssm_client=self.ssm, sts_client=self.sts)

    def test_first_path_returns_value(self):
        """First successful read short-circuits; no fallthrough lookups."""
        self.stub.add_response(
            "get_parameter",
            {"Parameter": {"Name": "/a", "Value": "secret-A", "Type": "SecureString"}},
            {"Name": "/a", "WithDecryption": True},
        )
        with self.stub:
            value = self.resolver.resolve(["/a", "/b", "/c"])

        self.assertEqual("secret-A", value)

    def test_cached_value_avoids_second_api_call(self):
        """Resolving the same path twice issues only one GetParameter call."""
        self.stub.add_response(
            "get_parameter",
            {"Parameter": {"Name": "/a", "Value": "secret-A", "Type": "SecureString"}},
            {"Name": "/a", "WithDecryption": True},
        )
        with self.stub:
            first = self.resolver.resolve(["/a"])
            second = self.resolver.resolve(["/a"])

        self.assertEqual("secret-A", first)
        self.assertEqual("secret-A", second)


class TestSsmResolverFallthrough(TestCase):
    """AccessDenied and ParameterNotFound silently fall through to the next path."""

    def setUp(self):
        self.ssm = MagicMock()
        self.sts = MagicMock()
        self.sts.get_caller_identity.return_value = {"Arn": CALLER_ARN}
        self.resolver = SsmResolver(ssm_client=self.ssm, sts_client=self.sts)

    def test_access_denied_falls_through(self):
        """A path the caller cannot read is silently skipped."""
        self.ssm.get_parameter.side_effect = [
            _client_error("AccessDeniedException"),
            {"Parameter": {"Name": "/b", "Value": "secret-B", "Type": "SecureString"}},
        ]

        value = self.resolver.resolve(["/a", "/b"])

        self.assertEqual("secret-B", value)
        self.assertEqual(2, self.ssm.get_parameter.call_count)

    def test_parameter_not_found_falls_through(self):
        """A path that does not exist is silently skipped."""
        self.ssm.get_parameter.side_effect = [
            _client_error("ParameterNotFound"),
            {"Parameter": {"Name": "/b", "Value": "secret-B", "Type": "SecureString"}},
        ]

        value = self.resolver.resolve(["/a", "/b"])

        self.assertEqual("secret-B", value)

    def test_non_fallthrough_error_propagates(self):
        """Non-fallthrough client errors abort resolution and surface to the caller.

        Throttling is retried inside amplify_aws_utils.throttled_call, so we pick an
        error code (ValidationException) that bypasses both the retry layer and the
        fallthrough list.
        """
        self.ssm.get_parameter.side_effect = _client_error("ValidationException")

        with self.assertRaises(ClientError) as ctx:
            self.resolver.resolve(["/a", "/b"])

        self.assertEqual("ValidationException", ctx.exception.response["Error"]["Code"])

    def test_skipped_path_is_cached(self):
        """A path that fell through is remembered; the second resolve hits no API."""
        self.ssm.get_parameter.side_effect = [
            _client_error("AccessDeniedException"),
            {"Parameter": {"Name": "/b", "Value": "secret-B", "Type": "SecureString"}},
        ]

        first = self.resolver.resolve(["/a", "/b"])
        second = self.resolver.resolve(["/a", "/b"])

        self.assertEqual("secret-B", first)
        self.assertEqual("secret-B", second)
        self.assertEqual(2, self.ssm.get_parameter.call_count)


class TestSsmPathsExhausted(TestCase):
    """Error message lists every attempted path and the caller identity."""

    def setUp(self):
        self.ssm = MagicMock()
        self.sts = MagicMock()
        self.sts.get_caller_identity.return_value = {"Arn": CALLER_ARN}
        self.resolver = SsmResolver(ssm_client=self.ssm, sts_client=self.sts)

    def test_message_lists_paths_and_caller(self):
        """SsmPathsExhausted carries every attempted path and the caller's ARN."""
        self.ssm.get_parameter.side_effect = [
            _client_error("AccessDeniedException"),
            _client_error("ParameterNotFound"),
        ]

        with self.assertRaises(SsmPathsExhausted) as ctx:
            self.resolver.resolve(["/a", "/b"])

        self.assertEqual(["/a", "/b"], ctx.exception.paths)
        self.assertEqual(CALLER_ARN, ctx.exception.caller_arn)
        self.assertIn("/a", str(ctx.exception))
        self.assertIn("/b", str(ctx.exception))
        self.assertIn(CALLER_ARN, str(ctx.exception))

    def test_empty_paths_raises_value_error(self):
        """An empty path list is a programming error, not a resolution failure."""
        with self.assertRaises(ValueError):
            self.resolver.resolve([])

    def test_sts_client_error_surfaces_sentinel(self):
        """STS ClientError on get_caller_identity still yields a usable SsmPathsExhausted."""
        self.ssm.get_parameter.side_effect = [_client_error("ParameterNotFound")]
        self.sts.get_caller_identity.side_effect = ClientError(
            error_response={
                "Error": {"Code": "InvalidClientTokenId", "Message": "stubbed"}
            },
            operation_name="GetCallerIdentity",
        )
        self.resolver = SsmResolver(ssm_client=self.ssm, sts_client=self.sts)

        with self.assertRaises(SsmPathsExhausted) as ctx:
            self.resolver.resolve(["/a"])

        self.assertIn("<unknown", ctx.exception.caller_arn)
        self.assertIn("sts:GetCallerIdentity failed", ctx.exception.caller_arn)

    def test_sts_no_creds_error_surfaces_sentinel(self):
        """STS NoCredentialsError on get_caller_identity still yields a usable SsmPathsExhausted."""
        self.ssm.get_parameter.side_effect = [_client_error("ParameterNotFound")]
        self.sts.get_caller_identity.side_effect = NoCredentialsError()
        self.resolver = SsmResolver(ssm_client=self.ssm, sts_client=self.sts)

        with self.assertRaises(SsmPathsExhausted) as ctx:
            self.resolver.resolve(["/a"])

        self.assertIn("<unknown", ctx.exception.caller_arn)
        self.assertIn("sts:GetCallerIdentity failed", ctx.exception.caller_arn)
