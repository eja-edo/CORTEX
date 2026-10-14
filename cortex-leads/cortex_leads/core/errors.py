class CortexError(Exception):
    """Base for all cortex-leads errors."""


class ConfigError(CortexError):
    """Missing or unsafe configuration; raised at startup."""


class TenantScopeError(CortexError):
    """A query ran without (or outside) a tenant scope."""
