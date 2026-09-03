"""
Container for terrawrap exceptions
"""


class NotTerraformConfigDirectory(RuntimeError):
    """Error raised when processing a directory that contains no .tf config files"""


class NoDependency(Exception):
    """Error raised when processing a directory that contains .tf_wrapper config files with no dependency"""


class ManualDependencyError(RuntimeError):
    """Error raised when a depends_on entry targets an apply_automatically: false directory"""
