import unittest
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_db
from main import app


class EmbedPageTests(unittest.TestCase):
    """Uses a private in-memory SQLite database, not back_in_stock.db."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        session_factory = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        self._original_lifespan = app.router.lifespan_context
        engine = self.engine

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

    def test_embed_returns_html(self):
        response = self.client.get("/embed")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("<form", response.text)

    def test_embed_html_contains_widget_content(self):
        html = self.client.get("/embed").text
        self.assertIn('id="email"', html)
        self.assertIn('type="email"', html)
        self.assertIn('id="sku"', html)
        self.assertIn('id="submit-button"', html)
        self.assertIn("for=\"email\"", html)
        self.assertIn("for=\"sku\"", html)
        self.assertIn("aria-live", html)
        self.assertIn('fetch("/api/requests"', html)
        self.assertIn("Content-Type", html)
        self.assertIn("application/json", html)
        self.assertIn("JSON.stringify", html)
        self.assertIn("requestInProgress", html)
        self.assertIn("submitButton.disabled = true", html)
        self.assertIn("status === 409", html)
        self.assertIn("You're on the list", html)

    def test_embed_form_integrates_with_signup_api(self):
        embed = self.client.get("/embed")
        self.assertEqual(embed.status_code, 200)
        self.assertIn('fetch("/api/requests"', embed.text)

        created = self.client.post(
            "/api/requests",
            json={"email": "shopper@example.com", "sku": "WIDGET-42"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["email"], "shopper@example.com")
        self.assertEqual(created.json()["sku"], "WIDGET-42")

        duplicate = self.client.post(
            "/api/requests",
            json={"email": "shopper@example.com", "sku": "WIDGET-42"},
        )
        self.assertEqual(duplicate.status_code, 409)


if __name__ == "__main__":
    unittest.main()
