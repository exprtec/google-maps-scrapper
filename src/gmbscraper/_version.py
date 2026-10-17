"""Single source of truth for the package version.

Read by ``gmbscraper/__init__.py`` (public ``__version__``) and by the
build backend (``pyproject.toml`` -> ``[tool.hatch.version]``).
"""

__version__ = "0.2.1"
