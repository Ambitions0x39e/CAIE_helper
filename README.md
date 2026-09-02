# CIE Helper
A local app to download CIE past papers, mark them with AI, and track your scores.

---

## Setup
1. Install `uv` (Astral's Python package manager) — see the instructions [here](https://docs.astral.sh/uv/getting-started/installation/). `uv` will fetch the right Python version for you.
2. Run `uv sync` to install the dependencies.
3. Build the UI with `npm run build --prefix frontend`, then package with
   `uv run pyinstaller packaging/cie-helper.spec --noconfirm`.

### Installer for distribution
Compile `packaging/windows/cie-helper.iss` with Inno Setup 6 → `dist/cie-helper-<version>-setup.exe`.

It ships unsigned, so expect the usual SmartScreen warning on first open. In-app updates need no bypass — the app fetches and installs the package itself, and nothing quarantines a file it downloaded.

---

## Marking
This feature requires an image (vision) model to read the handwritten papers.
By default the app uses the `qwen3.6-flash` model, but you can change it to any model you like in Settings.

If you use `qwen3.6-flash`, you will need an API key from DashScope by Alibaba Cloud (Aliyun).

---

## Sending to GoodNotes
In GoodNotes' settings you can find an import email address linked to your account.
Register this address in Settings, and you can then send your downloaded papers to GoodNotes directly from the app.

---
