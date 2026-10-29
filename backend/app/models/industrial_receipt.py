from sqlmodel import Field, SQLModel


class IndustrialReceipt(SQLModel, table=True):
    """A durable result for an explicitly confirmed frozen metadata plan."""

    __tablename__ = "industrial_receipts"
    plan_id: str = Field(primary_key=True, max_length=32)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    plan_hash: str = Field(max_length=64)
    kind: str = Field(max_length=40)
    result_json: str
