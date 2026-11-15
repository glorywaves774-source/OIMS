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
from .programmes import (Activity, ActivityReport, BudgetCategory, BudgetLine, BudgetRevision,  # noqa: F401
                         BudgetRevisionLine, Donor, Evaluation, Expenditure, FundingAgreement, FundingReceipt,
                         Indicator, IndicatorResult, IndicatorTarget, LearningItem, Location, Milestone,
                         MonitoringVisit, Programme, ProgrammeReport, ProgrammeTeamMember, ResultNode, Workplan)
from .projects import (Component, Deliverable, Issue, Project, ProjectClosure, ProjectTeamMember,  # noqa: F401
                       RiskItem)
from .meal import (ActivityAttendance, Beneficiary, ConsentRecord, DataForm, Enrollment, Feedback,  # noqa: F401
                   FeedbackAction, FormField, FormSubmission, Household, ServiceRecord)
from .procurement import (Asset, AssetEvent, GoodsReceipt, PurchaseOrder, PurchaseOrderItem,  # noqa: F401
                          PurchaseRequest, PurchaseRequestItem, Quotation, Supplier)
