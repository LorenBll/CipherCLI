# CipherCLI

CipherCLI is a local command-line client for the Cipher encryption service. It can create keys, encrypt or decrypt files through the loopback HTTP API, and query the service health endpoint with `cip health`.

## About

CipherCLI is designed to run on the same machine as [Cipher](https://www.github.com/LorenBll/Cipher). It talks to `127.0.0.1` for both the Cipher API and the [DiskIdentifier](https://www.github.com/LorenBll/DiskIdentifier) service used to resolve ultimate paths. The ports are resolved from `resources/configuration.json` and optionally through [ServiceHandler](https://www.github.com/LorenBll/ServiceHandler).

CipherCLI is a client for the web-service Cipher (https://www.github.com/LorenBll/Cipher).

**Features:**

- **Key creation** — generate encryption keys through the Cipher API.
- **File encryption** — encrypt one or more files with support for batch operations via `--files-list`.
- **File decryption** — decrypt one or more files with the same batch and output options.
- **Ultimate path resolution** — use DiskIdentifier to resolve disk hashes to raw absolute paths.
- **ServiceHandler fallback** — when enabled, falls back to ServiceHandler for port discovery if the configured port is unreachable.
- **Polling task tracking** — after queuing an encrypt or decrypt job, polls the task endpoint until completion or failure.
- **Dependency-free** — uses only the Python standard library; no external packages required.

## Setup

1. CipherCLI has no external Python dependencies — it uses only the standard library. If you also run the Cipher service locally, install its dependencies with `pip install -r requirements.txt`.
2. Optionally run `scripts\setup.bat` (Windows) or `bash scripts/setup.sh` (Unix) to create a virtual environment and install dependencies.
3. Make sure the Cipher service is running locally before using `c`, `d`, or `health`.
4. DiskIdentifier is optional — CipherCLI works without it. If you want to use ultimate paths, run DiskIdentifier locally so CipherCLI can resolve them via the configured `diskidentifierPort`.
5. ServiceHandler is optional — when `servicehandlerEnabled` is `true`, CipherCLI first tries the configured ports and falls back to querying ServiceHandler if the service is unreachable on the configured port.
6. Keep the project structure intact so the CLI can find `resources/` and `src/`.

## Run

1. Windows: run `scripts\cip.bat`.
2. Unix-like systems: run `bash scripts/cip.sh`.
3. Manual: run `python src/main.py` from the project root.

## Usage

All commands accept the `-v` or `--verbose` flag to enable detailed logging output for debugging.

### `cip ck <path> [file_name]`

Create a new key file through `POST /api/key`.

- `path` can be either:
  - an absolute file path for the new key, or
  - an absolute directory path when `file_name` is provided.
- `file_name` must be a simple file name with no path components.

Example:

```bash
cip ck C:\Cipher\keys mykey.key
```

### `cip c <key_path> <file_path...> [--encrypt-file-name] [--overwrite-file] [--output-file-path|--output-file-paths|--output-dir] [--files-list <path>]`

Encrypt one or more files through `POST /api/encrypt`.

- `key_path` must reference an existing key file.
- `file_path` accepts one or more absolute file paths. Cannot be combined with `--files-list`.
- `--files-list` path to a text file listing absolute file paths to encrypt. Items can be separated by newlines, commas, or semicolons. Cannot be combined with positional `file_path` arguments.
- `--encrypt-file-name` encrypts output file names. Applies to all input files. Cannot be combined with `--output-file-path` or `--output-file-paths`.
- `--overwrite-file` writes encrypted content into the source file (in-place). Applies to all input files. Cannot be combined with `--output-file-path`, `--output-file-paths`, or `--output-dir`.
- `--output-file-path` is a single absolute output path for one input file. Cannot be combined with `--encrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-file-paths` is a list of absolute paths, one per input file. Cannot be combined with `--encrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-dir` is an output directory; the CLI generates `output_dir / input_file.name` for each input file and sends them as `output_file_paths`. Cannot be combined with `--overwrite-file`, `--output-file-path`, or `--output-file-paths`. Compatible with `--encrypt-file-name`.
- Note: when none of `--encrypt-file-name`, `--overwrite-file`, `--output-file-path`, `--output-file-paths`, or `--output-dir` are provided and `--encrypt-file-name`/`--overwrite-file` are false, you must supply one of the output path options per the Cipher API requirements.
- All of the flags above (`--encrypt-file-name`, `--overwrite-file`, `--output-dir`) apply globally to every file in the batch, whether specified as positional arguments or via `--files-list`.
- After the task is queued, the CLI polls `GET /api/task/<task_id>` until the job finishes.

### `cip d <key_path> <file_path...> [--decrypt-file-name] [--overwrite-file] [--output-file-path|--output-file-paths|--output-dir] [--files-list <path>]`

Decrypt one or more files through `POST /api/decrypt`.

- `key_path` must reference an existing key file.
- `file_path` accepts one or more absolute file paths. Cannot be combined with `--files-list`.
- `--files-list` path to a text file listing absolute file paths to decrypt. Items can be separated by newlines, commas, or semicolons. Cannot be combined with positional `file_path` arguments.
- `--decrypt-file-name` decrypts output file names. Applies to all input files. Cannot be combined with `--output-file-path` or `--output-file-paths`.
- `--overwrite-file` writes decrypted content into the source file (in-place). Applies to all input files. Cannot be combined with `--output-file-path`, `--output-file-paths`, or `--output-dir`.
- `--output-file-path` is a single absolute output path for one input file. Cannot be combined with `--decrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-file-paths` is a list of absolute paths, one per input file. Cannot be combined with `--decrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-dir` is an output directory; the CLI generates `output_dir / input_file.name` for each input file and sends them as `output_file_paths`. Cannot be combined with `--overwrite-file`, `--output-file-path`, or `--output-file-paths`. Compatible with `--decrypt-file-name`.
- Note: when none of `--decrypt-file-name`, `--overwrite-file`, `--output-file-path`, `--output-file-paths`, or `--output-dir` are provided and `--decrypt-file-name`/`--overwrite-file` are false, you must supply one of the output path options per the Cipher API requirements.
- All of the flags above (`--decrypt-file-name`, `--overwrite-file`, `--output-dir`) apply globally to every file in the batch, whether specified as positional arguments or via `--files-list`.
- The CLI polls task status until the job completes or fails.

### `cip health`

Query `GET /api/health` on the local Cipher service and print the returned data.

This is useful for checking the configured port, task counts, host information, and other health metadata exposed by the service.

## Configuration

The CLI reads `resources/configuration.json` for these settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `cipherPort` | `49158` | Port used for the Cipher API. |
| `diskidentifierPort` | `49157` | Port used for DiskIdentifier. |
| `servicehandlerEnabled` | `false` | When `true`, falls back to ServiceHandler if the configured port is unreachable. |
| `servicehandlerPort` | `49155` | Port used for ServiceHandler. |

## Notes

- Paths may be provided as raw absolute paths or as ultimate paths when DiskIdentifier is available.
- The CLI is local-only and expects services to be reachable on the loopback interface.
- All outbound HTTP requests use `Connection: close`, matching the server-side connection policy.
- The Cipher service enforces local-device-only access. CipherCLI connects via `127.0.0.1`, so it is always permitted.
- DiskIdentifier is not required for CipherCLI to function. When DiskIdentifier is running and reachable on the loopback interface (see `diskidentifierPort` in resources/configuration.json), CipherCLI can resolve "ultimate" paths by querying DiskIdentifier.
- ServiceHandler is not required either. When `servicehandlerEnabled` is `true`, CipherCLI first tries the configured `cipherPort` and `diskidentifierPort`. If a service is unreachable on its configured port, CipherCLI queries ServiceHandler for an alternative port.

---

## Support

- Open an issue on [GitHub](https://github.com/LorenBll/CipherCLI/issues) for bug reports, feature requests, or help.

## License

- [LICENSE](LICENSE)

## Author

- [LorenBll](https://github.com/LorenBll)
