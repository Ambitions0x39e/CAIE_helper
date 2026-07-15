# CIE Helper
A local app to download CIE past papers, mark them with AI, and track your scores.

---

## Setup
1. Install `uv` (Astral's Python package manager) — see the instructions [here](https://docs.astral.sh/uv/getting-started/installation/). `uv` will fetch the right Python version for you.
2. Run `uv sync` to install the dependencies.
3. Build the app with `uv run flet build <target>`, where `<target>` is `windows`, `macos`, `ipa` (iOS device), or `ios-simulator`.

---

## Marking
This feature requires an image (vision) model to read the handwritten papers.
By default the app uses the `qwen3-vl-flash` model, but you can change it to any model you like in Settings.

If you use `qwen3-vl-flash`, you will need an API key from DashScope by Alibaba Cloud (Aliyun).

---

## Sending to GoodNotes
In GoodNotes' settings you can find an import email address linked to your account.
Register this address in Settings, and you can then send your downloaded papers to GoodNotes directly from the app.

---
