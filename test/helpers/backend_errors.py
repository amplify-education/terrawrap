"""Terraform backend-init error output shared by auto-init tests."""

# Verbatim terraform output, including its hard line wraps.
INITIAL_CONFIG_ERROR = """Executing: terraform apply
╷
│ Error: Backend initialization required, please run "terraform init"
│
│ Reason: Initial configuration of the requested backend "s3"
│
│ The "backend" is the interface that Terraform uses to store state,
│ perform operations, etc. If this message is showing up, it means that the
│ Terraform configuration you're using is using a custom configuration for
│ the Terraform backend.
╵
""".splitlines(keepends=True)

CHANGED_CONFIG_ERROR = """
Error: Backend initialization required: please run "terraform init"

Reason: Backend configuration block has changed
""".splitlines(keepends=True)
