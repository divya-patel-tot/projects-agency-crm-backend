import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from strawberry.fastapi import GraphQLRouter

from app.core.config import get_settings, mask_secret
from app.core.db import check_database_connection
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.core.rate_limit import limiter
from app.core.deps import get_graphql_context
from app.scheduler.runner import start_scheduler, stop_scheduler
from app.graphql.schema import schema
from app.core.production import validate_production_settings
from app.integrations.sentry import init_sentry
from app.routes.audit_export import router as audit_export_router
from app.routes.assets import router as assets_router
from app.routes.graphql_swagger import create_graphql_swagger_router

logger = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        validate_production_settings(settings)
        init_sentry(dsn=settings.sentry_dsn, environment=settings.environment, debug=settings.debug)
        configure_logging(debug=settings.debug)
        db_ok = await check_database_connection()
        logger.info(
            "Startup configuration resolved",
            extra={
                "extra_data": {
                    "environment": settings.environment,
                    "debug": settings.debug,
                    "jwt_secret_key": mask_secret(settings.jwt_secret_key),
                    "jwt_access_token_expire_minutes": settings.jwt_access_token_expire_minutes,
                    "jwt_refresh_token_expire_days": settings.jwt_refresh_token_expire_days,
                    "database_url": mask_secret(settings.database_url),
                    "groq_api_key": mask_secret(settings.groq_api_key),
                    "groq_model": settings.groq_model,
                    "cors_origins_count": len(settings.cors_origins_list),
                    "database_connected": db_ok,
                }
            },
        )
        if not db_ok:
            logger.warning("Startup connectivity check failed — service may be degraded")
        start_scheduler()
        yield
        stop_scheduler()

    app = FastAPI(
        title="Agency CRM API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        description=(
            "Agency CRM backend. Root GraphQL queries and mutations are listed below as "
            "REST-style POST endpoints for Swagger testing. The native GraphQL endpoint "
            "and GraphiQL IDE remain at `/graphql`."
        ),
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    if settings.cors_allow_all_origins:
        # Browsers reject Allow-Origin: * with credentials; regex reflects the request Origin.
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=r".*",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        cors_allow_headers = (
            ["Content-Type", "Authorization", "X-Request-ID"]
            if settings.is_production
            else ["*"]
        )
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=cors_allow_headers,
        )

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        if request.url.path.startswith(("/graphql", "/health", "/assets", "/audit")):
            auth = request.headers.get("Authorization")
            logger.info(
                "HTTP request",
                extra={
                    "extra_data": {
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": duration_ms,
                        "authenticated": bool(auth and auth.lower().startswith("bearer ")),
                    }
                },
            )
        return response

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid4()))
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_ctx.reset(token)

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if not settings.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled exception",
            extra={"extra_data": {"path": request.url.path, "method": request.method}},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": "Rate limit exceeded."},
        )

    graphql_ide = None if settings.is_production else "graphiql"
    graphql_router = GraphQLRouter(schema, context_getter=get_graphql_context, graphql_ide=graphql_ide)
    app.include_router(graphql_router, prefix="/graphql")
    app.include_router(create_graphql_swagger_router(schema))
    app.include_router(audit_export_router)
    app.include_router(assets_router)

    @app.get("/health", tags=["health"])
    async def health_liveness():
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def health_readiness():
        db_ok = await check_database_connection()
        if db_ok:
            return {"status": "ready", "database": "ok"}
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": "error",
            },
        )

    return app


app = create_app()
