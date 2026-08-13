"""CipherCLI terminal command."""

from __future__ import annotations

import argparse
import json
import logging
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib import error, request

from models import GetRequest, GetResponse, PostRequest, PostResponse

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "resources" / "configuration.json"
DEFAULT_CIPHER_PORT = 49158
DEFAULT_DISKIDENTIFIER_PORT = 49157
DEFAULT_SERVICEHANDLER_PORT = 49155
LOOPBACK_HOST = "127.0.0.1"


class CipherCliError(Exception):
	"""Raised when command input or processing is invalid."""


def _load_configuration() -> dict:
	"""Load configuration from resources/configuration.json."""
	if not CONFIG_PATH.exists():
		raise CipherCliError("Configuration file not found. Ensure resources/configuration.json exists.")

	try:
		with open(CONFIG_PATH, "r", encoding="utf-8-sig") as config_file:
			config = json.load(config_file)
		logger.info("Configuration loaded from %s", CONFIG_PATH)
	except json.JSONDecodeError as exc:
		logger.error("Configuration file contains invalid JSON: %s", exc)
		raise CipherCliError("Configuration file contains invalid JSON.") from exc
	except OSError as exc:
		logger.error("Failed to read configuration file: %s", exc)
		raise CipherCliError("Failed to read configuration file.") from exc

	if not isinstance(config, dict):
		logger.warning("Configuration root is not a JSON object")
		raise CipherCliError("Configuration file must contain a JSON object.")

	return config


def _parse_config_port(value: object, field_name: str, default_value: int) -> int:
	"""Parse an integer TCP port from configuration."""
	if value is None:
		return default_value

	if not isinstance(value, int):
		logger.warning("%s must be an integer, got %r", field_name, value)
		raise CipherCliError(f"{field_name} in configuration.json must be an integer.")

	if value < 1 or value > 65535:
		logger.warning("%s must be between 1 and 65535, got %r", field_name, value)
		raise CipherCliError(f"{field_name} in configuration.json must be between 1 and 65535.")

	return value


def _parse_config_bool(value: object, field_name: str, default_value: bool) -> bool:
	"""Parse a boolean from configuration."""
	if value is None:
		return default_value
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in ("true", "1", "yes")
	if isinstance(value, int):
		return value != 0
	logger.warning("Unsupported type %s for %s, using default %r", type(value).__name__, field_name, default_value)
	return default_value


def _test_port_open(host: str, port: int, timeout: float = 2.0) -> bool:
	"""Test if a TCP port is open on the given host."""
	try:
		with socket.create_connection((host, port), timeout=timeout):
			logger.debug("Port test %s:%d -> open", host, port)
			return True
	except (OSError, socket.timeout):
		logger.debug("Port test %s:%d -> closed", host, port)
		return False


def _resolve_service_port(service_name: str, config_port: int, servicehandler_port: int, servicehandler_enabled: bool) -> int:
	"""Resolve a service port: try the configured port first, then fall back to ServiceHandler if enabled."""
	if _test_port_open(LOOPBACK_HOST, config_port):
		logger.info("Using configured port %d for %s", config_port, service_name)
		return config_port

	logger.warning("Configured port %d for %s is unreachable", config_port, service_name)

	if servicehandler_enabled:
		logger.info("Querying ServiceHandler for %s port", service_name)
		try:
			response = _send_post_json(PostRequest(
				url=f"http://{LOOPBACK_HOST}:{servicehandler_port}/api/question/service",
				body=json.dumps({"name": service_name}).encode("utf-8"),
				timeout=5.0,
			))
			if response.status_code == 200 and isinstance(response.json_body, dict):
				port = response.json_body.get("port")
				if isinstance(port, int) and 1 <= port <= 65535:
					logger.info("Resolved %s port %d via ServiceHandler", service_name, port)
					return port
		except CipherCliError as exc:
			logger.warning("ServiceHandler resolution failed for %s: %s", service_name, exc)

	logger.debug("Falling back to configured port %d for %s", config_port, service_name)
	return config_port


def _looks_like_windows_raw_absolute(path_text: str) -> bool:
	"""Return True for Windows absolute paths like C:\\folder\\file or C:/folder/file."""
	return bool(re.match(r"^[a-zA-Z]:[\\/]", path_text.strip()))


