import concurrent.futures
import threading

import pytest

from codex_harness_connect import sessions, storage
from codex_harness_connect.sessions import SessionService, session_db


@pytest.fixture
def admission(tmp_path, monkeypatch):
    """Real durable receipts, with every subprocess launch stopped at Popen."""
    calls = []
    lock = threading.Lock()

    def failed_spawn(argv, **kwargs):
        with lock:
            calls.append(argv[-1])
        raise OSError("Synthetic worker startup failure")

    monkeypatch.setattr(sessions.subprocess, "Popen", failed_spawn)

    def make(capacity=3):
        monkeypatch.setattr(storage, "MAX_SESSIONS", capacity)
        return SessionService(tmp_path / "state")

    return make, calls, tmp_path, monkeypatch


def launch(service, path, request_id=None, **kwargs):
    return service.start(["/synthetic/worker", "task"], str(path),
                         request_id=request_id, **kwargs)


def test_concurrent_distinct_requests_admit_exact_capacity_before_popen(admission):
    make, calls, path, _ = admission
    service = make(3)
    barrier = threading.Barrier(8)

    def attempt(number):
        barrier.wait(timeout=5)
        try:
            return launch(service, path, f"{number:032x}")
        except storage.StorageCapacityError as error:
            assert error.capacity == 3
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(attempt, range(1, 9)))
    accepted = [item for item in results if item is not None]
    assert len(accepted) == len(calls) == len(set(calls)) == 3
    assert {item["session_id"] for item in accepted} == set(calls)
    assert all(item["status"] == "failed" for item in accepted)
    with session_db(service.state_root) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3
        assert db.execute("SELECT COUNT(DISTINCT request_id) FROM sessions").fetchone()[0] == 3


def test_same_request_race_at_capacity_launches_once_and_replay_keeps_receipt(admission):
    make, calls, path, _ = admission
    service = make(1)
    barrier = threading.Barrier(4)

    def attempt(_):
        barrier.wait(timeout=5)
        return launch(service, path, "1" * 32)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))
    sid = results[0]["session_id"]
    assert {item["session_id"] for item in results} == {sid}
    assert calls == [sid]
    assert launch(service, path, "1" * 32)["session_id"] == sid
    assert service.lookup_request("1" * 32)["session_id"] == sid
    with pytest.raises(ValueError, match="different launch"):
        service.start(["/synthetic/worker", "changed task"], str(path), request_id="1" * 32)
    with pytest.raises(storage.StorageCapacityError):
        launch(service, path, "2" * 32)
    assert calls == [sid]


def test_failed_lost_and_no_request_sessions_all_consume_capacity(admission):
    make, calls, path, _ = admission
    service = make(3)
    failed = launch(service, path, "1" * 32)
    lost = launch(service, path, "2" * 32)
    with session_db(service.state_root) as db:
        db.execute("UPDATE sessions SET status='lost' WHERE session_id=?", (lost["session_id"],))
    anonymous = launch(service, path)
    assert failed["status"] == "failed"
    assert service.lookup_request("2" * 32)["status"] == "lost"
    assert anonymous["request_id"] is None
    with pytest.raises(storage.StorageCapacityError):
        launch(service, path)
    with pytest.raises(storage.StorageCapacityError):
        launch(service, path, "3" * 32)
    assert launch(service, path, "2" * 32)["session_id"] == lost["session_id"]
    assert len(calls) == 3
    with session_db(service.state_root) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 3


def test_reopening_preserves_original_policy_despite_changed_default(admission):
    make, calls, path, monkeypatch = admission
    service = make(2)
    first = launch(service, path, "1" * 32)
    monkeypatch.setattr(storage, "MAX_SESSIONS", 1)
    reopened = SessionService(service.state_root)
    second = launch(reopened, path, "2" * 32)
    monkeypatch.setattr(storage, "MAX_SESSIONS", 99)
    reopened_again = SessionService(service.state_root)
    with pytest.raises(storage.StorageCapacityError) as error:
        launch(reopened_again, path, "3" * 32)
    assert error.value.capacity == 2
    assert reopened_again.lookup_request("1" * 32)["session_id"] == first["session_id"]
    assert launch(reopened_again, path, "2" * 32)["session_id"] == second["session_id"]
    assert calls == [first["session_id"], second["session_id"]]


def test_policyless_legacy_store_over_capacity_remains_recoverable(admission):
    make, calls, path, monkeypatch = admission
    original = make(4)
    jobs = [launch(original, path, f"{i:032x}") for i in range(1, 5)]
    with session_db(original.state_root) as db:
        before = [tuple(row) for row in db.execute("SELECT session_id,request_id,status,"
                                                   "launch_fingerprint FROM sessions ORDER BY session_id")]
        # Model the pre-admission store: accepted receipts exist, policy does not.
        db.execute("DROP TABLE storage_policy")
    monkeypatch.setattr(storage, "MAX_SESSIONS", 2)
    migrated = SessionService(original.state_root)
    with pytest.raises(storage.StorageCapacityError) as error:
        launch(migrated, path, "9" * 32)
    assert error.value.capacity == 2
    for i, job in enumerate(jobs, 1):
        assert migrated.lookup_request(f"{i:032x}")["session_id"] == job["session_id"]
        assert launch(migrated, path, f"{i:032x}")["session_id"] == job["session_id"]
    with session_db(migrated.state_root) as db:
        after = [tuple(row) for row in db.execute("SELECT session_id,request_id,status,"
                                                  "launch_fingerprint FROM sessions ORDER BY session_id")]
    assert after == before
    assert len(calls) == 4


@pytest.mark.parametrize("kwargs", [
    {"cwd": "/" + "x" * 4096},
    {"cwd": "/" + "🌍" * 1024},
    {"argv": ["/" + "x" * 1025]},
    {"argv": ["/" + "🌍" * 257]},
    {"env_overrides": {"SYNTHETIC": "x" * (256 * 1024)}},
    {"env_overrides": {"SYNTHETIC": "🌍" * (256 * 1024 // 4)}},
    {"argv": ["/synthetic/worker", "x" * (256 * 1024)]},
])
def test_oversized_immutable_launch_fields_reject_before_receipt_or_popen(admission, kwargs):
    make, calls, path, _ = admission
    service = make()
    arguments = {"argv": ["/synthetic/worker"], "cwd": str(path), "request_id": "1" * 32,
                 **kwargs}
    with pytest.raises(ValueError):
        service.start(**arguments)
    assert calls == []
    with session_db(service.state_root) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
