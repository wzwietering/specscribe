import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from specscribe.api.dependencies import (
    get_database_manager,
    get_jwt_service_with_refresh,
    get_refresh_token_service,
)
from specscribe.api.error_responses import ErrorDetail
from specscribe.api.exceptions import (
    AnswerNotFoundException,
    QuestionNotFoundException,
    SessionNotFoundAPIException,
    ValidationException,
)
from specscribe.api.middleware import (
    AuthenticationMiddleware,
    ExceptionHandlingMiddleware,
    RequestIDMiddleware,
)
from specscribe.api.routes import auth, billing, questions, sessions, usage
from specscribe.core.logging import init_logging

app = FastAPI(
    title="SpecScribe API",
    description="Your AI Business Analyst - Transform conversations into code-ready specifications",
    version="1.0.0",
)

# Initialize structured logging for the API server
init_logging(
    level=os.getenv("SPECSCRIBE_LOG_LEVEL", "INFO"),
    fmt=os.getenv("SPECSCRIBE_LOG_FORMAT", "json"),
    file_path=os.getenv("SPECSCRIBE_LOG_FILE"),
    mask=os.getenv("SPECSCRIBE_LOG_MASK", "false").lower() in ("true", "1", "yes", "on"),
    use_stderr=True,  # Use stderr for better separation from app output
)

# Add session middleware for OAuth state management
session_secret = os.getenv("JWT_SECRET_KEY")
if not session_secret:
    raise ValueError("JWT_SECRET_KEY environment variable is required for session middleware")
app.add_middleware(SessionMiddleware, secret_key=session_secret)

# Configure CORS for production
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Configurable origins for production
    allow_credentials=True,  # Enable for authentication
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # Standard REST methods
    allow_headers=["Content-Type", "Authorization"],  # Required headers for auth
    max_age=86400,  # Cache preflight requests for 24 hours
)

# Add request ID middleware (first, so all logs have request ID)
app.add_middleware(RequestIDMiddleware)

# Add authentication middleware (before exception handling)
# Include refresh token service and db session factory for auto-refresh
app.add_middleware(
    AuthenticationMiddleware,
    jwt_service=get_jwt_service_with_refresh(),
    refresh_token_service=get_refresh_token_service(),
    db_session_factory=get_database_manager().SessionLocal,
)

# Add unified exception handling middleware
app.add_middleware(ExceptionHandlingMiddleware)

app.include_router(auth.router, prefix="/api/v1", tags=["authentication"])
app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])
app.include_router(questions.router, prefix="/api/v1", tags=["questions"])
app.include_router(usage.router, prefix="/api/v1", tags=["usage"])
app.include_router(billing.router, prefix="/api/v1", tags=["billing"])


# Exception handler for validation exceptions from dependency injection
@app.exception_handler(ValidationException)
async def validation_exception_handler(request: Request, exc: ValidationException):
    return JSONResponse(
        status_code=exc.status_code, content={"error": "ValidationError", "message": exc.detail, "details": None}
    )


# Exception handler for Pydantic request validation errors
@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    details = []
    for error in exc.errors():
        field = ".".join(str(x) for x in error["loc"])
        details.append(ErrorDetail(type="validation", message=error["msg"], field=field))

    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_failed",
            "message": "Request validation failed",
            "details": [detail.model_dump() for detail in details],
            "status_code": 422,
        },
    )


# Exception handler for session not found errors
@app.exception_handler(SessionNotFoundAPIException)
async def session_not_found_exception_handler(request: Request, exc: SessionNotFoundAPIException):
    return JSONResponse(
        status_code=exc.status_code, content={"error": "SessionNotFound", "message": exc.detail, "details": None}
    )


# Exception handler for question not found errors
@app.exception_handler(QuestionNotFoundException)
async def question_not_found_exception_handler(request: Request, exc: QuestionNotFoundException):
    return JSONResponse(
        status_code=exc.status_code, content={"error": "QuestionNotFound", "message": exc.detail, "details": None}
    )


# Exception handler for answer not found errors
@app.exception_handler(AnswerNotFoundException)
async def answer_not_found_exception_handler(request: Request, exc: AnswerNotFoundException):
    return JSONResponse(
        status_code=exc.status_code, content={"error": "AnswerNotFound", "message": exc.detail, "details": None}
    )


@app.get("/")
async def root():
    return {"message": "SpecScribe API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.on_event("startup")
async def validate_stripe_configuration():
    """Validate Stripe environment variables on startup."""
    required_vars = [
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "STRIPE_PRICE_ID_MONTHLY",
        "STRIPE_PRICE_ID_ANNUAL",
    ]

    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        error_msg = f"Missing required Stripe environment variables: {', '.join(missing_vars)}"
        raise ValueError(error_msg)