def _looks_like_ultimate_path(path_text: str) -> bool:
	"""Return True for ultimate paths beginning with a 64-char disk hash."""
	trimmed = path_text.strip().replace("\\", "/")
	if not trimmed:
		return False

	disk_hash = trimmed.split("::", 1)[0]
	return bool(re.fullmatch(r"[0-9a-fA-F]{64}", disk_hash))


def _path_suffix_without_disk_hash(path_text: str) -> tuple[str, str]:
	"""Split ultimate path into (disk_hash, suffix)."""
	normalized = path_text.strip().replace("\\", "/")
	disk_hash, _, suffix = normalized.partition("::")
	return disk_hash, suffix


def _join_disk_root_and_suffix(disk_root: str, suffix: str) -> Path:
	"""Join disk root from DiskIdentifier with path suffix from an ultimate path."""
	normalized_root = disk_root.strip().replace("\\", "/")
	if not _looks_like_windows_raw_absolute(normalized_root):
		raise CipherCliError("DiskIdentifier returned an invalid disk root path.")

	root_path = Path(normalized_root)
	if not suffix:
		return root_path

	suffix_path = Path(*[part for part in suffix.split("/") if part])
	return root_path / suffix_path


def _send_post_json(http_request: PostRequest) -> PostResponse:
	"""Send a JSON POST request and normalize the response."""
	logger.debug("Sending POST request to %s", http_request.url)
	request_headers = {
		"Content-Type": "application/json",
		"Accept": "application/json",
		"Connection": "close",
		**http_request.headers,
	}

	urllib_request = request.Request(
		url=http_request.url,
		data=http_request.body,
		headers=request_headers,
		method="POST",
	)

	try:
		with request.urlopen(urllib_request, timeout=http_request.timeout) as response:
			response_body_bytes = response.read()
			response_body = response_body_bytes.decode("utf-8", errors="replace")
			parsed_json = _try_parse_json(response_body)
			logger.debug("POST response %d from %s", response.status, http_request.url)
			return PostResponse(
				status_code=response.status,
				body=response_body,
				json_body=parsed_json,
			)
	except error.HTTPError as exc:
		error_body_bytes = exc.read()
		error_body = error_body_bytes.decode("utf-8", errors="replace")
		logger.debug("POST HTTP error %d from %s", exc.code, http_request.url)
		return PostResponse(
			status_code=exc.code,
			body=error_body,
			json_body=_try_parse_json(error_body),
		)
	except error.URLError as exc:
		logger.warning("POST failed to contact service at %s: %s", http_request.url, exc.reason)
		raise CipherCliError(f"Failed to contact service at {http_request.url}: {exc.reason}") from exc


def _send_get_json(http_request: GetRequest, body: dict | None = None) -> GetResponse:
	"""Send a JSON GET request and normalize the response."""
	logger.debug("Sending GET request to %s", http_request.url)
	request_headers = {
		"Content-Type": "application/json",
		"Accept": "application/json",
		"Connection": "close",
		**http_request.headers,
	}
	body_bytes = json.dumps(body or {}).encode("utf-8")

	urllib_request = request.Request(
		url=http_request.url,
		data=body_bytes,
		headers=request_headers,
		method="GET",
	)

	try:
		with request.urlopen(urllib_request, timeout=http_request.timeout) as response:
			response_body_bytes = response.read()
			response_body = response_body_bytes.decode("utf-8", errors="replace")
			parsed_json = _try_parse_json(response_body)
			logger.debug("GET response %d from %s", response.status, http_request.url)
			return GetResponse(
				status_code=response.status,
				body=response_body,
				json_body=parsed_json,
			)
	except error.HTTPError as exc:
		error_body_bytes = exc.read()
		error_body = error_body_bytes.decode("utf-8", errors="replace")
		logger.debug("GET HTTP error %d from %s", exc.code, http_request.url)
		return GetResponse(
			status_code=exc.code,
			body=error_body,
			json_body=_try_parse_json(error_body),
		)
	except error.URLError as exc:
		logger.warning("GET failed to contact service at %s: %s", http_request.url, exc.reason)
		raise CipherCliError(f"Failed to contact service at {http_request.url}: {exc.reason}") from exc


def _try_parse_json(payload_text: str) -> dict | list | str | int | float | bool | None:
	"""Best-effort JSON parsing helper."""
	if not payload_text.strip():
		return None

	try:
		return json.loads(payload_text)
	except json.JSONDecodeError:
		logger.debug("Failed to parse JSON from payload")
		return None


