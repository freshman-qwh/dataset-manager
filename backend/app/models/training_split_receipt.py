from sqlmodel import Field, SQLModel


class TrainingSplitReceipt(SQLModel, table=True):
    """The most recent confirmed split response for safe request retries."""

    __tablename__ = "training_split_receipts"

    dataset_id: int = Field(foreign_key="datasets.id", primary_key=True)
    fingerprint: str = Field(max_length=64)
    result_json: str
