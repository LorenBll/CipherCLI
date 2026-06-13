# CipherCLI

CipherCLI is a local command-line client for the Cipher service. It can create Fernet keys, encrypt or decrypt files through the loopback HTTP API, and query the service health endpoint with `cip health`.

## About
CipherCLI is designed to run on the same machine as [Cipher](https://www.github.com/LorenBll/Cipher). It talks to `127.0.0.1` for both the Cipher API and the [DiskIdentifier](https://www.github.com/LorenBll/DiskIdentifier) service used to resolve ultimate paths. The ports are read from `resources/configuration.json`.

CipherCLI is a client for the web-service Cipher (https://www.github.com/LorenBll/Cipher).

## Setup
1. Install the Python dependencies with `pip install -r requirements.txt`.
2. Make sure the Cipher service is running locally before using `c`, `d`, or `health`.
3. DiskIdentifier is optional — CipherCLI works without it. If you want to use ultimate paths, run DiskIdentifier locally so CipherCLI can resolve them via the configured `diskidentifierPort`.
4. Keep the project structure intact so the CLI can find `resources/` and `src/`.

## Run
1. Windows: run `scripts\cip.bat`.
2. Unix-like systems: run `bash scripts/cip.sh`.
3. Manual: run `python src/main.py` from the project root.

## Usage

### `cip ck <path> [file_name]`
Create a new Fernet key file through `POST /api/key`.

- `path` can be either:
  - an absolute file path for the new key, or
  - an absolute directory path when `file_name` is provided.
- `file_name` must be a simple file name with no path components.

Example:

```bash
cip ck C:\Cipher\keys mykey.key
```

### `cip c <key_path> <file_path...> [--encrypt-file-name] [--overwrite-file] [--output-file-path|--output-file-paths|--output-dir]`
Encrypt one or more files through `POST /api/encrypt`.

- `key_path` must reference an existing key file.
- `file_path` accepts one or more absolute file paths.
- `--encrypt-file-name` encrypts output file names. Cannot be combined with `--output-file-path` or `--output-file-paths`.
- `--overwrite-file` writes encrypted content into the source file (in-place). Cannot be combined with `--output-file-path`, `--output-file-paths`, or `--output-dir`.
- `--output-file-path` is a single absolute output path for one input file. Cannot be combined with `--encrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-file-paths` is a list of absolute paths, one per input file. Cannot be combined with `--encrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-dir` is an output directory; the CLI generates `output_dir / input_file.name` for each input file and sends them as `output_file_paths`. Cannot be combined with `--overwrite-file`, `--output-file-path`, or `--output-file-paths`. Compatible with `--encrypt-file-name`.
- Note: when none of `--encrypt-file-name`, `--overwrite-file`, `--output-file-path`, `--output-file-paths`, or `--output-dir` are provided and `--encrypt-file-name`/`--overwrite-file` are false, you must supply one of the output path options per the Cipher API requirements.
- After the task is queued, the CLI polls `GET /api/task/<task_id>` until the job finishes.

### `cip d <key_path> <file_path...> [--decrypt-file-name] [--overwrite-file] [--output-file-path|--output-file-paths|--output-dir]`
Decrypt one or more files through `POST /api/decrypt`.

- `key_path` must reference an existing key file.
- `file_path` accepts one or more absolute file paths.
- `--decrypt-file-name` decrypts output file names. Cannot be combined with `--output-file-path` or `--output-file-paths`.
- `--overwrite-file` writes decrypted content into the source file (in-place). Cannot be combined with `--output-file-path`, `--output-file-paths`, or `--output-dir`.
- `--output-file-path` is a single absolute output path for one input file. Cannot be combined with `--decrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-file-paths` is a list of absolute paths, one per input file. Cannot be combined with `--decrypt-file-name`, `--overwrite-file`, or `--output-dir`.
- `--output-dir` is an output directory; the CLI generates `output_dir / input_file.name` for each input file and sends them as `output_file_paths`. Cannot be combined with `--overwrite-file`, `--output-file-path`, or `--output-file-paths`. Compatible with `--decrypt-file-name`.
- Note: when none of `--decrypt-file-name`, `--overwrite-file`, `--output-file-path`, `--output-file-paths`, or `--output-dir` are provided and `--decrypt-file-name`/`--overwrite-file` are false, you must supply one of the output path options per the Cipher API requirements.
- The CLI polls task status until the job completes or fails.

### `cip health`
Query `GET /api/health` on the local Cipher service and print the returned data.

This is useful for checking the configured port, task counts, host information, and other health metadata exposed by the service.

## Configuration
The CLI reads `resources/configuration.json` for these settings:
- `cipherPort`: port used for the Cipher API.
- `diskidentifierPort`: port used for DiskIdentifier.

## Notes
- Paths may be provided as raw absolute paths or as ultimate paths when DiskIdentifier is available.
- The CLI is local-only and expects services to be reachable on the loopback interface.

- DiskIdentifier is not required for CipherCLI to function. When DiskIdentifier is running and reachable on the loopback interface (see `diskidentifierPort` in resources/configuration.json), CipherCLI can resolve "ultimate" paths by querying DiskIdentifier.

## License
- [LICENSE](LICENSE)

## Author
- [LorenBll](https://github.com/LorenBll)