def _resolve_ultimate_path_to_raw(path_text: str, diskidentifier_port: int) -> Path:
	"""Resolve an ultimate path to a raw absolute path by calling DiskIdentifier."""
	logger.debug("Resolving ultimate path: %s", path_text)
	disk_hash, suffix = _path_suffix_without_disk_hash(path_text)
	locate_request = GetRequest(
		url=f"http://{LOOPBACK_HOST}:{diskidentifier_port}/api/disk/locate",
		timeout=15.0,
	)
	locate_response = _send_get_json(locate_request, body={"disk_identifier": disk_hash})

	if locate_response.status_code != 200:
		message = "Failed to resolve disk hash through DiskIdentifier."
		if isinstance(locate_response.json_body, dict):
			error_text = locate_response.json_body.get("error")
			if isinstance(error_text, str) and error_text.strip():
				message = error_text.strip()
		raise CipherCliError(message)

	if not isinstance(locate_response.json_body, dict):
		raise CipherCliError("DiskIdentifier returned an invalid response payload.")

	disk_root = locate_response.json_body.get("path")
	if not isinstance(disk_root, str) or not disk_root.strip():
		raise CipherCliError("DiskIdentifier did not return a disk root path.")

	raw_path = _join_disk_root_and_suffix(disk_root, suffix)
	resolved = raw_path.resolve(strict=False)
	if not resolved.is_absolute():
		raise CipherCliError("Resolved path is not absolute.")
	logger.debug("Resolved ultimate path to: %s", resolved)
	return resolved


def _normalize_cli_path(path_text: str, diskidentifier_port: int) -> Path:
	"""Normalize a user path, accepting raw absolute paths and ultimate paths."""
	candidate = path_text.strip()
	if not candidate:
		raise CipherCliError("Path cannot be empty.")

	if _looks_like_ultimate_path(candidate):
		resolved = _resolve_ultimate_path_to_raw(candidate, diskidentifier_port)
		logger.debug("Normalized ultimate path %s to %s", path_text, resolved)
		return resolved

	path_value = Path(candidate)
	if not path_value.is_absolute():
		raise CipherCliError("Path must be absolute raw or absolute ultimate.")
	resolved = path_value.resolve(strict=False)
	logger.debug("Normalized path %s to %s", path_text, resolved)
	return resolved


def _validate_ck_arguments(path_argument: str, optional_file_name: str | None) -> tuple[Path, str]:
	"""Validate ck mode arguments and return directory + file name."""
	if optional_file_name is None:
		destination_path = Path(path_argument)
		if destination_path.exists() and destination_path.is_dir():
			logger.warning("ck validation failed: provided path is an existing directory")
			raise CipherCliError("The provided path points to a directory. A file path is required.")
		if destination_path.exists():
			logger.warning("ck validation failed: provided file already exists")
			raise CipherCliError("The provided file already exists.")
		if destination_path.parent == destination_path:
			logger.warning("ck validation failed: provided path has no file name component")
			raise CipherCliError("The provided path must include a file name.")
		if not destination_path.parent.exists() or not destination_path.parent.is_dir():
			logger.warning("ck validation failed: destination directory does not exist")
			raise CipherCliError("The destination directory does not exist.")
		file_name = destination_path.name
		if not file_name:
			logger.warning("ck validation failed: provided path has an empty file name")
			raise CipherCliError("The provided path must include a file name.")
		return destination_path.parent, file_name

	base_directory = Path(path_argument)
	if not base_directory.exists() or not base_directory.is_dir():
		logger.warning("ck validation failed: base directory does not exist")
		raise CipherCliError("When a file name is provided, path must reference an existing directory.")

	safe_name = Path(optional_file_name).name
	if safe_name != optional_file_name or optional_file_name in {".", ".."}:
		logger.warning("ck validation failed: file_name contains path components")
		raise CipherCliError("file_name must be a simple file name without path components.")

	destination_path = base_directory / safe_name
	if destination_path.exists() and destination_path.is_dir():
		logger.warning("ck validation failed: target points to a directory")
		raise CipherCliError("The target points to a directory.")
	if destination_path.exists():
		logger.warning("ck validation failed: target file already exists")
		raise CipherCliError("The target file already exists.")

	return base_directory, safe_name


