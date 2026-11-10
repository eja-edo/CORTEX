from wp5_support import world  # noqa: F401
import pytest  # noqa: E402

from cortex_leads.config import get_settings  # noqa: E402
from cortex_leads.notify.mailer import MemoryMailer, set_mailer  # noqa: E402


@pytest.fixture
def mail(monkeypatch):
    """A mailbox the server can send to, and a public address for the links in it (without both, no one can be invited)."""
    box = MemoryMailer()
    set_mailer(box)
    monkeypatch.setattr(get_settings(), "PUBLIC_BASE_URL", "https://cortex.example.vn")
    yield box
    set_mailer(None)
