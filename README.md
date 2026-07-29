# KookAI AI Agent on Mobile

A companion system that connects your mobile device directly to your local KookAI workspace, allowing you to chat and interact with the workspace on the go.

---

## Server Setup

The server acts as the backend broker and hosts the web chat console.

### Prerequisites

- **Python 3.10+**
- **Node.js / npm**
- **Antigravity CLI (`agy`)** for Gemini / Claude / GPT-OSS models through Antigravity
- **Codex CLI** for Codex models (`5.6 Sol`, `5.6 Terra`, `5.6 Luna`, `5.5`, `5.4`, `5.4 Mini`)
- **Anthropic Claude Code CLI (`claude`)** for native Claude models (`Fable 5`, `Opus 5`, `Sonnet 5`, `Haiku 4.5`, etc.)
  - The npm install path requires **Node.js / npm**.
- **Moonshot Kimi Code CLI (`kimi`)** for Kimi K3
  - Windows requires **Git for Windows** because Kimi Code uses Git Bash.
- **xAI Grok Build CLI (`grok`)** for Grok 4.5, Grok 4.20, and Grok Build models

### Installation

1. Start the server:

   ```bash
   # macOS / Linux
   ./run_server.sh

   # Windows
   run_server.bat
   ```

   On first launch, KookAI creates the Python virtual environment when needed,
   installs missing Python packages from `requirements.txt`, and checks the
   `agy`, `claude`, `codex`, `kimi`, and `grok` declarations in the same file. Missing CLIs are
   downloaded and installed automatically before the server starts.

   Set `KOOKAI_AUTO_INSTALL_CLIS=0` to disable automatic CLI installation.
   A failed install remains visible in **Settings → Connections**, where an
   administrator can retry it.

   Long-running agent jobs use an inactivity timeout rather than a total
   runtime limit. `AGY_CLI_TIMEOUT` controls how many seconds a CLI may produce
   no output before it is treated as stuck (default: `600`; `0` disables it).
   Set `AGY_CLI_MAX_RUNTIME` to a positive number of seconds only if you also
   want a hard wall-clock limit (default: `0`, disabled).

2. The automatic Antigravity CLI (`agy`) installation uses:

   **macOS / Linux**
   ```bash
   curl -fsSL https://antigravity.google/cli/install.sh | bash
   ```

   **Windows PowerShell**
   ```powershell
   irm https://antigravity.google/cli/install.ps1 | iex
   ```

   **Windows CMD**
   ```cmd
   curl -fsSL https://antigravity.google/cli/install.cmd -o install.cmd && install.cmd && del install.cmd
   ```

   Launch and verify:

   ```bash
   agy
   agy --version
   ```

3. The automatic Codex installation uses:

   ```bash
   npm install -g @openai/codex
   codex login
   codex --version
   ```

   If the server cannot find the runnable CLI, set `CODEX_CLI_PATH` to the full executable path.

4. The automatic Claude Code installation uses:

   ```bash
   npm install -g @anthropic-ai/claude-code
   ```

   Start Claude Code once and complete the sign-in flow:

   ```bash
   claude
   ```

   Then verify:

   ```bash
   claude --version
   ```

   If the server cannot find the runnable CLI, set `CLAUDE_CLI_PATH` to the full executable path.

5. The automatic Kimi Code installation uses:

   **macOS / Linux**
   ```bash
   curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash
   ```

   **Windows PowerShell**
   ```powershell
   irm https://code.kimi.com/kimi-code/install.ps1 | iex
   ```

   Authenticate and verify:

   ```bash
   kimi login
   kimi --version
   ```

   If the server cannot find the runnable CLI, set `KIMI_CLI_PATH` to the full executable path.

6. The automatic Grok Build installation uses:

   **macOS / Linux**
   ```bash
   curl -fsSL https://x.ai/cli/install.sh | bash
   ```

   **Windows PowerShell**
   ```powershell
   irm https://x.ai/cli/install.ps1 | iex
   ```

   Authenticate, inspect the models available to the account, and verify:

   ```bash
   grok login
   grok models
   grok --version
   ```

   Headless environments may set `XAI_API_KEY` instead of opening the login
   flow. If the server cannot find the executable, set `GROK_CLI_PATH`.