def _run_ck_mode(args: argparse.Namespace, cipher_port: int, diskidentifier_port: int) -> int:
	"""Execute key creation mode: cipher ck."""
	normalized_path = _normalize_cli_path(args.path, diskidentifier_port)
	normalized_path_str = str(normalized_path)
	logger.info("Starting key-creation mode with resolved path %s", normalized_path_str)

	directory_path, file_name = _validate_ck_arguments(
		normalized_path_str,
		args.file_name,
	)

	logger.info("Creating key at %s", directory_path / file_name)

	payload = {
		"directory_path": str(directory_path),
		"file_name": file_name,
	}
	post_request = PostRequest(
		url=f"http://{LOOPBACK_HOST}:{cipher_port}/api/key",
		body=json.dumps(payload).encode("utf-8"),
		timeout=30.0,
	)

	response = _send_post_json(post_request)
	logger.info("Key creation request returned status %d", response.status_code)

	if response.status_code == 201:
		logger.info("Key created successfully at %s", directory_path / file_name)
		print(f"Key created: {directory_path / file_name}")
		return 0

	if isinstance(response.json_body, dict):
		error_message = response.json_body.get("error")
		if isinstance(error_message, str) and error_message.strip():
			_report_error(error_message.strip())
			return 1

	_report_error("Key creation failed.")
	return 1


def _run_health_mode(cipher_port: int) -> int:
	"""Execute health mode by querying the Cipher health endpoint."""
	logger.info("Querying Cipher health endpoint")
	get_request = GetRequest(
		url=f"http://{LOOPBACK_HOST}:{cipher_port}/api/health",
		timeout=15.0,
	)
	response = _send_get_json(get_request)
	logger.info("Health request returned status %d", response.status_code)

	if response.status_code != 200:
		error_message = _extract_error_message(response.json_body, "Failed to query service health.")
		_report_error(error_message)
		logger.info("Health mode exiting with code 1")
		return 1

	if response.json_body is not None:
		logger.debug("Health result: %s", response.body)
		print(json.dumps(response.json_body, indent=2, ensure_ascii=False))
	else:
		print(response.body)

	logger.info("Health mode exiting with code 0")
	return 0


def _extract_error_message(payload: object, fallback: str) -> str:
	"""Extract a user-facing error message from a JSON payload."""
	if isinstance(payload, dict):
		error_text = payload.get("error")
		if isinstance(error_text, str) and error_text.strip():
			return error_text.strip()
	return fallback


def _report_error(message: str, level: int = logging.ERROR) -> None:
	"""Log a message and print it to stderr so it is surfaced to the user."""
	logger.log(level, "%s", message)
	print(f"Error: {message}", file=sys.stderr)


def _parse_files_list(file_path: str) -> list[str]:
	"""Read a file containing a list of file paths. Items can be separated by newlines, commas, or semicolons."""
	try:
		content = Path(file_path).read_text(encoding="utf-8")
	except OSError as exc:
		raise CipherCliError(f"Failed to read files list: {exc}") from exc

	paths: list[str] = []
	for line in content.splitlines():
		for item in re.split(r"[,;]", line):
			stripped = item.strip()
			if stripped:
				paths.append(stripped)

	if not paths:
		raise CipherCliError("Files list is empty.")

	logger.debug("Loaded %d path(s) from files list", len(paths))
	return paths


def _normalize_existing_file_path(path_text: str, diskidentifier_port: int, field_name: str) -> Path:
	"""Normalize a path and ensure it points to an existing file."""
	normalized = _normalize_cli_path(path_text, diskidentifier_port)
	if not normalized.exists():
		raise CipherCliError(f"{field_name} does not exist: {normalized}")
	if not normalized.is_file():
		raise CipherCliError(f"{field_name} must reference a file: {normalized}")
	logger.debug("Normalized %s to %s", field_name, normalized)
	return normalized


