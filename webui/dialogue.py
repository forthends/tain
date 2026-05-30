"""Compatibility re-exports — see streaming.py, conversation_store.py, chat.py."""
from webui.streaming import stream_chat_message, cancel_chat_message, _active_cancel_events
from webui.conversation_store import load_history as _load_conversation_history, \
    append_message as _append_to_conversation_log, cleanup_incomplete as _cleanup_incomplete_messages
from tain_agent.core.chat import ChatEngine

# Legacy alias — ACP and api_chat now use streaming/chat directly
process_chat_message = stream_chat_message
