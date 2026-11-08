import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app
from models import Subscriber


class ApiRequestTests(unittest.TestCase):
    """Uses a private in-memory SQLite database, not back_in_stock.db."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        self._original_lifespan = app.router.lifespan_context
        engine = self.engine
        session_factory = self.SessionLocal

        @asynccontextmanager
        async def test_lifespan(app_instance):
            Base.metadata.create_all(bind=engine)
            yield

        def override_get_db():
            db = session_factory()
            try:
                yield db
            finally:
                db.close()

        app.router.lifespan_context = test_lifespan
        app.dependency_overrides[get_db] = override_get_db
        self._client_cm = TestClient(app)
        self.client = self._client_cm.__enter__()

    def tearDown(self):
        self._client_cm.__exit__(None, None, None)
        app.dependency_overrides.clear()
        app.router.lifespan_context = self._original_lifespan
        self.engine.dispose()

    def test_successful_subscription(self):
        response = self.client.post(
            "/api/requests",
            json={"email": "  Buyer@Example.com ", "sku": "  SKU-1  "},
        )
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["email"], "buyer@example.com")
        self.assertEqual(body["sku"], "SKU-1")
        self.assertEqual(body["status"], "pending")
        self.assertIsInstance(body["id"], int)
        self.assertTrue(body["created_at"])

    def test_invalid_email(self):
        response = self.client.post(
            "/api/requests",
            json={"email": "not-an-email", "sku": "SKU-1"},
        )
        self.assertEqual(response.status_code, 422)

    def test_missing_sku(self):
        response = self.client.post(
            "/api/requests",
            json={"email": "buyer@example.com"},
        )
        self.assertEqual(response.status_code, 422)

    def test_duplicate_pending_subscription(self):
        payload = {"email": "buyer@example.com", "sku": "SKU-1"}
        first = self.client.post("/api/requests", json=payload)
        second = self.client.post("/api/requests", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertIn("pending subscription already exists", second.json()["detail"])

    def test_resubscription_after_notified(self):
        payload = {"email": "buyer@example.com", "sku": "SKU-1"}
        first = self.client.post("/api/requests", json=payload)
        self.assertEqual(first.status_code, 201)

        db = self.SessionLocal()
        try:
            subscriber = db.scalars(
                select(Subscriber).where(Subscriber.id == first.json()["id"])
            ).one()
            subscriber.status = "notified"
            subscriber.notified_at = datetime.now(timezone.utc)
            db.commit()
        finally:
            db.close()

        second = self.client.post("/api/requests", json=payload)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json()["status"], "pending")
        self.assertNotEqual(second.json()["id"], first.json()["id"])


if __name__ == "__main__":
    unittest.main()
