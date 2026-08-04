from enum import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"
    ACCOUNT_MANAGER = "account_manager"
    PROJECT_MANAGER = "project_manager"
    TEAM_MEMBER = "team_member"
    FINANCE_ADMIN = "finance_admin"
    EXECUTIVE_VIEWER = "executive_viewer"


class UserStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    INVITED = "invited"


class CompanyStatus(StrEnum):
    LEAD = "lead"
    ACTIVE = "active"
    PAUSED = "paused"
    CHURNED = "churned"


class ContactStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class EntityType(StrEnum):
    COMPANY = "company"
    CONTACT = "contact"
    PROJECT = "project"
    MILESTONE = "milestone"
    DOCUMENT = "document"
    CHANGE_REQUEST = "change_request"


class ChangeRequestType(StrEnum):
    SCOPE_ADDITION = "scope_addition"
    SCOPE_REDUCTION = "scope_reduction"
    TIMELINE_CHANGE = "timeline_change"
    BUDGET_CHANGE = "budget_change"
    BUGFIX = "bugfix"
    OTHER = "other"


class ChangeRequestStatus(StrEnum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    PENDING_IMPACT_ASSESSMENT = "pending_impact_assessment"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"
    IN_PROGRESS = "in_progress"
    IMPLEMENTED = "implemented"
    CLOSED = "closed"


class ChangeRequestPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApproverType(StrEnum):
    INTERNAL = "internal"
    CLIENT = "client"


class ProjectStatus(StrEnum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectHealth(StrEnum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    DELAYED = "delayed"


class Currency(StrEnum):
    """ISO 4217 codes — uppercase, unlike other enums here, to match the
    external standard (and Intl.NumberFormat's `currency` option)."""

    GBP = "GBP"
    USD = "USD"
    EUR = "EUR"
    CAD = "CAD"
    AUD = "AUD"
    NZD = "NZD"
    CHF = "CHF"
    JPY = "JPY"
    SEK = "SEK"
    NOK = "NOK"
    DKK = "DKK"
    SGD = "SGD"
    HKD = "HKD"
    AED = "AED"
    INR = "INR"
    ZAR = "ZAR"


class PhaseStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"


class MilestoneStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    AT_RISK = "at_risk"
    COMPLETED = "completed"


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"


class TaskPriority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class SequenceTriggerType(StrEnum):
    MANUAL = "manual"
    ON_PROJECT_COMPLETED = "on_project_completed"
    ON_COMPANY_CREATED = "on_company_created"
    ON_RENEWAL_APPROACHING = "on_renewal_approaching"


class TouchpointChannel(StrEnum):
    EMAIL = "email"
    CALL = "call"
    MEETING = "meeting"
    INTERNAL_TASK = "internal_task"


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TouchpointStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    OVERDUE = "overdue"


class TouchpointOutcome(StrEnum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    AT_RISK = "at_risk"


class ContractStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"
