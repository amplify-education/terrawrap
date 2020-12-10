"""
Container for terrawrap exceptions
"""


class NotTerraformConfigDirectory(RuntimeError):
    """Error raised when processing a directory that contains no .tf config files"""


class NoDependency(Exception):
    """Error raised when processing a directory that contains .tf_wrapper config files with no dependency"""
