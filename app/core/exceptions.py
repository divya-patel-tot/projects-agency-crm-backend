class DomainError(Exception):
    def __init__(self, message: str, code: str = "domain_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthenticationError(DomainError):
    def __init__(self, message: str = "Invalid credentials"):
        super().__init__(message, code="authentication_error")


class AuthorizationError(DomainError):
    def __init__(self, message: str = "Forbidden"):
        super().__init__(message, code="authorization_error")


class NotFoundError(DomainError):
    def __init__(self, message: str = "Not found"):
        super().__init__(message, code="not_found")
