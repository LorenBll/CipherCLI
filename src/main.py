"""CipherCLI terminal command."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from urllib import error, request

from models import GetRequest, GetResponse, PostRequest, PostResponse

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "resources" / "configuration.json"
DEFAULT_CIPHER_PORT = 49158
DEFAULT_DISKIDENTIFIER_PORT = 49157
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
	except json.JSONDecodeError as exc:
		raise CipherCliError("Configuration file contains invalid JSON.") from exc
	except OSError as exc:
		raise CipherCliError("Failed to read configuration file.") from exc

	if not isinstance(config, dict):
		raise CipherCliError("Configuration file must contain a JSON object.")

	return config


def _parse_config_port(value: object, field_name: str, default_value: int) -> int:
	"""Parse an integer TCP port from configuration."""
	if value is None:
		return default_value

	parsed_value = value
	if isinstance(parsed_value, str):
		parsed_value = parsed_value.strip()
		if parsed_value.isdigit():
			parsed_value = int(parsed_value)

	if not isinstance(parsed_value, int):
		raise CipherCliError(f"{field_name} in configuration.json must be an integer.")

	if parsed_value < 1 or parsed_value > 65535:
		raise CipherCliError(f"{field_name} in configuration.json must be between 1 and 65535.")

	return parsed_value


def _resolve_project_path(path_text: str, base_directory: Path) -> Path:
	"""Resolve a path from configuration relative to the project root."""
	candidate = Path(path_text.strip())
	if candidate.is_absolute():
		return candidate
	return (base_directory / candidate).resolve(strict=False)


def _looks_like_windows_raw_absolute(path_text: str) -> bool:
	"""Return True for Windows absolute paths like C:\\folder\\file or C:/folder/file."""
	return bool(re.match(r"^[a-zA-Z]:[\\/]", path_text.strip()))


def _looks_like_ultimate_path(path_text: str) -> bool:
	"""Return True for ultimate paths beginning with a 64-char disk hash."""
	trimmed = path_text.strip().replace("\\", "/")
	if not trimmed:
		return False

	disk_hash = trimmed.split("/", 1)[0]
	return bool(re.fullmatch(r"[0-9a-fA-F]{64}", disk_hash))


def _path_suffix_without_disk_hash(path_text: str) -> tuple[str, str]:
	"""Split ultimate path into (disk_hash, suffix)."""
	normalized = path_text.strip().replace("\\", "/")
	disk_hash, _, suffix = normalized.partition("/")
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
	request_headers = {
		"Content-Type": "application/json",
		"Accept": "application/json",
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
			response_headers = dict(response.headers.items())
			parsed_json = _try_parse_json(response_body)
			return PostResponse(
				status_code=response.status,
				reason=getattr(response, "reason", ""),
				body=response_body,
				body_size=len(response_body_bytes),
				headers=response_headers,
				json_body=parsed_json,
			)
	except error.HTTPError as exc:
		error_body_bytes = exc.read()
		error_body = error_body_bytes.decode("utf-8", errors="replace")
		response_headers = dict(exc.headers.items()) if exc.headers else {}
		return PostResponse(
			status_code=exc.code,
			reason=exc.reason if isinstance(exc.reason, str) else "",
			body=error_body,
			body_size=len(error_body_bytes),
			headers=response_headers,
			json_body=_try_parse_json(error_body),
		)
	except error.URLError as exc:
		raise CipherCliError(f"Failed to contact service at {http_request.url}: {exc.reason}") from exc


def _send_get_json(http_request: GetRequest, body: dict | None = None) -> GetResponse:
	"""Send a JSON GET request and normalize the response."""
	request_headers = {
		"Content-Type": "application/json",
		"Accept": "application/json",
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
			response_headers = dict(response.headers.items())
			parsed_json = _try_parse_json(response_body)
			return GetResponse(
				status_code=response.status,
				reason=getattr(response, "reason", ""),
				body=response_body,
				body_size=len(response_body_bytes),
				headers=response_headers,
				json_body=parsed_json,
			)
	except error.HTTPError as exc:
		error_body_bytes = exc.read()
		error_body = error_body_bytes.decode("utf-8", errors="replace")
		response_headers = dict(exc.headers.items()) if exc.headers else {}
		return GetResponse(
			status_code=exc.code,
			reason=exc.reason if isinstance(exc.reason, str) else "",
			body=error_body,
			body_size=len(error_body_bytes),
			headers=response_headers,
			json_body=_try_parse_json(error_body),
		)
	except error.URLError as exc:
		raise CipherCliError(f"Failed to contact service at {http_request.url}: {exc.reason}") from exc


def _try_parse_json(payload_text: str) -> dict | list | str | int | float | bool | None:
	"""Best-effort JSON parsing helper."""
	if not payload_text.strip():
		return None

	try:
		return json.loads(payload_text)
	except json.JSONDecodeError:
		return None


def _resolve_ultimate_path_to_raw(path_text: str, diskidentifier_port: int) -> Path:
	"""Resolve an ultimate path to a raw absolute path by calling DiskIdentifier."""
	disk_hash, suffix = _path_suffix_without_disk_hash(path_text)
	locate_request = GetRequest(
		url=f"http://{LOOPBACK_HOST}:{diskidentifier_port}/api/locate",
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
	return resolved


def _normalize_cli_path(path_text: str, diskidentifier_port: int) -> Path:
	"""Normalize a user path, accepting raw absolute paths and ultimate paths."""
	candidate = path_text.strip()
	if not candidate:
		raise CipherCliError("Path cannot be empty.")

	if _looks_like_ultimate_path(candidate):
		return _resolve_ultimate_path_to_raw(candidate, diskidentifier_port)

	path_value = Path(candidate)
	if not path_value.is_absolute():
		raise CipherCliError("Path must be absolute raw or absolute ultimate.")
	resolved = path_value.resolve(strict=False)
	return resolved


def _validate_ck_arguments(path_argument: str, optional_file_name: str | None) -> tuple[Path, str]:
	"""Validate ck mode arguments and return directory + file name."""
	if optional_file_name is None:
		destination_path = Path(path_argument)
		if destination_path.exists() and destination_path.is_dir():
			raise CipherCliError("The provided path points to a directory. A file path is required.")
		if destination_path.exists():
			raise CipherCliError("The provided file already exists.")
		if destination_path.parent == destination_path:
			raise CipherCliError("The provided path must include a file name.")
		if not destination_path.parent.exists() or not destination_path.parent.is_dir():
			raise CipherCliError("The destination directory does not exist.")
		file_name = destination_path.name
		if not file_name:
			raise CipherCliError("The provided path must include a file name.")
		return destination_path.parent, file_name

	base_directory = Path(path_argument)
	if not base_directory.exists() or not base_directory.is_dir():
		raise CipherCliError("When a file name is provided, path must reference an existing directory.")

	safe_name = Path(optional_file_name).name
	if safe_name != optional_file_name or optional_file_name in {".", ".."}:
		raise CipherCliError("file_name must be a simple file name without path components.")

	destination_path = base_directory / safe_name
	if destination_path.exists() and destination_path.is_dir():
		raise CipherCliError("The target points to a directory.")
	if destination_path.exists():
		raise CipherCliError("The target file already exists.")

	return base_directory, safe_name


def _run_ck_mode(args: argparse.Namespace, cipher_port: int, diskidentifier_port: int) -> int:
	"""Execute key creation mode: cipher ck."""
	normalized_path = _normalize_cli_path(args.path, diskidentifier_port)
	normalized_path_str = str(normalized_path)

	directory_path, file_name = _validate_ck_arguments(
		normalized_path_str,
		args.file_name,
	)

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

	if response.status_code == 201:
		print(f"Key created: {directory_path / file_name}")
		return 0

	if isinstance(response.json_body, dict):
		error_message = response.json_body.get("error")
		if isinstance(error_message, str) and error_message.strip():
			print(f"Error: {error_message.strip()}", file=sys.stderr)
			return 1

	print("Error: Key creation failed.", file=sys.stderr)
	return 1


def _run_health_mode(cipher_port: int) -> int:
	"""Execute health mode by querying the Cipher health endpoint."""
	get_request = GetRequest(
		url=f"http://{LOOPBACK_HOST}:{cipher_port}/api/health",
		timeout=15.0,
	)
	response = _send_get_json(get_request)

	if response.status_code != 200:
		error_message = _extract_error_message(response.json_body, "Failed to query service health.")
		print(f"Error: {error_message}", file=sys.stderr)
		return 1

	if response.json_body is not None:
		print(json.dumps(response.json_body, indent=2, ensure_ascii=False))
	else:
		print(response.body)

	return 0


def _extract_error_message(payload: object, fallback: str) -> str:
	"""Extract a user-facing error message from a JSON payload."""
	if isinstance(payload, dict):
		error_text = payload.get("error")
		if isinstance(error_text, str) and error_text.strip():
			return error_text.strip()
	return fallback


def _normalize_existing_file_path(path_text: str, diskidentifier_port: int, field_name: str) -> Path:
	"""Normalize a path and ensure it points to an existing file."""
	normalized = _normalize_cli_path(path_text, diskidentifier_port)
	if not normalized.exists():
		raise CipherCliError(f"{field_name} does not exist: {normalized}")
	if not normalized.is_file():
		raise CipherCliError(f"{field_name} must reference a file: {normalized}")
	return normalized


def _poll_task_until_done(task_id: str, cipher_port: int, operation: str) -> int:
	"""Poll task status until it reaches a terminal state."""
	max_wait_seconds = 300
	poll_interval_seconds = 1.0
	deadline = time.time() + max_wait_seconds
	task_url = f"http://{LOOPBACK_HOST}:{cipher_port}/api/task/{task_id}"

	last_status: str | None = None
	while True:
		if time.time() > deadline:
			print(
				f"Error: Task timed out after {max_wait_seconds} seconds. Use task id {task_id} to check status later.",
				file=sys.stderr,
			)
			return 1

		response = _send_get_json(GetRequest(url=task_url, timeout=15.0))
		if response.status_code != 200:
			error_message = _extract_error_message(response.json_body, "Failed to query task status.")
			print(f"Error: {error_message}", file=sys.stderr)
			return 1

		if not isinstance(response.json_body, dict):
			print("Error: Task endpoint returned an invalid payload.", file=sys.stderr)
			return 1

		status = response.json_body.get("status")
		if not isinstance(status, str) or not status.strip():
			print("Error: Task status is missing in server response.", file=sys.stderr)
			return 1

		status = status.strip()
		if status != last_status:
			print(f"Task {task_id}: {status}")
			last_status = status

		if status == "completed":
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
							print(f"{input_path} -> {output_path}")
			print(f"{operation.capitalize()} completed.")
			return 0

		if status == "failed":
			error_message = response.json_body.get("error")
			if isinstance(error_message, str) and error_message.strip():
				print(f"Error: {error_message.strip()}", file=sys.stderr)
			else:
				print(f"Error: {operation} task failed.", file=sys.stderr)
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
			raise CipherCliError("--overwrite-file cannot be combined with --output-file-path.")
		if output_file_paths_arg:
			raise CipherCliError("--overwrite-file cannot be combined with --output-file-paths.")
		if output_dir_arg:
			raise CipherCliError("--overwrite-file cannot be combined with --output-dir.")

	# --encrypt-file-name/--decrypt-file-name excludes --output-file-path, --output-file-paths
	if file_name_flag_value:
		if output_file_path_arg:
			raise CipherCliError(f"--{file_name_flag_dash} cannot be combined with --output-file-path.")
		if output_file_paths_arg:
			raise CipherCliError(f"--{file_name_flag_dash} cannot be combined with --output-file-paths.")

	# --output-dir excludes --overwrite-file, --output-file-path, --output-file-paths
	if output_dir_arg:
		if overwrite:
			raise CipherCliError("--output-dir cannot be combined with --overwrite-file.")
		if output_file_path_arg:
			raise CipherCliError("--output-dir cannot be combined with --output-file-path.")
		if output_file_paths_arg:
			raise CipherCliError("--output-dir cannot be combined with --output-file-paths.")

	# Validate output path requirements according to Cipher API rules
	if not file_name_flag_value and not overwrite:
		if not output_file_path_arg and not output_file_paths_arg and not output_dir_arg:
			raise CipherCliError(
				"When filename transformation is disabled and overwrite is false, you must provide output paths via --output-file-path, --output-file-paths, or --output-dir."
			)

	normalized_output_paths: list[str] | None = None
	if output_dir_arg:
		output_dir = _normalize_cli_path(output_dir_arg, diskidentifier_port)
		normalized_output_paths = [str(output_dir / path.name) for path in file_paths]
	elif output_file_paths_arg:
		if len(output_file_paths_arg) != len(file_paths):
			raise CipherCliError("The number of --output-file-paths must match the number of input files.")
		normalized_output_paths = [str(_normalize_cli_path(p, diskidentifier_port)) for p in output_file_paths_arg]
	elif output_file_path_arg:
		if len(file_paths) != 1:
			raise CipherCliError("--output-file-path may only be used when a single input file is provided.")
		normalized_output_paths = [str(_normalize_cli_path(output_file_path_arg, diskidentifier_port))]

	payload = {
		"key_path": str(key_path),
		"file_paths": [str(path) for path in file_paths],
		file_name_flag_field: file_name_flag_value,
		"overwrite_file": overwrite,
	}

	if normalized_output_paths is not None:
		if len(normalized_output_paths) == 1:
			payload["output_file_path"] = normalized_output_paths[0]
		else:
			payload["output_file_paths"] = normalized_output_paths
	post_request = PostRequest(
		url=f"http://{LOOPBACK_HOST}:{cipher_port}{endpoint}",
		body=json.dumps(payload).encode("utf-8"),
		timeout=30.0,
	)

	response = _send_post_json(post_request)
	if response.status_code != 202:
		error_message = _extract_error_message(response.json_body, f"Failed to queue {operation} task.")
		print(f"Error: {error_message}", file=sys.stderr)
		return 1

	if not isinstance(response.json_body, dict):
		print("Error: Cipher service returned an invalid task payload.", file=sys.stderr)
		return 1

	task_id = response.json_body.get("task_id")
	if not isinstance(task_id, str) or not task_id.strip():
		print("Error: Cipher service did not return a task id.", file=sys.stderr)
		return 1

	task_id = task_id.strip()
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

	return parser


def main() -> int:
	"""Program entry point."""
	logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

	try:
		config = _load_configuration()
		cipher_port = _parse_config_port(config.get("cipherPort"), "cipherPort", DEFAULT_CIPHER_PORT)
		diskidentifier_port = _parse_config_port(
			config.get("diskidentifierPort"),
			"diskidentifierPort",
			DEFAULT_DISKIDENTIFIER_PORT,
		)
	except CipherCliError as exc:
		print(f"Error: {exc}", file=sys.stderr)
		return 1

	parser = _build_parser()
	if len(sys.argv) == 1:
		print("Error: a mode is required.", file=sys.stderr)
		parser.print_help()
		return 1

	args = parser.parse_args()

	if args.mode == "ck":
		try:
			return _run_ck_mode(args, cipher_port, diskidentifier_port)
		except CipherCliError as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 1

	if args.mode == "c":
		try:
			if args.key_path is None or not args.file_paths:
				raise CipherCliError("Both key_path and at least one file_path are required.")
			return _run_cipher_mode(
				args,
				cipher_port,
				diskidentifier_port,
				"encrypt",
				"/api/encrypt",
				"encrypt_file_name",
				bool(args.encrypt_file_name),
			)
		except CipherCliError as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 1

	if args.mode == "d":
		try:
			if args.key_path is None or not args.file_paths:
				raise CipherCliError("Both key_path and at least one file_path are required.")
			return _run_cipher_mode(
				args,
				cipher_port,
				diskidentifier_port,
				"decrypt",
				"/api/decrypt",
				"decrypt_file_name",
				bool(args.decrypt_file_name),
			)
		except CipherCliError as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 1

	if args.mode == "health":
		try:
			return _run_health_mode(cipher_port)
		except CipherCliError as exc:
			print(f"Error: {exc}", file=sys.stderr)
			return 1

	parser.print_help()
	return 1


if __name__ == "__main__":
	sys.exit(main())