7. Open **Settings → Connections** and select **Connect** for each provider.
   KookAI opens that provider's interactive sign-in in a terminal on the server
   computer. For security, CLI installation and connection management are
   available only from localhost.

The server automatically launches a Cloudflare Quick Tunnel so your mobile phone can reach your local workspace.

### Project Workspaces

By default, KookAI lists immediate subdirectories of the current user's
Desktop as projects. The application installation directory is kept separate
and is never scanned for projects.

Set `KOOKAI_PROJECTS_ROOTS` before starting the server to allow projects from
different locations. Separate multiple roots with the platform path separator
(`:` on macOS/Linux, `;` on Windows):

```bash
KOOKAI_PROJECTS_ROOTS="/srv/projects:/root/Desktop" ./run_server.sh
```

Only directories directly inside these configured roots can be selected as
workspaces. Unknown project names are rejected instead of falling back to the
KookAI application directory.

Paired mobile devices can also create a project from the project picker. New
projects are created as directories inside the first configured project root.

### Dynamic Model Catalog

KookAI serves a versioned model catalog from `GET /api/models`. The web client
and paired mobile app use that response instead of requiring model names to be
compiled into the app. The mobile app caches the latest valid catalog and falls
back to its built-in list when the host is temporarily unavailable.

From the server computer, open **Settings → Models** to add, disable, reorder,
or update models. The editor validates the complete JSON document before
saving it. Runtime changes are stored persistently at:

```text
~/.gemini/kookai/model_catalog.json
```

The bundled [`model_catalog.json`](model_catalog.json) is used until a
persistent override is saved. Each model separates:

- `id`: stable value sent by clients and stored with conversations
- `label`: user-facing name
- `cli_model`: exact model name or slug passed to the provider CLI
- `provider`: `agy`, `claude`, `codex`, `kimi`, or `xai`
- `capabilities`: supported effort, speed, and thinking controls
- `enabled`: removes a model from clients without deleting its configuration

Set `KOOKAI_MODEL_CATALOG_PATH` to use a different persistent catalog file.
Catalog management is localhost-only, while paired mobile devices can read
enabled models through their existing authorization token.

Adding models that use the existing `agy`, `claude`, `codex`, `kimi`, or `xai` controls does
not require a new mobile build. A genuinely new provider, input type, or UI
capability still requires an app update because older clients do not know how
to render or execute that new interaction.

### Restarting the Server

If you change backend code, provider settings, or CLI paths, restart the server so `localhost:8080` loads the latest code:

```powershell
# Stop the old python main.py process if it is still running, then:
cd D:\Gemini\Project\KookAI
python main.py
```

If the browser still shows stale behavior, refresh with `Ctrl + F5`.

---

## Mobile App Setup

The mobile app is built with React Native and Expo.

### Prerequisites

- **Node.js** and **npm**
- **Expo Go** app installed on your iOS/Android device, or a native Android build installed on your phone

### Installation

1. Navigate to the mobile directory:

   ```bash
   cd mobile
   ```

2. Install dependencies:

   ```bash
   npm install
   ```

3. Start Expo:

   ```bash
   npx expo start
   ```

4. Scan the QR code with **Expo Go** or build/install the native Android app.

### Android Release Build

To build and install a release APK on a connected Android device:

```powershell
cd D:\Gemini\Project\KookAI\mobile\android
.\gradlew.bat assembleRelease
adb install -r .\app\build\outputs\apk\release\app-release.apk
adb shell monkey -p com.kookai.app -c android.intent.category.LAUNCHER 1
```

Release APK output:

```text
D:\Gemini\Project\KookAI\mobile\android\app\build\outputs\apk\release\app-release.apk
```

> Note: The current release config signs with the debug keystore for local testing. Use a production keystore before publishing to Google Play.

---

## How to Use

1. Start the server with `python main.py`.
2. Open `http://localhost:8080` in your desktop browser.
3. Click **Generate PIN**.
4. Open the mobile app and enter the 6-digit PIN, or scan the pairing QR code.
5. Start chatting with your local KookAI workspace from mobile.

---

## Model Providers

### Antigravity (`agy`)

Used for Antigravity-supported Gemini / Claude / GPT-OSS models.

