# P3 — Web Chat Cancellation Support

**Target:** v0.4.4
**Source:** [design doc, gap #5](../design/v0-4-2-design.md#5-web-chat-执行取消支持--tain-缺失)

## Current State

`process_chat_message()` can run up to 5 tool-execution turns × up to 5 minutes each = up to ~5 minutes with no response. User has no way to cancel. Frontend only has a send button.

## Reference (Mini-Agent)

- `cancel_event: asyncio.Event` on agent object
- `_check_cancelled()` called before each step and after each tool
- `_cleanup_incomplete_messages()` removes orphan tool_use/tool_result pairs
- CLI: independent thread listens for Esc key

## Implementation

### New route: `POST /api/agent/{name}/chat/cancel`

```
Query params: message_id
→ finds active cancel_event by message_id
→ sets event
→ returns {"cancelled": true}
```

### Modified: `webui/dialogue.py`

- `process_chat_message()` accepts optional `cancel_event: asyncio.Event`
- Check `cancel_event.is_set()` at start of each turn loop iteration
- After cancel: call `_cleanup_incomplete_messages()` to remove orphan pairs
- Active cancel events stored in module-level dict keyed by `message_id`

### Modified: API route handler

- Generates `message_id` before streaming, registers `cancel_event`
- Removes event on completion or cancel

### Modified: `webui/templates/agent_tabs/chat.html`

- Send button transforms to "Stop" button while `streaming` is true
- Stop button calls `POST /api/agent/{name}/chat/cancel?message_id=...`
- On stop: set `streaming = false`, flush any partial text as message

### Modified: `agent_detail.html` — chatApp

```javascript
// New field
cancelMessageId: null,

async stopGeneration() {
    if (this.cancelMessageId) {
        await fetch(`/api/agent/${agentName}/chat/cancel?message_id=${this.cancelMessageId}`, {method: 'POST'});
    }
    this.streaming = false;
    // flush partial text
},
```

## Verification

- Send long chat message, click stop before response completes
- Confirm no orphan tool_use/tool_result in conversation history
- Confirm next message succeeds without API errors
- Confirm partial text is saved as message
- Stop button reverts to send button after cancellation
