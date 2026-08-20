from dronedream_agent_core.context import ContextStore


def test_context_window_keeps_summary_and_recent_events(tmp_path):
    store = ContextStore(tmp_path / "context.sqlite3")
    try:
        for index in range(4):
            store.append(
                "conversation-1",
                role="user",
                event_type="message",
                payload={"index": index},
            )
        store.set_summary("conversation-1", "first two messages", 2)
        store.set_response_id("conversation-1", "openai", "resp_123")
        window = store.window("conversation-1", max_recent_events=10)
    finally:
        store.close()
    assert window.summary == "first two messages"
    assert [event.sequence for event in window.recent_events] == [3, 4]
    assert window.previous_response_ids == {"openai": "resp_123"}
