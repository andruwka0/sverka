from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from radar.config import load_rules
from radar.engine import compare
from radar.models import CheckResult, Diagnostic, InputError
from radar.tables import read_excel

DEFAULT_RULES = Path(__file__).resolve().parents[1] / "rules.yaml"


def create_app(rules_path: Path = DEFAULT_RULES) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.rules = load_rules(rules_path)
        yield

    app = FastAPI(title="Сверка таблиц", lifespan=lifespan)

    @app.exception_handler(InputError)
    async def input_error(request: Request, exc: InputError):
        return JSONResponse(
            status_code=422,
            content={"errors": [item.model_dump() for item in exc.errors]},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [
            Diagnostic(
                code="invalid_request",
                file_role=str(item["loc"][-1]),
                field=str(item["loc"][-1]),
                message=item["msg"],
            ).model_dump()
            for item in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"errors": errors})

    @app.post("/api/v1/checks")
    def check(
        request: Request,
        participants: Annotated[UploadFile, File()],
        officials: Annotated[UploadFile, File()],
        related_persons: Annotated[UploadFile, File()],
    ) -> CheckResult:
        tables = {}
        errors = []
        for role, upload in [
            ("participants", participants),
            ("officials", officials),
            ("related_persons", related_persons),
        ]:
            try:
                tables[role] = read_excel(
                    upload.file, role, upload.filename or role + ".xlsx"
                )
            except InputError as exc:
                errors.extend(exc.errors)
        if errors:
            raise InputError(errors)
        return compare(tables, request.app.state.rules)

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.frontend(
        "/", directory=Path(__file__).resolve().parents[1] / "frontend", fallback=None
    )
    return app


app = create_app()