def _poll_task_until_done(task_id: str, cipher_port: int, operation: str) -> int:
	"""Poll task status until it reaches a terminal state."""
	max_wait_seconds = 300
	poll_interval_seconds = 1.0
	deadline = time.time() + max_wait_seconds
	task_url = f"http://{LOOPBACK_HOST}:{cipher_port}/api/task/{task_id}"

	last_status: str | None = None
	attempt = 0
	while True:
		attempt += 1
		logger.debug("Polling task %s (attempt %d)", task_id, attempt)

		if time.time() > deadline:
			_report_error(
				f"Task timed out after {max_wait_seconds} seconds. Use task id {task_id} to check status later."
			)
			return 1

		response = _send_get_json(GetRequest(url=task_url, timeout=15.0))
		if response.status_code != 200:
			error_message = _extract_error_message(response.json_body, "Failed to query task status.")
			_report_error(error_message)
			return 1

		if not isinstance(response.json_body, dict):
			_report_error("Task endpoint returned an invalid payload.")
			return 1

		status = response.json_body.get("status")
		if not isinstance(status, str) or not status.strip():
			_report_error("Task status is missing in server response.")
			return 1

		status = status.strip()
		if status != last_status:
			logger.info("Task %s status: %s", task_id, status)
			print(f"Task {task_id}: {status}")
			last_status = status

		if status == "completed":
			logger.debug("Task %s reached terminal state: %s", task_id, status)
			result = response.json_body.get("result")
			if isinstance(result, dict):
				files = result.get("files")
				if isinstance(files, list) and files:
					for file_entry in files:
						if not isinstance(file_entry, dict):
							continue
						input_path = file_entry.get("input_path")
						output_path = file_entry.get("output_path")
						if isinstance(input_path, str) and isinstance(output_path, str):
							logger.debug("Task file mapping: %s -> %s", input_path, output_path)
							print(f"{input_path} -> {output_path}")
			logger.info("%s task %s completed", operation.capitalize(), task_id)
			print(f"{operation.capitalize()} completed.")
			return 0

		if status == "failed":
			logger.debug("Task %s reached terminal state: %s", task_id, status)
			error_message = response.json_body.get("error")
			if isinstance(error_message, str) and error_message.strip():
				_report_error(error_message.strip())
			else:
				_report_error(f"{operation} task failed.")
			return 1

		time.sleep(poll_interval_seconds)


