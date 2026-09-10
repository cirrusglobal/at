"""Domain exceptions and their HTTP mapping.

Keeping these separate from the routers means the service layer never imports
FastAPI, which is what makes it testable in isolation.
"""


class DomainError(Exception):
    """Base class for errors that map onto a specific HTTP response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NetworkNotFound(DomainError):
    status_code = 404
    code = "network_not_found"

    def __init__(self, network_id: str) -> None:
        super().__init__(f"No network with id {network_id!r}", details={"network_id": network_id})


class ProvisioningError(DomainError):
    """A cloud call failed. Anything already created has been rolled back."""

    status_code = 502
    code = "provisioning_failed"


class RollbackIncomplete(DomainError):
    """Provisioning failed AND cleanup failed. Resources may still exist.

    Distinct from ProvisioningError on purpose: this is the one case where the
    caller must be told that orphaned resources may be billing.
    """

    status_code = 500
    code = "rollback_incomplete"
