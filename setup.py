"""setup.py controls the build, testing, and distribution of the egg"""
from __future__ import print_function

import re
import os.path

from setuptools import setup, find_packages


VERSION_REGEX = re.compile(
    r"""
    ^__version__\s=\s
    ['"](?P<version>.*?)['"]
""",
    re.MULTILINE | re.VERBOSE,
)

VERSION_FILE = os.path.join("terrawrap", "version.py")


def get_long_description():
    """Reads the long description from the README"""
    this_directory = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(this_directory, "README.md"), encoding="utf-8") as file:
        return file.read()


def get_version():
    """Reads the version from the package"""
    with open(VERSION_FILE, encoding="utf-8") as handle:
        lines = handle.read()
        result = VERSION_REGEX.search(lines)
        if result:
            return result.groupdict()["version"]
        raise ValueError("Unable to determine __version__")


def get_requirements():
    """Reads the installation requirements from requirements.txt"""
    with open("requirements.txt", encoding="utf-8") as reqfile:
        return [
            line
            for line in reqfile.read().split("\n")
            if not line.startswith(("#", "-"))
        ]


setup(
    name="terrawrap",
    python_requires=">=3.8.0",
    version=get_version(),
    description="Set of Python-based CLI tools for working with Terraform configurations",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    # Get strings from http://www.python.org/pypi?%3Aaction=list_classifiers
    classifiers=[
        "Development Status :: 4 - Beta",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
    ],
    keywords="",
    author="Amplify Education",
    author_email="github@amplify.com",
    url="https://github.com/amplify-education/terrawrap",
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=get_requirements(),
    test_suite="nose.collector",
    scripts=[
        "bin/tf",
        "bin/tf_apply",
        "bin/backend_check",
        "bin/pipeline_check",
        "bin/plan_check",
        "bin/visualize",
        "bin/graph_apply",
        "bin/tf_move",
    ],
)
