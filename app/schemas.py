"""Pydantic models describing the shape of API input and output.

These perform *input validation* (is the data well formed?). Whether the
measurements are within engineering limits is decided in ``app.services``.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class TestType(str, Enum):
    POWER = "POWER"
    UART = "UART"
    MEMORY = "MEMORY"
    THERMAL = "THERMAL"
    FUNCTIONAL = "FUNCTIONAL"


class TestCreate(BaseModel):
    """Body of ``POST /tests``. The result is computed, never supplied."""

    model_config = ConfigDict(str_strip_whitespace=True)

    device_id: str = Field(min_length=1, max_length=64, examples=["FPGA-001"])
    test_type: TestType = Field(examples=["POWER"])
    voltage: float = Field(allow_inf_nan=False, description="Volts", examples=[3.31])
    current: float = Field(allow_inf_nan=False, description="Amperes", examples=[0.42])
    temperature: float = Field(
        allow_inf_nan=False, description="Degrees Celsius", examples=[41.7]
    )
    duration: float = Field(
        ge=0, allow_inf_nan=False, description="Seconds", examples=[2.31]
    )


class TestResponse(BaseModel):
    """A stored test result."""

    id: int
    device_id: str
    test_type: str
    voltage: float
    current: float
    temperature: float
    duration: float
    result: str
    failure_reason: str | None
    timestamp: str


class Statistics(BaseModel):
    total_tests: int
    passed_tests: int
    failed_tests: int
    pass_rate: float
    average_voltage: float | None
    average_current: float | None
    average_temperature: float | None


class DeviceStatistics(Statistics):
    device_id: str
