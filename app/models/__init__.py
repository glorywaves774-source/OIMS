# Models are imported here so "from app.models import X" works and Alembic sees every table.
from .base import TenantMixin, TimestampMixin, as_aware, db, utcnow  # noqa: F401
from .identity import Membership, Organization, PlatformRole, Role, RolePermission, User  # noqa: F401
from .platform import AuditLog, Subscription, SubscriptionPlan, SupportAccessRequest  # noqa: F401
from .office import (AttendanceRecord, Department, LeaveRequest, LeaveType, PerformanceReview,  # noqa: F401
                     StaffProfile, StaffTransfer, TrainingRecord)
from .documents import (Document, DocumentAccessLog, DocumentCategory, DocumentFolder,  # noqa: F401
                        DocumentShare, DocumentVersion)
from .comms import (Announcement, Conversation, ConversationParticipant, Correspondence,  # noqa: F401
                    CorrespondenceAction, Meeting, MeetingDecision, MeetingParticipant, Message,
                    Notification, SequenceCounter, Task, TaskComment)
