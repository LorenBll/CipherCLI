"""JSON logging library implementing the shared logging standard.

Logs are appended to a single JSON file containing a list of events. Each event
has a timestamp, a type (ERROR, WARN, INFO, DEBUG), a title, arbitrary
JSON-serializable data, and a SHA-256 hash computed over the timestamp, title
and data so each entry can be referenced uniquely by (project, hash).

Log files older than the 14-day retention period are removed at startup. The
expiration check compares dates only.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import date, datetime
from pathlib import Path

_LOG_FILE_STEM_FORMAT = "%d-%m-%Y_%H.%M.%S"
_RETENTION_DAYS = 14

_lock = threading.Lock()
_project_name = "unknown"
_debug_enabled = False
_log_dir: Path | None = None
_log_file: Path | None = None
_events: list[dict] = []


def _canonical_serialize(value) -> str:
	"""Canonical JSON serialization used for hashing."""
	return json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))


def _compute_hash(timestamp: str, title: str, data) -> str:
	"""SHA-256 hash over the canonical serialization of timestamp, title and data."""
	payload = _canonical_serialize([timestamp, title, data])
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _default_log_dir() -> Path:
	"""Default log directory: <project root>/logs where project root contains src/."""
	return Path(__file__).resolve().parent.parent.parent / "logs"


def _log_file_date(log_file: Path) -> date:
	"""Extract the date from a log file name (DD-MM-YYYY...), falling back to mtime."""
	match = re.match(r"^(\d{2})-(\d{2})-(\d{4})", log_file.stem)
	if match:
		day, month, year = match.groups()
		try:
			return date(int(year), int(month), int(day))
		except ValueError:
			pass
	return datetime.fromtimestamp(log_file.stat().st_mtime).date()


def _prune_expired_logs(log_dir: Path) -> None:
	"""Remove log files older than the retention period (date-only comparison)."""
	today = date.today()
	for log_file in log_dir.glob("*.json"):
		try:
			file_date = _log_file_date(log_file)
		except OSError:
			continue
		if (today - file_date).days > _RETENTION_DAYS:
			try:
				log_file.unlink()
			except OSError:
				pass


def init_logging(project_name: str, debug: bool = False, log_dir: Path | None = None) -> None:
	"""Initialize logging for the current run.

	Sets the project name, the debug flag and the log directory (default
	<project root>/logs, created if missing), prunes expired logs, and opens
	the current run's log file.
	"""
	global _project_name, _debug_enabled, _log_dir, _log_file, _events

	_project_name = project_name
	_debug_enabled = debug
	_log_dir = log_dir if log_dir is not None else _default_log_dir()
	_log_dir.mkdir(parents=True, exist_ok=True)
	_prune_expired_logs(_log_dir)
	_log_file = _log_dir / f"{datetime.now().strftime(_LOG_FILE_STEM_FORMAT)}.json"
	_events = []
	if _log_file.exists():
		try:
			with open(_log_file, "r", encoding="utf-8") as file:
				existing = json.load(file)
			if isinstance(existing, list):
				_events = existing
		except (OSError, json.JSONDecodeError):
			_events = []


def _write_log(log_type: str, title: str, data) -> None:
	"""Append one event to the current run's log file (thread-safe)."""
	if log_type == "DEBUG" and not _debug_enabled:
		return
	if _log_file is None:
		return

	timestamp = datetime.now().isoformat()
	event = {
		"timestamp": timestamp,
		"type": log_type,
		"title": title,
		"data": data,
		"hash": _compute_hash(timestamp, title, data),
	}
	with _lock:
		_events.append(event)
		try:
			with open(_log_file, "w", encoding="utf-8") as file:
				json.dump(_events, file, ensure_ascii=False, default=str, indent=2)
		except (OSError, TypeError):
			pass


def log_error(title: str, data=None) -> None:
	"""Log an ERROR event."""
	_write_log("ERROR", title, data)


def log_warn(title: str, data=None) -> None:
	"""Log a WARN event."""
	_write_log("WARN", title, data)


def log_info(title: str, data=None) -> None:
	"""Log an INFO event."""
	_write_log("INFO", title, data)


def log_debug(title: str, data=None) -> None:
	"""Log a DEBUG event (no-op unless debug mode is enabled)."""
	_write_log("DEBUG", title, data)