def _run_cipher_mode(
	args: argparse.Namespace,
	cipher_port: int,
	diskidentifier_port: int,
	operation: str,
	endpoint: str,
	file_name_flag_field: str,
	file_name_flag_value: bool,
) -> int:
	"""Execute encryption/decryption mode by queuing and polling a Cipher task."""
	logger.info("Starting %s mode targeting endpoint %s", operation, endpoint)
	key_path = _normalize_existing_file_path(args.key_path, diskidentifier_port, "key_path")
	file_paths = [
		_normalize_existing_file_path(file_path_text, diskidentifier_port, "file_path")
		for file_path_text in args.file_paths
	]
	# filename handling and output options
	overwrite = bool(getattr(args, "overwrite_file", False))
	output_file_path_arg = getattr(args, "output_file_path", None)
	output_file_paths_arg = getattr(args, "output_file_paths", None)
	output_dir_arg = getattr(args, "output_dir", None)

	file_name_flag_dash = file_name_flag_field.replace("_", "-")

	# --overwrite-file excludes --output-file-path, --output-file-paths, --output-dir
	if overwrite:
		if output_file_path_arg:
			logger.warning("Flag conflict: --overwrite-file cannot be combined with --output-file-path")
			raise CipherCliError("--overwrite-file cannot be combined with --output-file-path.")
		if output_file_paths_arg:
			logger.warning("Flag conflict: --overwrite-file cannot be combined with --output-file-paths")
			raise CipherCliError("--overwrite-file cannot be combined with --output-file-paths.")
		if output_dir_arg:
			logger.warning("Flag conflict: --overwrite-file cannot be combined with --output-dir")
			raise CipherCliError("--overwrite-file cannot be combined with --output-dir.")

	# --encrypt-file-name/--decrypt-file-name excludes --output-file-path, --output-file-paths
	if file_name_flag_value:
		if output_file_path_arg:
			logger.warning("Flag conflict: --%s cannot be combined with --output-file-path", file_name_flag_dash)
			raise CipherCliError(f"--{file_name_flag_dash} cannot be combined with --output-file-path.")
		if output_file_paths_arg:
			logger.warning("Flag conflict: --%s cannot be combined with --output-file-paths", file_name_flag_dash)
			raise CipherCliError(f"--{file_name_flag_dash} cannot be combined with --output-file-paths.")

	# --output-dir excludes --overwrite-file, --output-file-path, --output-file-paths
	if output_dir_arg:
		if overwrite:
			logger.warning("Flag conflict: --output-dir cannot be combined with --overwrite-file")
			raise CipherCliError("--output-dir cannot be combined with --overwrite-file.")
		if output_file_path_arg:
			logger.warning("Flag conflict: --output-dir cannot be combined with --output-file-path")
			raise CipherCliError("--output-dir cannot be combined with --output-file-path.")
		if output_file_paths_arg:
			logger.warning("Flag conflict: --output-dir cannot be combined with --output-file-paths")
			raise CipherCliError("--output-dir cannot be combined with --output-file-paths.")

	# Validate output path requirements according to Cipher API rules
	if not file_name_flag_value and not overwrite:
		if not output_file_path_arg and not output_file_paths_arg and not output_dir_arg:
			logger.warning("No output path specified for %s mode", operation)
			raise CipherCliError(
				"When filename transformation is disabled and overwrite is false, you must provide output paths via --output-file-path, --output-file-paths, or --output-dir."
			)

	normalized_output_paths: list[str] | None = None
	output_dir_normalized: Path | None = None
	if output_dir_arg:
		output_dir_normalized = _normalize_cli_path(output_dir_arg, diskidentifier_port)
		if not file_name_flag_value:
			normalized_output_paths = [str(output_dir_normalized / path.name) for path in file_paths]
	elif output_file_paths_arg:
		if len(output_file_paths_arg) != len(file_paths):
			logger.warning("--output-file-paths count %d does not match input count %d", len(output_file_paths_arg), len(file_paths))
			raise CipherCliError("The number of --output-file-paths must match the number of input files.")
		normalized_output_paths = [str(_normalize_cli_path(p, diskidentifier_port)) for p in output_file_paths_arg]
	elif output_file_path_arg:
		if len(file_paths) != 1:
			logger.warning("--output-file-path provided with %d input files", len(file_paths))
			raise CipherCliError("--output-file-path may only be used when a single input file is provided.")
		normalized_output_paths = [str(_normalize_cli_path(output_file_path_arg, diskidentifier_port))]

	payload = {
		"key_path": str(key_path),
		"file_paths": [str(path) for path in file_paths],
		file_name_flag_field: file_name_flag_value,
		"overwrite_file": overwrite,
	}

	if output_dir_normalized is not None and file_name_flag_value:
		payload["output_dir"] = str(output_dir_normalized)

	if normalized_output_paths is not None:
		if len(normalized_output_paths) == 1:
			payload["output_file_path"] = normalized_output_paths[0]
		else:
			payload["output_file_paths"] = normalized_output_paths

	logger.info("Queuing %s task for %d file(s)", operation, len(file_paths))

	post_request = PostRequest(
		url=f"http://{LOOPBACK_HOST}:{cipher_port}{endpoint}",
		body=json.dumps(payload).encode("utf-8"),
		timeout=30.0,
	)

	response = _send_post_json(post_request)
	logger.info("%s request returned status %d", operation, response.status_code)
	if response.status_code != 202:
		error_message = _extract_error_message(response.json_body, f"Failed to queue {operation} task.")
		_report_error(error_message)
		return 1

	if not isinstance(response.json_body, dict):
		_report_error("Cipher service returned an invalid task payload.")
		return 1

	task_id = response.json_body.get("task_id")
	if not isinstance(task_id, str) or not task_id.strip():
		_report_error("Cipher service did not return a task id.")
		return 1

	task_id = task_id.strip()
	logger.info("Task %s queued successfully for %s", task_id, operation)
	print(f"Task queued: {task_id}")
	return _poll_task_until_done(task_id, cipher_port, operation)


