# Project: NeurIPS Whisper

## 1. Goal
Build a minimal, real-time "Town Square" for NeurIPS conference participants.
- **Stack:** Python (FastAPI), HTML/HTMX (Frontend), Redis (Pub/Sub & Rate Limiting), PostgreSQL (Persistence).
- **Deployment:** Railway (or Docker-ready VPS).

## 2. Authentication (Strict "Professional" Filter)

### A. The Login Flow
1. **User Input:** Email + Conference Code + "Agree to Terms" Checkbox.
2. **Shared Secret Check:** Validate code matches env var `CONFERENCE_SECRET`.
3. **Domain Blocklist Check:**
   - **Goal:** Filter out "anonymous/generic" accounts to ensure professional accountability.
   - **Logic:** Reject if email domain matches the **Global Free Provider List**:
     - *US/Global:* `gmail.com`, `googlemail.com`, `yahoo.com`, `hotmail.com`, `outlook.com`, `live.com`, `icloud.com`, `me.com`, `aol.com`, `protonmail.com`, `proton.me`.
     - *China:* `163.com`, `126.com`, `qq.com`, `foxmail.com`, `sina.com`, `sohu.com`, `yeah.net`.
     - *Europe/Russia:* `gmx.de`, `gmx.net`, `web.de`, `mail.ru`, `yandex.ru`, `libero.it`, `virgilio.it`, `laposte.net`.
   - *Error Message:* "Please use your institutional or company email (university or industry lab)."

4. **Terms of Use (Strict):**
   - User *must* check a box: *"I agree to the Terms of Use."*
   - **Terms Text:**
     1. "Messages are immutable (cannot be deleted/edited)."
     2. "Data is ephemeral: All data will be wiped 48 hours after the conference ends."
     3. "No scraping, archiving, or using this data for model training."

5. **Magic Link (via SendGrid):**
   - **Library:** Use `sendgrid` (official Python SDK).
   - **Env Vars:** `SENDGRID_API_KEY`, `FROM_EMAIL`.
   - **Action:** Generate a JWT (signed with `SECRET_KEY`) valid for 24 hours. Send a link `https://[HOST]/auth/verify?token=[JWT]` to the user.

## 3. The Feed (Real-Time & Minimal)

### A. Interaction Design
- **Protocol:** Server-Sent Events (SSE).
- **Rate Limit:** **1 message every 5 seconds** (User-friendly "cooldown" mode).
- **Length:** Max 140 chars (Twitter classic style).
- **Hashtags:** Parse `#topic` (e.g., `#LLM`, `#PosterSession`) and make them clickable filters.

### B. URL Whitelist (Strict Regex)
Reject messages with URLs *unless* they match:
- **Google Maps:** `https?://(www\.)?google\.[a-z]+/maps.*`, `https?://maps\.app\.goo\.gl/.*`
- **ArXiv:** `https?://(www\.)?arxiv\.org/(abs|pdf)/.*`
- **OpenReview:** `https?://(www\.)?openreview\.net/.*`
- **NeurIPS:** `https?://(www\.)?neurips\.cc/.*`

## 4. Technical Specs for Agent

### Database (PostgreSQL)
- `users`: `id`, `email`, `terms_accepted_at` (timestamp), `created_at`.
- `messages`: `id`, `user_id`, `content`, `created_at`.

### File Structure Plan
- `app/main.py`: App entry point.
- `app/config.py`: Pydantic settings (`SENDGRID_API_KEY`, etc.).
- `app/services/auth.py`: JWT handling + Magic Link logic.
- `app/services/email.py`: SendGrid wrapper function.
- `app/utils/validators.py`: Domain blocklist + URL whitelist regex.
- `app/templates/index.html`: Single page HTMX app (Tailwind CSS via CDN).

### Instructions
1. Use `sendgrid` library for emails. Handle `python-http-client` exceptions gracefully.
2. Implement the "Blocklist" as a `set` for O(1) lookups in `validators.py`.
3. Use `asyncpg` for async DB access.
4. Ensure the frontend shows a "Live" indicator when connected to SSE.