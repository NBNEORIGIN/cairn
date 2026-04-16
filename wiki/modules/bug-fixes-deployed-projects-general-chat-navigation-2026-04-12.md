# Bug Fixes Deployed - Projects + General Chat + Navigation (2026-04-12)

**Summary:** Three critical bugs have been fixed in Deek's production environment. The project dropdown now correctly loads all 14 projects, chat functionality works immediately without requiring project selection (via a new "General" mode), and Amazon/Etsy/Social tools are now accessible through a new navigation bar and quick-action buttons. A proxy route fix also resolved Docker networking issues affecting the Social page.

## Fixed Issues

### 1. Project Dropdown Now Loads Correctly

**Root Cause:** Environment variable mismatch between `docker-compose.yml` (which set `DEEK_API_URL`) and route handlers (which read `CLAW_API_URL`). The web container silently fell back to `http://localhost:8765`, unreachable from inside Docker. Additionally, Next.js inlines `process.env.*` at build time, requiring environment variables during the Docker build stage.

**Resolution:** Both `CLAW_API_URL` and `DEEK_API_URL` are now set in `docker-compose.yml` and the Dockerfile builder stage.

**Result:** The project dropdown displays all 14 projects:
- amazon-intelligence
- ark
- deek
- crm
- etsy-intelligence
- general
- ledger
- manufacturing
- memorials
- nbne
- phloe
- proving-ground
- render
- studio

### 2. General Chat Mode (No Project Required)

**Previous Behavior:** Chat was blocked until a project was selected. The textarea and Send button were disabled with a "Select a project first" message.

**New Behavior:** 
- A "General" option appears first in the project dropdown and is selected by default
- Chat input is always enabled on page load
- The backend creates a lightweight agent with full tool access including:
  - Memory
  - Wiki
  - CRM
  - Analyzer
  - Amazon Intelligence
  - Email Search
- **No codebase retrieval** in General mode (only available when a specific project is selected)

**Verification:** End-to-end tested with the query "What tools do you have?" which returned a complete DeepSeek response listing all available tools.

### 3. Amazon/Etsy/Social Tools Now Accessible

Three improvements were deployed:

**Navigation Bar:**
- New persistent navigation at the top of every page: **Chat** / **Social** / **Status**
- Uses Lucide icons with active state highlighting
- Click freely between pages

**Quick-Action Buttons:**
- Five buttons appear above the chat input when starting a fresh conversation:
  - **Amazon Sales**
  - **Etsy Analytics**
  - **Analyse Enquiry**
  - **Email Triage**
  - **Social Draft**
- Each button pre-fills the input with a prompt template
- Review and edit the prompt before sending

**Social Page Fix:**
- Previous hardcoded `http://localhost:8765` references broke in Docker
- New catch-all proxy route `/api/social/[...path]` forwards requests to the backend
- Social drafting interface now works correctly in production

## Testing Checklist

To verify the fixes are working correctly:

1. Visit [https://deek.nbnesigns.co.uk](https://deek.nbnesigns.co.uk)
2. Confirm the navigation bar (Chat / Social / Status) appears at the top
3. Check the project dropdown shows "General" plus all 14 projects
4. Type a test message and send—you should receive a response in General mode
5. Select a specific project (e.g. "deek")—project-specific skills should appear
6. Click "Social" in the navigation bar—the drafting interface should load
7. Return to Chat and test the quick-action buttons

## Known Issues

> **⚠️ WARNING:** The Status page still displays "API offline" due to its own hardcoded localhost reference. This affects developer diagnostics only and is lower priority. A fix is scheduled for the next development session.

## Related Commits

- `072688f` - fix(web): env var mismatch + project-less chat + nav bar + social proxy
- `4627e6b` - fix(web): set CLAW_API_URL at Docker build time
- `77be55c` - feat(general): standalone project for project-less chat
- `e980d00` - fix(web): dedupe general in project dropdown

## Related Topics

- **Docker Environment Configuration** - Understanding environment variable handling in Next.js containers
- **Deek Agent Architecture** - How General mode differs from project-specific agents
- **Social Media Tools** - Using the Social page for content drafting
- **Quick Actions Reference** - Complete list of available prompt templates