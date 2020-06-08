"""
Container for terrawrap exceptions
"""


class NotTerraformConfigDirectory(RuntimeError):
    """Error raised when processing a directory that contains no .tf config files"""
