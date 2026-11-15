"""Correspondence, meetings, tasks, notifications, announcements and messages (Phase 2)."""
from .base import TenantMixin, TimestampMixin, db, utcnow


class SequenceCounter(TenantMixin, db.Model):
    """Per-organization counters for reference numbers (e.g. IN/2026/0007)."""

    __tablename__ = "sequence_counters"
    __table_args__ = (db.UniqueConstraint("organization_id", "key", name="uq_counter_org_key"),)

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(40), nullable=False)
    value = db.Column(db.Integer, nullable=False, default=0)


class Correspondence(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "correspondence"
    __table_args__ = (db.UniqueConstraint("organization_id", "reference_no", name="uq_corr_org_ref"),)

    KINDS = {"incoming": ("IN", "Incoming letter"), "outgoing": ("OUT", "Outgoing letter"),
             "memo": ("MEMO", "Internal memo")}
    STATUSES = ("registered", "assigned", "in_progress", "awaiting_approval", "approved", "responded", "closed")
    PRIORITIES = ("normal", "high", "urgent")

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False, index=True)
    reference_no = db.Column(db.String(40), nullable=False)
    external_reference = db.Column(db.String(120))
    subject = db.Column(db.String(300), nullable=False)
    party = db.Column(db.String(250))  # sender (incoming) or recipient (outgoing / memo)
    letter_date = db.Column(db.Date)
    received_date = db.Column(db.Date)
    summary = db.Column(db.Text)
    priority = db.Column(db.String(10), nullable=False, default="normal")
    confidential = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="registered", index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    response_due = db.Column(db.Date, index=True)
    in_reply_to_id = db.Column(db.Integer, db.ForeignKey("correspondence.id", ondelete="SET NULL"))
    archived = db.Column(db.Boolean, nullable=False, default=False, index=True)
    due_notified_at = db.Column(db.DateTime(timezone=True))

    department = db.relationship("Department")
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    in_reply_to = db.relationship("Correspondence", remote_side=[id])
    actions = db.relationship("CorrespondenceAction", order_by="CorrespondenceAction.created_at",
                              cascade="all, delete-orphan")


class CorrespondenceAction(TenantMixin, db.Model):
    __tablename__ = "correspondence_actions"

    id = db.Column(db.Integer, primary_key=True)
    correspondence_id = db.Column(db.Integer, db.ForeignKey("correspondence.id", ondelete="CASCADE"), nullable=False, index=True)
    action = db.Column(db.String(30), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    actor = db.relationship("User", foreign_keys=[actor_id])
    to_user = db.relationship("User", foreign_keys=[to_user_id])


class Meeting(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "meetings"

    STATUSES = ("scheduled", "held", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    meeting_type = db.Column(db.String(80))
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    ends_at = db.Column(db.DateTime(timezone=True))
    location = db.Column(db.String(250))
    online_link = db.Column(db.String(500))
    agenda = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="scheduled")
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    organizer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    minutes = db.Column(db.Text)
    minutes_recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    department = db.relationship("Department")
    organizer = db.relationship("User", foreign_keys=[organizer_id])
    participants = db.relationship("MeetingParticipant", cascade="all, delete-orphan", lazy="selectin")
    decisions = db.relationship("MeetingDecision", cascade="all, delete-orphan", order_by="MeetingDecision.id")


class MeetingParticipant(TenantMixin, db.Model):
    __tablename__ = "meeting_participants"
    __table_args__ = (db.UniqueConstraint("meeting_id", "user_id", name="uq_meetingpart_meeting_user"),)

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    response = db.Column(db.String(20), nullable=False, default="invited")  # invited / accepted / declined
    attended = db.Column(db.Boolean)

    user = db.relationship("User")


class MeetingDecision(TenantMixin, db.Model):
    __tablename__ = "meeting_decisions"

    id = db.Column(db.Integer, primary_key=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)


class Task(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "tasks"

    PRIORITIES = ("low", "normal", "high", "urgent")
    STATUSES = ("todo", "in_progress", "blocked", "done", "cancelled")
    OPEN = ("todo", "in_progress", "blocked")

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    priority = db.Column(db.String(10), nullable=False, default="normal")
    status = db.Column(db.String(20), nullable=False, default="todo", index=True)
    due_date = db.Column(db.Date, index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    meeting_id = db.Column(db.Integer, db.ForeignKey("meetings.id", ondelete="SET NULL"), index=True)
    # Work breakdown: a task can belong to a project activity, have a parent task (subtask),
    # or be a corrective action for a project issue or risk.
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    issue_id = db.Column(db.Integer, db.ForeignKey("project_issues.id", ondelete="SET NULL"), index=True)
    risk_id = db.Column(db.Integer, db.ForeignKey("risks.id", ondelete="SET NULL"), index=True)
    completed_at = db.Column(db.DateTime(timezone=True))
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    department = db.relationship("Department")
    meeting = db.relationship("Meeting")
    project = db.relationship("Project")
    activity = db.relationship("Activity")
    parent = db.relationship("Task", remote_side=[id], backref="subtasks")
    issue = db.relationship("Issue")
    risk = db.relationship("RiskItem")
    comments = db.relationship("TaskComment", cascade="all, delete-orphan", order_by="TaskComment.created_at")


class TaskComment(TenantMixin, db.Model):
    __tablename__ = "task_comments"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    author = db.relationship("User")


class Notification(TenantMixin, db.Model):
    __tablename__ = "notifications"
    __table_args__ = (db.UniqueConstraint("user_id", "dedupe_key", name="uq_notification_user_key"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    body = db.Column(db.String(1000))
    link = db.Column(db.String(300))
    dedupe_key = db.Column(db.String(120))
    read_at = db.Column(db.DateTime(timezone=True), index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class Announcement(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "announcements"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    body = db.Column(db.Text, nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"))  # NULL = everyone
    pinned = db.Column(db.Boolean, nullable=False, default=False)
    expires_on = db.Column(db.Date)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    department = db.relationship("Department")
    author = db.relationship("User")


class Conversation(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "conversations"

    id = db.Column(db.Integer, primary_key=True)
    subject = db.Column(db.String(200))
    last_message_at = db.Column(db.DateTime(timezone=True), index=True)

    participants = db.relationship("ConversationParticipant", cascade="all, delete-orphan", lazy="selectin")
    messages = db.relationship("Message", cascade="all, delete-orphan", order_by="Message.created_at")


class ConversationParticipant(TenantMixin, db.Model):
    __tablename__ = "conversation_participants"
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id", name="uq_convpart_conv_user"),)

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    last_read_at = db.Column(db.DateTime(timezone=True))

    user = db.relationship("User")


class Message(TenantMixin, db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)

    sender = db.relationship("User")
