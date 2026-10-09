import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import SingleInstanceLock


def test_single_instance_lock_class_exists():
    assert isinstance(SingleInstanceLock, type)


def test_single_instance_lock_context_manager_protocol():
    assert hasattr(SingleInstanceLock, '__enter__')


def test_single_instance_lock_acquire_returns_true_and_writes_pid_started_at(tmp_path):
    lock_file = tmp_path / "test.lock"
    lock = SingleInstanceLock(lock_file)
    with lock as acquired:
        assert acquired is True
        content = lock_file.read_text()
        assert "pid=" in content
        assert "started_at=" in content


def test_single_instance_lock_second_acquire_returns_false(tmp_path):
    lock_file = tmp_path / "test.lock"
    first_lock = SingleInstanceLock(lock_file)
    with first_lock as acquired:
        assert acquired is True
        second_lock = SingleInstanceLock(lock_file)
        with second_lock as second_acquired:
            assert second_acquired is False


def test_single_instance_lock_reacquire_after_context_exit(tmp_path):
    lock_file = tmp_path / "test.lock"
    with SingleInstanceLock(lock_file):
        pass
    with SingleInstanceLock(lock_file) as acquired:
        assert acquired is True


def test_single_instance_lock_file_not_overwritten(tmp_path):
    lock_file = tmp_path / "test.lock"
    first_lock = SingleInstanceLock(lock_file)
    with first_lock as acquired:
        assert acquired is True
        original_content = lock_file.read_text()
        second_lock = SingleInstanceLock(lock_file)
        with second_lock as second_acquired:
            assert second_acquired is False
            assert lock_file.read_text() == original_content


def test_single_instance_lock_recovers_from_dead_pid(tmp_path):
    lock_file = tmp_path / "test.lock"
    # Write a lock with a nonexistent PID
    dead_pid = 999999
    lock_file.write_text(f"pid={dead_pid}\nstarted_at=2026-10-01T00:00:00+00:00\n", encoding="utf-8")

    # A new lock should detect dead pid, reclaim the lock and acquire successfully
    new_lock = SingleInstanceLock(lock_file)
    with new_lock as acquired:
        assert acquired is True
        assert f"pid={dead_pid}" not in lock_file.read_text()


def test_single_instance_lock_recovers_from_expired_timestamp(tmp_path):
    lock_file = tmp_path / "test.lock"
    # Write an expired lock timestamp (age > max_age_seconds=1)
    lock_file.write_text(f"pid=1\nstarted_at=2020-01-01T00:00:00+00:00\n", encoding="utf-8")

    new_lock = SingleInstanceLock(lock_file, max_age_seconds=1)
    with new_lock as acquired:
        assert acquired is True

