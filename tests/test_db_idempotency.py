import time
from datetime import datetime

import pytest

from db.database import SessionLocal
from db.models import User, Video, VideoStatus
from service.video_service import claim_video_processing


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def _make_user(db):
    ts = int(time.time() * 1000)
    u = User(
        username=f"u{ts}",
        email=f"u{ts}@test.local",
        hashed_password="x",
        is_active=True,
        storage_limit=10**9,
        used_storage=0,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_video_uploaded(db, owner_id: int):
    v = Video(
        title="t",
        status=VideoStatus.UPLOADED,
        uploaded_at=datetime.utcnow(),
        owner_id=owner_id,
        original_path="original/test.mp4",
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return v


def test_claim_only_one_wins(db):
    u = _make_user(db)
    v = _make_video_uploaded(db, owner_id=u.id)

    t1 = claim_video_processing(v.id, lease_seconds=30)
    assert t1 is not None

    t2 = claim_video_processing(v.id, lease_seconds=30)
    assert t2 is None


def test_claim_after_lease_expired(db):
    u = _make_user(db)
    v = _make_video_uploaded(db, owner_id=u.id)

    t1 = claim_video_processing(v.id, lease_seconds=1)
    assert t1 is not None

    time.sleep(1.1)

    t2 = claim_video_processing(v.id, lease_seconds=30)
    assert t2 is not None
    assert t2 != t1
