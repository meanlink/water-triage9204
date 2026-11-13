from pydantic import BaseModel, Field


class DatasetInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source: str = Field(default='manual.json', max_length=200)
    records: list[dict] = Field(min_length=5, max_length=5000)


class DatasetRevisionInput(BaseModel):
    # 留空时由服务端按原批次自动命名，确保新批次完整且不影响原批次。
    name: str | None = Field(default=None, max_length=160)
    source: str = Field(default='', max_length=200)
    records: list[dict] = Field(min_length=1, max_length=5000)
