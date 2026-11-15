"""In-app notifications (with optional email) and reference numbers."""
from datetime import date

from flask import g, has_request_context
from sqlalchemy import select

from app.extensions import db
from app.models import Notification, SequenceCounter, User
from app.security import external_url, mail_configured, send_email


def notify(user_ids, kind, title, body=None, endpoint=None, organization_id=None, dedupe_key=None,
           exclude_current=True, **url_values):
    """Create one in-app notification per user and email those who allow it.

    ``endpoint``/``url_values`` build the link. ``dedupe_key`` prevents repeats
    (e.g. a reminder for the same task) for the same user.
    """
    from flask_login import current_user

    org_id = organization_id or g.get("tenant_id")
    link = None
    if endpoint:
        from flask import url_for
        link = url_for(endpoint, **url_values)
    me = current_user.id if (has_request_context() and current_user and current_user.is_authenticated) else None
    sent = 0
    for uid in {u for u in user_ids if u}:
        if exclude_current and uid == me:
            continue
        if dedupe_key and db.session.execute(select(Notification.id).where(
                Notification.user_id == uid, Notification.dedupe_key == dedupe_key)).first():
            continue
        db.session.add(Notification(organization_id=org_id, user_id=uid, kind=kind, title=title[:250],
                                    body=(body or "")[:1000] or None, link=link, dedupe_key=dedupe_key))
        sent += 1
        user = db.session.get(User, uid)
        if user and user.email_notifications and user.is_enabled and mail_configured():
            text = f"{title}\n\n{body or ''}\n"
            if endpoint:
                text += f"\nOpen: {external_url(endpoint, **url_values)}\n"
            text += "\nYou can turn off these emails in My profile."
            send_email(user.email, f"OIMS: {title}", text)
    return sent


def unread_count(user_id, organization_id):
    from sqlalchemy import func
    return db.session.scalar(select(func.count(Notification.id)).where(
        Notification.user_id == user_id, Notification.organization_id == organization_id,
        Notification.read_at.is_(None))) or 0


def next_reference(prefix, organization_id=None, year=None):
    """Allocate the next reference number, e.g. IN/2026/0007. Safe under concurrency on PostgreSQL."""
    org_id = organization_id or g.get("tenant_id")
    year = year or date.today().year
    key = f"{prefix}-{year}"
    stmt = select(SequenceCounter).where(SequenceCounter.organization_id == org_id, SequenceCounter.key == key)
    if db.engine.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    counter = db.session.execute(stmt).scalar_one_or_none()
    if counter is None:
        counter = SequenceCounter(organization_id=org_id, key=key, value=0)
        db.session.add(counter)
        db.session.flush()
    counter.value += 1
    db.session.flush()
    return f"{prefix}/{year}/{counter.value:04d}"


def working_days(start, end):
    """Monday–Friday days between two dates, inclusive."""
    from datetime import timedelta
    if end < start:
        return 0
    days, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            days += 1
        d += timedelta(days=1)
    return days
