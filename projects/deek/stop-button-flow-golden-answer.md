# DEEK Stop Button Flow

The stop button starts in [D:\deek\web\src\components\ChatWindow.tsx](D:/deek/web/src/components/ChatWindow.tsx), where `stopGeneration()` sends a POST request to `/api/chat/stop`, closes the active `EventSource`, aborts any active `fetch()` controller, and clears the live draft/activity state in the browser.

That browser request goes through the Next.js proxy route at [D:\deek\web\src\app\api\chat\stop\route.ts](D:/deek/web/src/app/api/chat/stop/route.ts), which forwards the stop request to the FastAPI backend endpoint `POST /chat/stop`.

On the backend, [D:\deek\api\main.py](D:/deek/api/main.py) handles `POST /chat/stop` and calls `agent.request_stop(session_id)`.

Cooperative stopping happens inside [D:\deek\core\agent.py](D:/deek/core/agent.py). `request_stop()` records the session in `_stop_requests`, `_check_stop()` raises `GenerationStopped` for that session, and `_check_request_active()` calls `_check_stop()` at key checkpoints in the request/tool loop so the in-flight request exits cleanly instead of hanging.
