import tempfile
import unittest
from pathlib import Path

from mail_bark_forwarder.state import StateStore


class StateStoreTest(unittest.TestCase):
    def test_deduplicates_by_uid_and_message_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "state.sqlite3"
            state = StateStore(str(db))
            self.assertFalse(state.is_processed("a", "1", "<m1>"))
            state.mark_processed("a", "1", "<m1>")
            self.assertTrue(state.is_processed("a", "1", "<m1>"))
            self.assertTrue(state.is_processed("a", "2", "<m1>"))
            self.assertFalse(state.is_processed("b", "2", "<m1>"))
            state.close()


if __name__ == "__main__":
    unittest.main()
