"""FastAPI application: HTTP routes only.

Routes validate the request, delegate to ``app.services`` (engineering logic)
and ``app.database`` (SQL), and shape the response.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import database, schemas, services

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("htap")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    logger.info("Database ready")
    yield


app = FastAPI(
    title="Hardware Test Analytics Platform",
    description=(
        "Collect, validate, store and analyze hardware test results. "
        "PASS/FAIL is decided by the server from engineering limits."
    ),
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Return 422 without echoing rejected input (NaN/inf are not valid JSON)."""
    errors = [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.get("/")
def root():
    return {"message": "Hardware Test Analytics Platform", "docs": "/docs"}


@app.post("/tests", response_model=schemas.TestResponse, status_code=status.HTTP_201_CREATED)
def create_test(test: schemas.TestCreate):
    evaluation = services.evaluate_test(
        voltage=test.voltage,
        current=test.current,
        temperature=test.temperature,
        duration=test.duration,
    )
    record = database.insert_test(
        device_id=test.device_id,
        test_type=test.test_type.value,
        voltage=test.voltage,
        current=test.current,
        temperature=test.temperature,
        duration=test.duration,
        result=evaluation.result,
        failure_reason=evaluation.failure_reason,
    )
    if evaluation.result == services.FAIL:
        logger.info(
            "Test %s failed for %s: %s",
            record["id"], record["device_id"], evaluation.failure_reason,
        )
    else:
        logger.info("Test %s created for %s", record["id"], record["device_id"])
    return record


@app.get("/tests", response_model=list[schemas.TestResponse])
def list_tests():
    return database.get_all_tests()


@app.get("/tests/{test_id}", response_model=schemas.TestResponse)
def read_test(test_id: int):
    record = database.get_test(test_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")
    return record


@app.delete("/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test(test_id: int):
    if not database.delete_test(test_id):
        raise HTTPException(status_code=404, detail=f"Test {test_id} not found")
    logger.info("Test %s deleted", test_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/failures", response_model=list[schemas.TestResponse])
def list_failures():
    return database.get_failed_tests()


@app.get("/devices/{device_id}/tests", response_model=list[schemas.TestResponse])
def list_device_tests(device_id: str):
    return database.get_device_tests(device_id)


@app.get("/statistics", response_model=schemas.Statistics)
def overall_statistics():
    return services.build_statistics(database.get_statistics())


@app.get("/devices/{device_id}/statistics", response_model=schemas.DeviceStatistics)
def device_statistics(device_id: str):
    row = database.get_device_statistics(device_id)
    if row["total_tests"] == 0:
        raise HTTPException(status_code=404, detail=f"Device {device_id} has no tests")
    return {"device_id": device_id, **services.build_statistics(row)}
