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
  - The npm install path for Claude Code recommends **Node.js 22+**.

### Installation

1. Install the required Python packages:

   ```bash
   pip install fastapi uvicorn pydantic
   ```

2. Download and install the Antigravity CLI (`agy`):

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

   Login and verify:

   ```bash
   agy login
   agy --version
   ```

3. To use Codex models, install and authenticate the Codex CLI:

   ```bash
   npm install -g @openai/codex
   codex login
   codex --version
   ```

   If the server cannot find the runnable CLI, set `CODEX_CLI_PATH` to the full executable path.

4. To use native Claude models, install Claude Code:

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

5. Start the server:

   ```bash
   python main.py
   ```

   The server automatically launches a Cloudflare Quick Tunnel so your mobile phone can reach your local workspace.

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

---

## References

- [Google Antigravity CLI installation and auth](https://antigravity.google/docs/cli/install)
- [Google Antigravity download page](https://antigravity.google/download)
- [Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/setup)
- [Claude Code authentication](https://docs.anthropic.com/en/docs/claude-code/iam)

---

## Support & License

- **License**: MIT License
- **Developer Contact**: rangsarn@gmail.com
- **Donations**: `0xcCAe4BDA3F9A92dd14D4193680535128f7DEE842` (ERC-20 / EVM Address)
