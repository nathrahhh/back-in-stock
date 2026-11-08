
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import EmailNotification, Subscriber, WebhookEvent


def utc_now_naive() -> datetime:
    """Return UTC time without timezone info for database DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_pending_subscription(
    db: Session, email: str, sku: str
) -> Subscriber | None:
    stmt = select(Subscriber).where(
        Subscriber.email == email,
        Subscriber.sku == sku,
        Subscriber.status == "pending",
    )
    return db.scalars(stmt).first()


def create_subscription(db: Session, email: str, sku: str) -> Subscriber:
    subscriber = Subscriber(email=email, sku=sku, status="pending")
    db.add(subscriber)
    db.commit()
    db.refresh(subscriber)
    return subscriber


def get_pending_subscribers(db: Session, sku: str) -> list[Subscriber]:
    stmt = (
        select(Subscriber)
        .where(
            Subscriber.sku == sku,
            Subscriber.status == "pending",
        )
        .order_by(Subscriber.id)
    )
    return list(db.scalars(stmt).all())


def claim_webhook_event(
    db: Session,
    event_id: str,
    sku: str,
    quantity: int,
    stale_after_minutes: int = 10,
) -> bool:
    """
    Claim a webhook event for processing.

    Returns True if this request can process the event.
    Returns False if it has already been processed or is
    currently being handled by another request.
    """
    event = WebhookEvent(
        event_id=event_id,
        sku=sku,
        quantity=quantity,
        status="processing",
    )

    db.add(event)

    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()

    existing = db.scalars(
        select(WebhookEvent).where(WebhookEvent.event_id == event_id)
    ).first()

    if existing is None:
        return False

    now = utc_now_naive()
    stale_before = now - timedelta(minutes=stale_after_minutes)

    result = db.execute(
        update(WebhookEvent)
        .where(
            WebhookEvent.id == existing.id,
            or_(
                WebhookEvent.status == "failed",
                and_(
                    WebhookEvent.status == "processing",
                    WebhookEvent.updated_at < stale_before,
                ),
            ),
        )
        .values(
            status="processing",
            quantity=quantity,
            last_error=None,
            processed_at=None,
            updated_at=now,
        )
    )

    db.commit()
    return result.rowcount == 1


def update_webhook_event(
    db: Session,
    event_id: str,
    status: str,
    error: str | None = None,
) -> None:
    event = db.scalars(
        select(WebhookEvent).where(WebhookEvent.event_id == event_id)
    ).first()

    if event is None:
        return

    now = utc_now_naive()
    event.status = status
    event.last_error = error
    event.updated_at = now

    if status in ("processed", "ignored"):
        event.processed_at = now
    else:
        event.processed_at = None

    db.commit()


def claim_email_notification(
    db: Session,
    subscriber_id: int,
    event_id: str,
    stale_after_minutes: int = 10,
) -> bool:
    """
    Claim an email notification for a subscriber.

    A subscriber can have only one notification record.
    Failed or stale notifications can be retried.
    """
    notification = EmailNotification(
        subscriber_id=subscriber_id,
        event_id=event_id,
        status="sending",
        attempts=1,
    )

    db.add(notification)

    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()

    existing = db.scalars(
        select(EmailNotification).where(
            EmailNotification.subscriber_id == subscriber_id
        )
    ).first()

    if existing is None:
        return False

    now = utc_now_naive()
    stale_before = now - timedelta(minutes=stale_after_minutes)

    result = db.execute(
        update(EmailNotification)
        .where(
            EmailNotification.id == existing.id,
            or_(
                EmailNotification.status.in_(("failed", "pending")),
                and_(
                    EmailNotification.status == "sending",
                    EmailNotification.updated_at < stale_before,
                ),
            ),
        )
        .values(
            event_id=event_id,
            status="sending",
            attempts=EmailNotification.attempts + 1,
            last_error=None,
            updated_at=now,
        )
    )

    db.commit()
    return result.rowcount == 1


def mark_notification_sent(
    db: Session,
    subscriber_id: int,
    provider_message_id: str | None = None,
) -> None:
    """Mark the notification as sent and the subscriber as notified."""
    now = utc_now_naive()

    notification = db.scalars(
        select(EmailNotification).where(
            EmailNotification.subscriber_id == subscriber_id
        )
    ).first()

    if notification is None:
        return

    notification.status = "sent"
    notification.provider_message_id = provider_message_id
    notification.sent_at = now
    notification.updated_at = now
    notification.last_error = None

    subscriber = db.get(Subscriber, subscriber_id)
    if subscriber is not None:
        subscriber.status = "notified"
        subscriber.notified_at = now

    db.commit()


def mark_notification_failed(
    db: Session,
    subscriber_id: int,
    error: str,
) -> None:
    """Mark a failed delivery so it can be retried later."""
    notification = db.scalars(
        select(EmailNotification).where(
            EmailNotification.subscriber_id == subscriber_id
        )
    ).first()

    if notification is None:
        return

    notification.status = "failed"
    notification.last_error = error[:2000]
    notification.updated_at = utc_now_naive()

    db.commit()
