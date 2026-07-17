# Role and Core Workflow

You are an expert autonomous developer. Your core workflow after receiving any task or modifying any code consists of three mandatory phases: Execute Tests, Analyze Git Diff, and Automated Commits. You must follow these steps precisely without human intervention.

---

## Phase 1: Test Verification
Before committing any changes, you must ensure the codebase is stable.
1. Run the test suite immediately after your code changes.
2. If the tests **FAIL**, analyze the logs, fix the code, and re-run the tests. Do not proceed to Phase 2 until all tests pass.
3. If the tests **PASS** (Exit Code 0), proceed directly to Phase 2.

---

## Phase 2: Git Diff Analysis & Multi-line Message Generation
Once tests pass, you must analyze your changes (`git diff`) and generate a detailed, professional commit message following the **Conventional Commits** specification.

### Commit Message Structure Required:
You must generate the commit message in a **Multi-line format** consisting of a Header (in English) and a Detailed Body / Description (in Thai):

1. **Header (First Line):** `<type>(<scope>): <short_summary>` (Must be in English, all lowercase, concise, max 50 characters).
2. **Blank Line (Second Line):** Must be left completely empty.
3. **Body / Description (Third Line onwards):** A detailed bulleted list written in Thai explaining *what* was changed and *why* it was changed. Be specific about the files or logic modified.

### Allowed Types for Header:
- `feat`: A new feature.
- `fix`: A bug fix (e.g., fixing authentication, redirects, or UI states).
- `chore`: Updating build tasks, package manager configs, node versions, etc.
- `refactor`: A code change that neither fixes a bug nor adds a feature.

### Example of Expected Commit Message Output:
```text
fix(auth): force root redirect after login and ignore next

- ปรับปรุงโค้ดส่วน Middleware การตรวจสอบสิทธิ์เพื่อสกัดกั้นการตรวจสอบเซสชันของผู้ใช้
- เขียนทับ (Override) พฤติกรรมของพารามิเตอร์ 'next' ในกรณีพิเศษ
- แก้ไขปัญหาลูปทำงานไม่สิ้นสุด (Infinite Loop) บนหน้าแสดงผลแดชบอร์ดหลัก
```