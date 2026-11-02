from sqlalchemy import BigInteger, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ProjectLegal(TimestampMixin, Base):
    """The developer's legal details for a project, printed on welcome letters and payment demands."""

    __tablename__ = "project_legal"

    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    developer_legal_name: Mapped[str | None] = mapped_column(String(200))
    rera_number: Mapped[str | None] = mapped_column(String(50))
    registered_address: Mapped[str | None] = mapped_column(Text)
    signatory_name: Mapped[str | None] = mapped_column(String(150))
    signatory_designation: Mapped[str | None] = mapped_column(String(100))
    gstin: Mapped[str | None] = mapped_column(String(15))
    cin: Mapped[str | None] = mapped_column(String(21))  # optional: partnerships and LLPs have none
    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )


class ProjectBank(TimestampMixin, Base):
    """Where customers pay for this project. The account number is stored encrypted."""

    __tablename__ = "project_bank_details"

    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    bank_name: Mapped[str | None] = mapped_column(String(150))
    account_holder_name: Mapped[str | None] = mapped_column(String(200))
    account_number_enc: Mapped[str | None] = mapped_column(
        Text
    )  # Fernet, key derived from SECRET_KEY
    account_last4: Mapped[str | None] = mapped_column(String(4))
    ifsc: Mapped[str | None] = mapped_column(String(11))
    branch: Mapped[str | None] = mapped_column(String(150))
    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
