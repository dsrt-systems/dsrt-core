"""c6_5_evidence_claim_tenancy

Revision ID: d56328795f13
Revises: e858f7460f1c
Create Date: 2026-10-14 12:27:48.179108

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd56328795f13'
down_revision: Union[str, None] = 'e858f7460f1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