### Codex

Selecting a Codex model exposes:

- **Effort**: Light, Medium, High, Extra High, and Ultra for supported models.
- **Speed**: Standard or Fast. Fast uses more allowance and is unavailable for `5.4 Mini`.

`Sandbox` maps to Codex workspace-write isolation. `Real` bypasses Codex approvals and sandboxing, so only use it with a trusted paired device and workspace.

### Native Claude Code

Native Claude models run through Anthropic's `claude` CLI and keep resumable sessions separate from Antigravity and Codex conversations.

- **Effort**: Low, Medium, High, Extra, or Max when supported by the selected Claude model.
- **Thinking**: Enables or disables Claude extended thinking.
- **Sandbox**: Runs non-interactively with permission prompts denied.
- **Real**: Uses `--dangerously-skip-permissions`; only use this with a trusted paired device and workspace.

### Kimi Code

Kimi K3 runs through Moonshot's `kimi` CLI with the `kimi-for-coding/k3`
model alias. KookAI uses non-interactive `stream-json` output and stores Kimi
session IDs separately so conversations can be resumed.

### xAI Grok Build

xAI models run through the official `grok` CLI using newline-delimited
`streaming-json` output. KookAI captures the returned `sessionId` and resumes
later turns with `--resume`.

- **Grok 4.5**: configurable Low, Medium, or High reasoning effort.
- **Grok 4.20 Reasoning / Non-Reasoning**: explicit reasoning variants.
- **Grok Build 0.1**: coding-focused model for agentic workflows.
- **Sandbox**: combines `--sandbox workspace` with automatic tool approvals,
  limiting writes to the selected workspace and temporary files.
- **Real**: runs with automatic approvals and no Grok OS sandbox. Only use it
  with a trusted paired device and workspace.

Run `grok models` after login to confirm which catalog slugs the current xAI
account may use.

---

## Troubleshooting

### `Unsupported agent provider: claude`

This usually means the server process is stale and still running older code.

Fix:

1. Stop the existing `python main.py` process.
2. Start the server again from `D:\Gemini\Project\KookAI`:

   ```powershell
   python main.py
   ```

3. Refresh the browser with `Ctrl + F5`.

### `Failed to run claude CLI` or `No runnable Claude Code CLI was found`

Check:

```bash
claude --version
```

If it works in your terminal but not in KookAI, set `CLAUDE_CLI_PATH` to the full path of the `claude` executable and restart the server.

### `Failed to run codex CLI` or `No runnable Codex CLI was found`

Check:

```bash
codex --version
```

If it works in your terminal but not in KookAI, set `CODEX_CLI_PATH` to the full path of the `codex` executable and restart the server.

### `Failed to run kimi CLI` or `No runnable Kimi Code CLI was found`

Check:

```bash
kimi --version
kimi login
```

If it works in your terminal but not in KookAI, set `KIMI_CLI_PATH` to the full path of the `kimi` executable and restart the server.

### `Failed to run grok CLI` or `No runnable Grok Build CLI was found`

Check:

```bash
grok --version
grok login
grok models
```

If it works in your terminal but not in KookAI, set `GROK_CLI_PATH` to the full
path of the `grok` executable and restart the server.

---

## References

- [Google Antigravity CLI installation and auth](https://antigravity.google/docs/cli/install)
- [Google Antigravity download page](https://antigravity.google/download)
- [OpenAI Codex CLI](https://developers.openai.com/codex/cli)
- [OpenAI Codex authentication](https://learn.chatgpt.com/docs/auth)
- [Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/setup)
- [Claude Code authentication](https://docs.anthropic.com/en/docs/claude-code/iam)
- [Kimi Code CLI](https://github.com/MoonshotAI/kimi-code)
- [Kimi command reference](https://moonshotai.github.io/kimi-code/en/reference/kimi-command.html)
- [xAI Grok Build CLI](https://docs.x.ai/build/overview)
- [xAI Grok CLI reference](https://docs.x.ai/build/cli/reference)

---

## Support & License

- **License**: MIT License
- **Developer Contact**: rangsarn@gmail.com
- **Donations**: `0xcCAe4BDA3F9A92dd14D4193680535128f7DEE842` (ERC-20 / EVM Address)
