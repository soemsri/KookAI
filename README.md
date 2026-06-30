# AGY Workspace Chat Client

A companion system that connects your mobile device directly to your local Antigravity (AGY) workspace, allowing you to chat and interact with the workspace on the go.

---

## 🛠️ Server Setup

The server acts as the backend broker and hosts the web chat console.

### Prerequisites
- **Python 3.10+**
- **Node.js** (for tunnel sharing)

### Installation
1. Install the required Python packages:
   ```bash
   pip install fastapi uvicorn pydantic
   ```
2. Start the server:
   ```bash
   python main.py
   ```
   *Note: The server automatically launches `npx localtunnel` to make the connection secure and accessible from your mobile phone.*

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
4. **Start Chatting**: Once successfully paired, you can now interact with your local AGY workspace directly from your mobile phone!
