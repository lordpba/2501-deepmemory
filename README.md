# 2501 DeepMemory
> *Portable, Persistent AI Memory.*

![2501 Logo](2501_small.png)

> *"Your Ghost travels with you. The Shell is just borrowed."*
> — inspired by Project 2501, Ghost in the Shell (Masamune Shirow)

![2501 Ghost](name_your_ghost.png)

**Your AI memory dies every time you switch models. 2501 fixes that.**

ChatGPT doesn't remember you when you move to Claude. Claude doesn't remember you when you move to Llama. Every conversation starts from zero. Your memory belongs to their servers, not to you.

2501 is different. Your memory — your **Ghost** — lives encrypted in a folder you control, or on a **USB stick** in your pocket. Plug it into any machine, and your AI is there. Switch models whenever you want. The Ghost stays.

---

## How it works

```
your Ghost (encrypted USB) + LLM (Local/Cloud) = your personal AI
```

The Ghost is yours. The machine is just a **Shell** you borrow.

---

## Features (v1.1.0)

- **Portable USB Mode** — Auto-deploy the entire system to a USB stick. Works on any machine without installation.
- **Cross-Platform** — Native launchers for Linux (`run.sh`) and Windows (`run.bat`), plus direct bootstrapping from `python3 2501.py`.
- **Local venv bootstrap** — `2501.py` creates a repository-local `venv/` on first run and installs `requirements.txt` automatically.
- **Portable Dependencies** — USB mode still supports a local `libs` folder for portable installs on FAT32/exFAT sticks.
- **Multi-Provider LLM** — Use local **Ollama** (including remote LAN endpoints), **OpenAI**, **Google Gemini**, or **Anthropic Claude**.
- **Secure Key Vault** — Your API keys are stored **encrypted** inside your Ghost. Only you can unlock them.
- **Hierarchical LLM Wiki** — Obsidian-style tree view. Automatically groups memories into categories (`project`, `knowledge`, `user`).
- **Multimodal** — Send PDFs, images, and documents for analysis.
- **Wake/Sleep Cycle** — Automatic memory consolidation after 45 seconds of conversation pause.

---

## Quick Start

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/lordpba/2501-deepmemory
cd 2501-deepmemory

# Launch directly (Linux / macOS)
python3 2501.py

# Or launch via the Linux wrapper
bash run.sh

# Launch on Windows
run.bat
```

### 2. Deployment to USB (Optional)
Run the script and choose **"Yes"** when asked to deploy to USB. 
2501 will detect your USB stick, copy all files, and set up a portable environment.

Once deployed, just plug the stick into any computer and run:
- **Linux**: `bash run.sh`
- **Windows**: Double-click `run.bat`

### 3. Syncing from USB to Desktop
If you use your Ghost on the go via a USB stick, its memories will evolve independently. To synchronize the newly learned memories from the USB back to your primary Desktop Ghost, run:
```bash
python 2501.py --sync-from-usb
```
*Note: For security, you will be asked for the Desktop Ghost's password before the sync can overwrite your local data.*

---

## LLM Configuration

You can configure your LLM by clicking the **Settings (gear icon)** in the top right of the UI:

- **Ollama**: Specify a local or LAN endpoint (e.g., a DGX server).
- **Cloud APIs**: Select OpenAI, Gemini, or Claude and enter your API Key.
- **Ghost Security**: All settings and memories are Fernet-encrypted (AES-128-CBC + HMAC) using your Ghost password.

---

## The Ghost Structure

Your Ghost is a set of encrypted markdown files. Under the encryption, it's plain text — readable by humans, editable, and compatible with Obsidian.

```
ghost/
├── identity/      ← encrypted identity, config & API keys
├── wiki/          ← hierarchical memories (Obsidian-style)
│   ├── project-x.md
│   ├── knowledge-y.md
│   └── index.md
└── sessions/      ← full conversation logs
```

---

## Philosophy

Most AI products put the intelligence in the model.
**2501 puts the intelligence in the memory.**

A small local model with a rich Ghost outperforms a large cloud model with no memory of you. The Ghost is the product. The LLM is just the voice.

---

## License

MIT
