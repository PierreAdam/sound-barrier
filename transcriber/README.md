# Sound-Barrier transcriber

Gives Sound-Barrier's podcasts and audiobooks their text, on a PC with an NVIDIA GPU. The
text shows like synced lyrics in the web UI (Now playing, karaoke) and in Subsonic apps
that support OpenSubsonic lyrics, and is written as a `.lrc` file next to the audio.

Speech recognition: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (Whisper
large-v3 by default), with voice activity detection and the timing of every word.

## How it works

```
 this PC (GPU)                                   Sound-Barrier server
 transcriber run ──── HTTPS, outgoing only ────▶ /api/transcriber
   1. claim the next file without text            the file is ours for 10 minutes,
   2. download it                                  renewed while we work
   3. transcribe it (in 30-minute chunks)
   4. send the lines back (in parts)               kept, and written as .lrc
```

- The server never connects to the PC: nothing to open on your network.
- The app signs in with a **worker token** (Settings → Transcripts), not with a user's
  password. The token only lets it list, download and transcribe podcasts and audiobooks.
  It is saved in `config.toml` in this folder; revoke it in Settings when needed.
- Two GPUs: `--gpu all` runs one worker per GPU. They never take the same file: the
  faster GPU simply takes more.
- A PC turned off mid-file: after 10 minutes the file waits again for any worker.
  Ctrl+C gives it back at once.

## Install (Windows)

Needs an NVIDIA driver, nothing else: Python, the libraries and NVIDIA's cuBLAS / cuDNN are
installed **inside this folder** (like a Pinokio app), nothing system-wide.

1. Double-click `install.cmd` (or `powershell -ExecutionPolicy Bypass -File install.ps1`).
   - It uses [uv](https://docs.astral.sh/uv/) (installed into `env\bin` if you do not have it)
     to get Python 3.12 into `env\python` and the libraries into `.venv`: about 1.5 GB.
   - At the end it lists the GPUs it sees.
2. In Sound-Barrier, Settings → Transcripts, create a token (a name for this PC).
3. Sign in:

   ```bat
   transcriber.cmd login https://music.example.com
   ```

   It asks for the token (hidden input) and checks it.

Run `install.cmd` again to update the libraries. Delete the folder to remove everything.

## Install (Linux)

The same, with the shell scripts (x86-64 or ARM64, an NVIDIA driver, and `curl` or `wget`
if uv is not installed):

```sh
./install.sh            # or: bash install.sh
./transcriber.sh login https://music.example.com
```

`transcriber.sh` takes the same commands as `transcriber.cmd` below. It puts NVIDIA's pip
libraries in `LD_LIBRARY_PATH` before starting Python (the loader only reads it when a
process starts); the app also preloads them when started otherwise.

## Use

On Linux, `./transcriber.sh` instead of `transcriber.cmd`.

```bat
transcriber.cmd list                        what waits for text
transcriber.cmd show "dune"                 the files of a book / show, and their state
transcriber.cmd run "dune" --gpu 0          transcribes a book (several names allowed)
transcriber.cmd run --all --gpu all         everything that waits, on every GPU
transcriber.cmd run --all --kind podcasts --gpu 1
transcriber.cmd devices                     the GPUs that can be used
```

Books and shows are named by (part of) their title, or by their id (`show` prints it).

Options of `run`:

| Option | Default | |
|---|---|---|
| `--gpu` | 0 | a GPU (`devices`, or `nvidia-smi -L`), a list (`0,1`), or `all`: one worker per GPU, each line of progress prefixed with its GPU; Ctrl+C gives every file back |
| `--model` | `large-v3` | `large-v3-turbo` (much faster, nearly as good), `medium`, `small` |
| `--language` | detected | e.g. `fr`, `en`: detected on the first 30 minutes of each file otherwise |
| `--compute-type` | `float16` | `int8_float16` uses less GPU memory |
| `--batch-size` | 8 | lower it if the GPU runs out of memory; 1 decodes one by one (slower) |
| `--retry-failed` | | also takes files that failed before (or: Retry failed in Settings) |

The model is downloaded on first use into `models\` (large-v3: about 3 GB).

Rough speed with large-v3 on an RTX 3080 Ti: 30 to 60 times real time (a 15-hour book in
15 to 30 minutes). A file that fails (a broken file, the GPU out of memory) is marked as
failed on the server; three failures in a row stop the run.

## Folder layout

```
transcriber/
  install.cmd, install.ps1   installation (this folder only), Windows
  install.sh                 the same, Linux
  transcriber.cmd            runs the app with this folder's environment (Linux: transcriber.sh)
  config.toml                the server and the token (after `login`)
  env/  .venv/  models/      Python, the libraries, the Whisper models
  work/                      the file being transcribed (removed afterwards)
  src/sb_transcriber/        the app
```

`SB_TRANSCRIBER_HOME` moves `config.toml`, `models/` and `work/` elsewhere.

## Development

```bat
.venv\Scripts\python -m pytest
```

(Linux: `.venv/bin/python -m pytest`.)

The server side is in the backend: `app/api/transcripts.py` (worker API and admin routes)
and `app/services/transcripts.py` (claims, leases, `.lrc` files).
