class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def not_found(message: str = "Resource not found.") -> AppError:
    return AppError(404, "not_found", message)


def unauthorized(message: str = "Authentication required.") -> AppError:
    return AppError(401, "unauthorized", message)


def conflict(code: str, message: str) -> AppError:
    return AppError(409, code, message)
