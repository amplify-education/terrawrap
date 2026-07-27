"""
Container for terrawrap exceptions
"""


class NotTerraformConfigDirectory(RuntimeError):
    """Error raised when processing a directory that contains no .tf config files"""


class NoDependency(Exception):
    """Error raised when processing a directory that contains .tf_wrapper config files with no dependency"""


class EnvVarResolutionError(RuntimeError):
    """Error raised when a .tf_wrapper envvar cannot be resolved to a value"""