def _build_parser() -> argparse.ArgumentParser:
	"""Build the CLI parser."""
	parser = argparse.ArgumentParser(
		prog="cip",
		description="Cip command-line client.",
	)

	subparsers = parser.add_subparsers(dest="mode")

	parser_c = subparsers.add_parser("c", help="Cipher files.")
	parser_c.description = "Encrypt files. See mutually exclusive flag rules below."
	parser_c.add_argument("key_path", nargs="?", help="Absolute key file path (raw or ultimate path).")
	parser_c.add_argument(
		"file_paths",
		nargs="*",
		help="One or more absolute file paths to encrypt (raw or ultimate paths).",
	)
	parser_c.add_argument(
		"--encrypt-file-name",
		action="store_true",
		help="Encrypt output file names as well. Cannot be combined with --output-file-path or --output-file-paths.",
	)
	parser_c.add_argument(
		"--overwrite-file",
		action="store_true",
		help="Write encrypted output into the source file (in-place). Cannot be combined with --output-file-path, --output-file-paths or --output-dir.",
	)
	parser_c.add_argument(
		"--output-file-path",
		help="Single absolute output file path when one input file is provided. Cannot be combined with --encrypt-file-name, --overwrite-file or --output-dir.",
	)
	parser_c.add_argument(
		"--output-file-paths",
		nargs="+",
		help="One output path per input file (must match number of input files). Cannot be combined with --encrypt-file-name, --overwrite-file or --output-dir.",
	)
	parser_c.add_argument(
		"--output-dir",
		help="Output directory; generates output paths inside it using input file names. Cannot be combined with --overwrite-file, --output-file-path or --output-file-paths.",
	)
	parser_c.add_argument(
		"--files-list",
		help="Path to a text file listing absolute file paths to encrypt. Items can be separated by newlines, commas, or semicolons. Cannot be combined with positional file paths.",
	)

	parser_d = subparsers.add_parser("d", help="Decipher files.")
	parser_d.description = "Decrypt files. See mutually exclusive flag rules below."
	parser_d.add_argument("key_path", nargs="?", help="Absolute key file path (raw or ultimate path).")
	parser_d.add_argument(
		"file_paths",
		nargs="*",
		help="One or more absolute file paths to decrypt (raw or ultimate paths).",
	)
	parser_d.add_argument(
		"--decrypt-file-name",
		action="store_true",
		help="Decrypt output file names as well. Cannot be combined with --output-file-path or --output-file-paths.",
	)
	parser_d.add_argument(
		"--overwrite-file",
		action="store_true",
		help="Write decrypted output into the source file (in-place). Cannot be combined with --output-file-path, --output-file-paths or --output-dir.",
	)
	parser_d.add_argument(
		"--output-file-path",
		help="Single absolute output file path when one input file is provided. Cannot be combined with --decrypt-file-name, --overwrite-file or --output-dir.",
	)
	parser_d.add_argument(
		"--output-file-paths",
		nargs="+",
		help="One output path per input file (must match number of input files). Cannot be combined with --decrypt-file-name, --overwrite-file or --output-dir.",
	)
	parser_d.add_argument(
		"--output-dir",
		help="Output directory; generates output paths inside it using input file names. Cannot be combined with --overwrite-file, --output-file-path or --output-file-paths.",
	)
	parser_d.add_argument(
		"--files-list",
		help="Path to a text file listing absolute file paths to decrypt. Items can be separated by newlines, commas, or semicolons. Cannot be combined with positional file paths.",
	)

	parser_ck = subparsers.add_parser("ck", help="Create a key.")
	parser_ck.add_argument("path", help="Destination file path, or destination directory path.")
	parser_ck.add_argument(
		"file_name",
		nargs="?",
		default=None,
		help="Optional key file name when path points to a directory.",
	)

	parser_health = subparsers.add_parser("health", help="Show service health.")
	parser_health.description = "Show service health."

	parser.add_argument(
		"-v", "--verbose",
		action="store_true",
		help="Enable verbose logging output.",
	)

	return parser


