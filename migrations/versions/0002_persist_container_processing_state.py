"""persist container processing state"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(op.f('ix_media_assets_filename'), 'media_assets', ['filename'], unique=True)
    op.add_column('publishing_jobs', sa.Column('children', sa.JSON(), server_default='[]', nullable=False))
    op.add_column('publishing_jobs', sa.Column('poll_count', sa.Integer(), server_default='0', nullable=False))


def downgrade():
    op.drop_column('publishing_jobs', 'poll_count')
    op.drop_column('publishing_jobs', 'children')
    op.drop_index(op.f('ix_media_assets_filename'), table_name='media_assets')
