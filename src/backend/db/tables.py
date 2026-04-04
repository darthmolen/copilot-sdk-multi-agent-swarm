"""SQLAlchemy Table definitions for swarm state persistence."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = sa.MetaData()

swarms = sa.Table(
    "swarms",
    metadata,
    sa.Column("id", UUID(as_uuid=True), primary_key=True),
    sa.Column("goal", sa.Text, nullable=False),
    sa.Column("qa_refined_goal", sa.Text),
    sa.Column("phase", sa.String(30), nullable=False, server_default="starting"),
    sa.Column("template_key", sa.String(100)),
    sa.Column("synthesis_session_id", sa.String(200)),
    sa.Column("report", sa.Text),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
    ),
    sa.Column("completed_at", sa.DateTime(timezone=True)),
    sa.Column("current_round", sa.Integer, nullable=False, server_default="0"),
    sa.Column("max_rounds", sa.Integer, nullable=False, server_default="8"),
    sa.Column("suspended_at", sa.DateTime(timezone=True)),
)

tasks = sa.Table(
    "tasks",
    metadata,
    sa.Column("swarm_id", UUID(as_uuid=True), sa.ForeignKey("swarms.id"), nullable=False),
    sa.Column("id", sa.String(50), nullable=False),
    sa.Column("subject", sa.Text, nullable=False),
    sa.Column("description", sa.Text, nullable=False),
    sa.Column("worker_role", sa.String(100), nullable=False),
    sa.Column("worker_name", sa.String(100), nullable=False),
    sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
    sa.Column("blocked_by", JSONB, nullable=False, server_default="[]"),
    sa.Column("result", sa.Text, nullable=False, server_default=""),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()
    ),
    sa.PrimaryKeyConstraint("swarm_id", "id"),
)

agents = sa.Table(
    "agents",
    metadata,
    sa.Column("swarm_id", UUID(as_uuid=True), sa.ForeignKey("swarms.id"), nullable=False),
    sa.Column("name", sa.String(100), nullable=False),
    sa.Column("role", sa.String(200), nullable=False),
    sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
    sa.Column("session_id", sa.String(200)),
    sa.Column("status", sa.String(30), nullable=False, server_default="idle"),
    sa.Column("tasks_completed", sa.Integer, nullable=False, server_default="0"),
    sa.PrimaryKeyConstraint("swarm_id", "name"),
)

messages = sa.Table(
    "messages",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("swarm_id", UUID(as_uuid=True), sa.ForeignKey("swarms.id"), nullable=False),
    sa.Column("sender", sa.String(100), nullable=False),
    sa.Column("recipient", sa.String(100), nullable=False),
    sa.Column("content", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Index("idx_messages_swarm", "swarm_id", "created_at"),
)

events = sa.Table(
    "events",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("swarm_id", UUID(as_uuid=True)),
    sa.Column("event_type", sa.String(100), nullable=False),
    sa.Column("data_json", JSONB, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Index("idx_events_swarm", "swarm_id", "created_at"),
    sa.Index("idx_events_type", "swarm_id", "event_type"),
)

files = sa.Table(
    "files",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
    sa.Column("swarm_id", UUID(as_uuid=True), sa.ForeignKey("swarms.id"), nullable=False),
    sa.Column("path", sa.Text, nullable=False),
    sa.Column("size_bytes", sa.BigInteger, nullable=False, server_default="0"),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.UniqueConstraint("swarm_id", "path", name="uq_files_swarm_path"),
)
