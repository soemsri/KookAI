# KookAI AI Agent (Web & Mobile Companion)

**KookAI** คือระบบ AI Agent ที่เชื่อมต่อพื้นที่ทำงานบนคอมพิวเตอร์ของคุณเข้ากับแอปมือถือและ Web Console ช่วยให้คุณสั่งงาน วิเคราะห์โค้ด ถอดเสียงและวิเคราะห์คลิปวิดีโอผ่าน LLM หลายค่ายได้อย่างสะดวกรวดเร็ว

<p align="center">
  <img src="docs/assets/mobile-preview.jpg" alt="KookAI Mobile Model Selection" width="360" />
</p>

---

## ✨ ฟีเจอร์เด่น (Key Features)

- 🤖 **Multi-Provider AI CLI:** รองรับโมเดลจากหลายค่ายชั้นนำ:
  - **Antigravity (`agy`):** Gemini 2.5 Flash/Pro, Claude, GPT-OSS
  - **Codex (`codex`):** OpenAI 5.6 Sol / Terra / Luna
  - **Claude Code (`claude`):** Anthropic Claude 3.7 / 3.5
  - **Kimi Code (`kimi`):** Moonshot Kimi K3
  - **xAI Grok (`grok`):** Grok 4.5 / 4.20 / Grok Build
  - **Meta Muse (`muse`):** Muse Spark 1.2
- 🎥 **Universal Video Analysis & `/watch`:**
  - สกัดเฟรมภาพหลัก (Keyframes) และสกัดไฟล์เสียงจาก YouTube / TikTok / Vimeo / ลิงก์ตรง / ไฟล์คลิปในเครื่อง (`.mp4`, `.mov`)
  - ถอดเสียงภาษาไทย/อังกฤษความแม่นยำสูงด้วย **Groq / OpenAI Whisper (`whisper-large-v3`)**
  - ⚡ **Multi-Key Rotation & Failover:** รองรับการใส่หลาย API Key สลับใช้งานแบบ Round-Robin และตัดสลับ Key อัตโนมัติเมื่อติด Rate Limit
- 🌐 **Cloudflare Quick Tunnel & Pairing Code:** สร้างอุโมงค์เชื่อมต่อความปลอดภัยสูง ให้มือถือเชื่อมต่อเข้าเซิร์ฟเวอร์หลังบ้านได้จากทุกที่ทันที
- ⚙️ **Web Dashboard & Settings UI:** บริหารจัดการเซิร์ฟเวอร์ ตรวจสอบ CLI status และตั้งค่า API Key ผ่านหน้าเว็บ `http://localhost:8080`

---

## 🚀 เริ่มต้นใช้งานเซิร์ฟเวอร์ (Quick Start)

### 1. ติดตั้งและเริ่มทำงาน
```bash
# macOS / Linux
./run_server.sh

# Windows
run_server.bat  (หรือ python main.py)
```
> **Note:** ในการเปิดครั้งแรก ระบบจะสร้าง Virtual Environment, ติดตั้ง Python dependencies และดาวน์โหลด CLI ต่างๆ (`agy`, `claude`, `codex`, `kimi`, `grok`, `muse`) ที่ขาดให้อัตโนมัติ

### 2. การติดตั้งและเข้าสู่ระบบ Meta Muse Spark (`muse login`)
- **การติดตั้งอัตโนมัติ:** เมื่อเริ่มต้นเซิร์ฟเวอร์ ระบบจะตรวจสอบและติดตั้ง `muse` CLI ให้อัตโนมัติหากยังไม่มีในเครื่อง
- **การเข้าสู่ระบบ (Login):**
  - **วิธีที่ 1 (ผ่าน Web Dashboard):** เปิดหน้าเว็บ `http://localhost:8080` -> เข้าเมนู **Settings → CLI Status** แล้วกดปุ่ม **Connect** ถัดจาก **Meta Muse Code** เพื่อเปิดหน้าต่างเข้าสู่ระบบ
  - **วิธีที่ 2 (ผ่าน Terminal):** รันคำสั่งใน Terminal/Command Prompt:
    ```bash
    muse login
    ```

