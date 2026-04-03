class SocketIOValidationError(Exception):
    """Raised when incoming data fails Pydantic validation."""

    def __init__(self, errors: list, model_name: str):
        self.errors = errors
        self.model_name = model_name
        super().__init__(f"Validation error for {model_name}: {errors}")
