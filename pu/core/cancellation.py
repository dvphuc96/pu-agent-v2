"""Cooperative cancellation must bypass generic model/tool retry handlers."""


class RunCancelled(BaseException):
    """Control flow, like asyncio.CancelledError; never a retryable failure."""
