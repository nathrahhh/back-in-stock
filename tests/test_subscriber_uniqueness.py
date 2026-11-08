import unittest
from datetime import datetime, timezone

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base
from models import Subscriber


class SubscriberUniquenessTests(unittest.TestCase):
    """Uses an in-memory SQLite database, not back_in_stock.db."""

    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(bind=self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_partial_unique_index_is_created(self):
        indexes = inspect(self.engine).get_indexes("subscribers")
        match = next(
            (idx for idx in indexes if idx["name"] == "uq_subscriber_pending_email_sku"),
            None,
        )
        self.assertIsNotNone(match)
        self.assertTrue(match["unique"])
        self.assertEqual(match["column_names"], ["email", "sku"])

        with self.engine.connect() as conn:
            sql = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type='index' AND name='uq_subscriber_pending_email_sku'"
                )
            ).scalar_one()
        self.assertIn("WHERE status = 'pending'", sql)

    def test_duplicate_pending_subscription_is_rejected(self):
        self.session.add(Subscriber(email="buyer@example.com", sku="SKU-1"))
        self.session.commit()

        self.session.add(Subscriber(email="buyer@example.com", sku="SKU-1"))
        with self.assertRaises(IntegrityError):
            self.session.commit()

    def test_subscription_allowed_after_previous_is_notified(self):
        original = Subscriber(email="buyer@example.com", sku="SKU-1")
        self.session.add(original)
        self.session.commit()

        original.status = "notified"
        original.notified_at = datetime.now(timezone.utc)
        self.session.commit()

        self.session.add(Subscriber(email="buyer@example.com", sku="SKU-1"))
        self.session.commit()

        rows = self.session.query(Subscriber).filter_by(
            email="buyer@example.com", sku="SKU-1"
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row.status for row in rows}, {"notified", "pending"})

    def test_same_email_different_sku_is_allowed(self):
        self.session.add(Subscriber(email="buyer@example.com", sku="SKU-1"))
        self.session.add(Subscriber(email="buyer@example.com", sku="SKU-2"))
        self.session.commit()
        self.assertEqual(self.session.query(Subscriber).count(), 2)


if __name__ == "__main__":
    unittest.main()
