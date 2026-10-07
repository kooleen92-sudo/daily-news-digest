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
