"""Expected failures. The CLI prints these without a traceback."""


class ApiWatchError(Exception):
    """Base class for errors the user can act on."""


class UsageError(ApiWatchError):
    """The command line or the config file is not usable."""


class LLMError(ApiWatchError):
    """The model provider could not complete a request."""


class AlertError(ApiWatchError):
    """A failure webhook could not be delivered."""
