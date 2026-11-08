
import hmac
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    status,
)
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from crud import (
    claim_email_notification,
    claim_webhook_event,
    create_subscription,
    get_pending_subscribers,
    get_pending_subscription,
    mark_notification_failed,
    mark_notification_sent,
    update_webhook_event,
)
from database import Base, engine, get_db
from models import Subscriber  # noqa: F401
from schemas import (
    StockWebhookRequest,
    SubscriptionRequest,
    SubscriptionResponse,
)
from services import (
    get_stock_details,
    is_product_in_stock,
    send_back_in_stock_email,
)


BASE_DIR = Path(__file__).parent

EMBED_HTML = (BASE_DIR / "templates" / "embed.html").read_text(
    encoding="utf-8"
)

templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates")
)

admin_security = HTTPBasic()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Back in Stock",
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {"message": "Back in Stock API is running!"}


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/embed", response_class=HTMLResponse)
def embed():
    return EMBED_HTML


@app.post(
    "/api/requests",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_request(
    payload: SubscriptionRequest,
    db: Session = Depends(get_db),
):
    existing = get_pending_subscription(
        db,
        payload.email,
        payload.sku,
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending subscription already exists for this email and SKU.",
        )

    try:
        return create_subscription(
            db,
            payload.email,
            payload.sku,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pending subscription already exists for this email and SKU.",
        )


@app.post("/webhooks/stock")
def stock_webhook(
    payload: StockWebhookRequest,
    db: Session = Depends(get_db),
    webhook_secret: str | None = Header(
        default=None,
        alias="X-Webhook-Secret",
    ),
):
    # 1. Authenticate the incoming webhook.
    expected_secret = os.getenv("WEBHOOK_SECRET")

    if not expected_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook authentication is not configured.",
        )

    if webhook_secret is None or not hmac.compare_digest(
        webhook_secret,
        expected_secret,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook secret.",
        )

    # 2. Claim the event to prevent duplicate processing.
    claimed = claim_webhook_event(
        db=db,
        event_id=payload.event_id,
        sku=payload.sku,
        quantity=payload.quantity,
    )

    if not claimed:
        return {
            "status": "duplicate",
            "message": "This webhook event has already been processed or claimed.",
        }

    # 3. Verify actual stock using the store's API.
    try:
        stock_details = get_stock_details(payload.sku)

        if not is_product_in_stock(stock_details):
            update_webhook_event(
                db,
                payload.event_id,
                "ignored",
            )

            return {
                "status": "ignored",
                "message": "The product is not currently in stock.",
            }

        product_name = stock_details.get("name")

    except Exception as exc:
        update_webhook_event(
            db,
            payload.event_id,
            "failed",
            str(exc),
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify the product's current stock.",
        ) from exc

    # 4. Find subscribers waiting for this SKU.
    subscribers = get_pending_subscribers(
        db,
        payload.sku,
    )

    failed_notifications = 0
    sent_notifications = 0

    # 5. Claim and send one notification per subscriber.
    for subscriber in subscribers:
        claimed_notification = claim_email_notification(
            db=db,
            subscriber_id=subscriber.id,
            event_id=payload.event_id,
        )

        if not claimed_notification:
            continue

        try:
            provider_message_id = send_back_in_stock_email(
                email=subscriber.email,
                sku=subscriber.sku,
                product_name=product_name,
                idempotency_key=f"back-in-stock-subscriber-{subscriber.id}",
            )

            mark_notification_sent(
                db=db,
                subscriber_id=subscriber.id,
                provider_message_id=provider_message_id,
            )

            sent_notifications += 1

        except Exception as exc:
            mark_notification_failed(
                db=db,
                subscriber_id=subscriber.id,
                error=str(exc),
            )

            failed_notifications += 1

    # 6. Update the webhook event based on delivery results.
    if failed_notifications:
        update_webhook_event(
            db,
            payload.event_id,
            "failed",
            f"{failed_notifications} notification(s) failed.",
        )

        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"{failed_notifications} notification(s) could not be sent. "
                "The event can be retried."
            ),
        )

    update_webhook_event(
        db,
        payload.event_id,
        "processed",
    )

    return {
        "status": "processed",
        "sku": payload.sku,
        "notifications_sent": sent_notifications,
    }


@app.get("/admin", response_class=HTMLResponse)
def admin(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(admin_security),
    db: Session = Depends(get_db),
):
    # 1. Read the admin password from the environment.
    expected_username = "admin"
    expected_password = os.getenv("ADMIN_PASSWORD")

    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin authentication is not configured.",
        )

    # 2. Authenticate the admin.
    username_valid = secrets.compare_digest(
        credentials.username,
        expected_username,
    )

    password_valid = secrets.compare_digest(
        credentials.password,
        expected_password,
    )

    if not username_valid or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect admin credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )

    # 3. Retrieve subscriptions from the database.
    subscribers = db.scalars(
        select(Subscriber).order_by(
            Subscriber.created_at.desc()
        )
    ).all()

    # 4. Render the admin dashboard.
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "subscribers": subscribers,
        },
    )
