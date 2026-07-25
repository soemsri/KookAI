# Kookai AI agent on mobile 

A companion system that connects your mobile device directly to your local KookAI workspace, allowing you to chat and interact with the workspace on the go.

---

## 🛠️ Server Setup

The server acts as the backend broker and hosts the web chat console.

### Prerequisites
- **Python 3.10+**
- **Node.js** (for tunnel sharing)
- **KookAI (`agy`) CLI** for the existing Gemini/Claude/GPT-OSS models
- **Codex CLI** for the Codex model family (`5.6 Sol`, `5.6 Terra`, `5.6 Luna`, `5.5`, `5.4`, and `5.4 Mini`)

### Installation
1. Install the required Python packages:
   ```bash
   pip install fastapi uvicorn pydantic
   ```
2. To use Codex models, install and authenticate the Codex CLI:
   ```bash
   npm install -g @openai/codex
   codex login
   ```
   If the server cannot find the runnable CLI (for example, when a Windows app
   alias shadows it), set `CODEX_CLI_PATH` to the full executable path.
3. Start the server:
   ```bash
   python main.py
   ```
   *Note: The server automatically launches a Cloudflare Quick Tunnel to make the connection accessible from your mobile phone.*

---

## 📱 Mobile App Setup

The mobile app is built with React Native and Expo.

### Prerequisites
- **Node.js** and **npm**
- **Expo Go** app installed on your iOS/Android device (from App Store or Google Play)

### Installation
1. Navigate to the mobile directory:
   ```bash
   cd mobile
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Start the Expo developer tool:
   ```bash
   npx expo start
   ```
4. Scan the QR code shown in your terminal using the **Expo Go** app (Android) or your phone camera (iOS).

---

## 🚀 How to Use

1. **Start the Server**: Run `python main.py` on your computer.
2. **Get a Pairing PIN**: 
   - Open `http://localhost:8080` in your web browser.
   - Click **Generate PIN** to get a 6-digit pairing code.
3. **Pair Mobile**: 
   - Open the app on your mobile device.
   - Enter the 6-digit pairing PIN.
4. **Start Chatting**: Once successfully paired, you can now interact with your local KookAI workspace directly from your mobile phone!

### Codex options

Selecting a Codex model exposes two additional controls:

- **Effort**: Light, Medium, High, Extra High, and (for 5.6 Sol/Terra) Ultra.
- **Speed**: Standard or Fast. Fast uses more allowance and is unavailable for 5.4 Mini.

`Sandbox` maps to Codex workspace-write isolation. `Real` bypasses Codex
approvals and sandboxing, so only use it with a trusted paired device and
workspace.

---

## 📞 การสนับสนุนและสัญญาอนุญาต (Support & License)

- **สัญญาอนุญาต (License)**: MIT License
- **ข้อมูลติดต่อผู้พัฒนา (Developer Contact)**: rangsarn@gmail.com
- **สนับสนุนผู้พัฒนา (Donations)**: `0xcCAe4BDA3F9A92dd14D4193680535128f7DEE842` (ERC-20 / EVM Address)