### 3. ตั้งค่า Whisper API Key (สำหรับถอดเสียงวิดีโอ)
คุณสามารถสมัครรับ Key ฟรีได้ที่ [Groq Console](https://console.groq.com/keys) แล้วเลือกตั้งค่าได้ 2 วิธี:
- **วิธีที่ 1 (ในไฟล์ `.env`):**
  ```env
  GROQ_API_KEY=gsk_key1, gsk_key2, gsk_key3
  ```
- **วิธีที่ 2 (ผ่าน Web UI):** เปิดหน้าเว็บ `http://localhost:8080` -> เข้าเมนู **Settings → General** -> กรอก Key ในช่อง **Whisper API Keys** แล้วกด **Save Changes**

### 4. จับคู่แอปมือถือ (Pairing)
1. เปิดหน้าเว็บ `http://localhost:8080` บนคอมพิวเตอร์
2. กดปุ่ม **Generate PIN** บนหน้าเว็บ
3. เปิดแอปพลิเคชัน KookAI บนมือถือ แล้วกรอก รหัส PIN 6 หลัก หรือสแกน QR Code เพื่อเริ่มใช้งาน

---

## 🎥 ตัวอย่างคำสั่งถอดความและวิเคราะห์วิดีโอ (`/watch`)

| รูปแบบคำสั่ง / การใช้งาน | คำอธิบาย |
| :--- | :--- |
| `/watch https://youtu.be/XXXXXX สรุปคลิปนี้` | สกัดเฟรม + ถอดเสียง และสรุปใจความสำคัญของคลิป |
| `/watch https://youtu.be/XXXXXX ทำ Timeline` | ถอดเสียงคำพูดพร้อมระบุนาทีสำคัญ (Timestamps) |
| `/watch https://youtu.be/XXXXXX แกะโค้ด` | แกะโค้ดและขั้นตอนการสอนในวิดีโอทีละ Step |
| `[แนบไฟล์วิดีโอ .mp4] สรุปเนื้อหา` | วิเคราะห์และถอดเสียงไฟล์วิดีโอจากเครื่องโดยตรง |

*(ดูตัวอย่าง Prompt เพิ่มเติมได้ในไฟล์ [`video_analysis_prompts.txt`](video_analysis_prompts.txt))*

---

## 🛠️ โครงสร้าง CLI & Model Providers

| Provider | CLI Command | รองรับโมเดลหลัก | ตัวเลือกพิเศษ (Controls) |
| :--- | :--- | :--- | :--- |
| **Antigravity** | `agy` | Gemini 2.5 Flash/Pro, Claude | Sandbox / Real |
| **Codex** | `codex` | 5.6 Sol, 5.6 Terra, 5.4 Mini | Effort (Low-Ultra), Speed (Fast/Std) |
| **Claude Code** | `claude` | Claude 3.7 Sonnet, Opus | Effort (Low-Max), Extended Thinking |
| **Kimi Code** | `kimi` | Kimi K3 | Stream-JSON, Resumable Session |
| **xAI Grok** | `grok` | Grok 4.5, Grok Build 0.1 | Reasoning Effort (Low-High) |
| **Meta Muse** | `muse` | Muse Spark 1.2 | Effort (Low-High), Stream-JSON |

---

## 📱 แอปพลิเคชันมือถือ (Mobile App Setup)

แอปมือถือพัฒนาด้วย **React Native / Expo**:

```bash
cd mobile
npm install
npx expo start
```

### การ Build APK สำหรับ Android:
```powershell
cd mobile\android
.\gradlew.bat assembleRelease
adb install -r .\app\build\outputs\apk\release\app-release.apk
```

---

## 📄 Support & License

- **License:** MIT License
- **Developer Contact:** rangsarn@gmail.com
- **Donations:** `0xcCAe4BDA3F9A92dd14D4193680535128f7DEE842` (EVM Address)