def main() -> int:
	"""Program entry point."""
	parser = _build_parser()

	try:
		config = _load_configuration()
		config_cipher_port = _parse_config_port(config.get("cipherPort"), "cipherPort", DEFAULT_CIPHER_PORT)
		config_diskidentifier_port = _parse_config_port(
			config.get("diskidentifierPort"),
			"diskidentifierPort",
			DEFAULT_DISKIDENTIFIER_PORT,
		)
		servicehandler_enabled = _parse_config_bool(config.get("servicehandlerEnabled"), "servicehandlerEnabled", False)
		servicehandler_port = _parse_config_port(
			config.get("servicehandlerPort"),
			"servicehandlerPort",
			DEFAULT_SERVICEHANDLER_PORT,
		)

		cipher_port = _resolve_service_port("Cipher", config_cipher_port, servicehandler_port, servicehandler_enabled)
		diskidentifier_port = _resolve_service_port("DiskIdentifier", config_diskidentifier_port, servicehandler_port, servicehandler_enabled)
		logger.info("Resolved ports: cipher=%d, diskidentifier=%d", cipher_port, diskidentifier_port)
	except CipherCliError as exc:
		_report_error(str(exc), level=logging.WARNING)
		logger.info("Exiting with code 1")
		return 1

	if len(sys.argv) == 1:
		logger.debug("No arguments provided, printing help")
		_report_error("a mode is required.", level=logging.WARNING)
		parser.print_help()
		logger.info("Exiting with code 1")
		return 1

	args = parser.parse_args()

	if args.mode == "ck":
		logger.info("Dispatching to ck mode")
		try:
			ck_result = _run_ck_mode(args, cipher_port, diskidentifier_port)
			logger.info("Exiting with code %d", ck_result)
			return ck_result
		except CipherCliError as exc:
			_report_error(str(exc), level=logging.WARNING)
			logger.info("Exiting with code 1")
			return 1

	if args.mode == "c":
		logger.info("Dispatching to c mode")
		try:
			if args.key_path is None:
				logger.warning("Encrypt mode validation failed: key_path is missing")
				raise CipherCliError("Both key_path and at least one file_path are required.")
			if args.files_list:
				if args.file_paths:
					logger.warning("Encrypt mode validation failed: --files-list combined with positional file paths")
					raise CipherCliError("--files-list cannot be combined with positional file paths.")
				args.file_paths = _parse_files_list(args.files_list)
			elif not args.file_paths:
				logger.warning("Encrypt mode validation failed: no file paths provided")
				raise CipherCliError("Both key_path and at least one file_path are required.")
			cipher_result = _run_cipher_mode(
				args,
				cipher_port,
				diskidentifier_port,
				"encrypt",
				"/api/encrypt",
				"encrypt_file_name",
				bool(args.encrypt_file_name),
			)
			logger.info("Exiting with code %d", cipher_result)
			return cipher_result
		except CipherCliError as exc:
			_report_error(str(exc), level=logging.WARNING)
			logger.info("Exiting with code 1")
			return 1

	if args.mode == "d":
		logger.info("Dispatching to d mode")
		try:
			if args.key_path is None:
				logger.warning("Decrypt mode validation failed: key_path is missing")
				raise CipherCliError("Both key_path and at least one file_path are required.")
			if args.files_list:
				if args.file_paths:
					logger.warning("Decrypt mode validation failed: --files-list combined with positional file paths")
					raise CipherCliError("--files-list cannot be combined with positional file paths.")
				args.file_paths = _parse_files_list(args.files_list)
			elif not args.file_paths:
				logger.warning("Decrypt mode validation failed: no file paths provided")
				raise CipherCliError("Both key_path and at least one file_path are required.")
			cipher_result = _run_cipher_mode(
				args,
				cipher_port,
				diskidentifier_port,
				"decrypt",
				"/api/decrypt",
				"decrypt_file_name",
				bool(args.decrypt_file_name),
			)
			logger.info("Exiting with code %d", cipher_result)
			return cipher_result
		except CipherCliError as exc:
			_report_error(str(exc), level=logging.WARNING)
			logger.info("Exiting with code 1")
			return 1

	if args.mode == "health":
		logger.info("Dispatching to health mode")
		try:
			health_result = _run_health_mode(cipher_port)
			logger.info("Exiting with code %d", health_result)
			return health_result
		except CipherCliError as exc:
			_report_error(str(exc), level=logging.WARNING)
			logger.info("Exiting with code 1")
			return 1

	logger.debug("Unknown mode %r, printing help", args.mode)
	parser.print_help()
	logger.info("Exiting with code 1")
	return 1


if __name__ == "__main__":
	parser = _build_parser()
	early_args, _ = parser.parse_known_args()

	log_dir = Path(__file__).resolve().parent.parent / "logs"
	log_dir.mkdir(exist_ok=True)
	log_file = log_dir / f"{datetime.now().strftime('%d-%m-%Y_%H.%M.%S')}.log"
	logging.basicConfig(
		level=logging.DEBUG if early_args.verbose else logging.INFO,
		format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
		handlers=[
			logging.StreamHandler(),
			logging.FileHandler(log_file, encoding="utf-8"),
		],
	)
	logger.info("CipherCLI invoked: %s", " ".join(sys.argv))
	logger.debug("Log file: %s", log_file)

	sys.exit(main())
