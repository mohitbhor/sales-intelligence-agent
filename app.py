import json
import requests
import streamlit as st

# ─────────────────────────────────────────────
# SNOWFLAKE CONFIG
# ─────────────────────────────────────────────
SNOWFLAKE_ACCOUNT = "RWUSEGY-FSB47544"
DATABASE = "SNOWFLAKE_INTELLIGENCE"
SCHEMA = "AGENTS"
AGENT_NAME = "SALES_CONVERSATION_AGENT"
ROLE = "SALES_INTELLIGENCE_ROLE"

# PAT loaded from Streamlit secrets (never hardcode tokens in source code)
import os
PAT_TOKEN = st.secrets.get("SNOWFLAKE_PAT", os.environ.get("SNOWFLAKE_PAT", ""))
if not PAT_TOKEN:
    st.error("⚠️ SNOWFLAKE_PAT not configured. Set it in `.streamlit/secrets.toml` or as an environment variable.")
    st.stop()

ACCOUNT_FOR_URL = SNOWFLAKE_ACCOUNT.replace(".", "-").lower()
AGENT_URL = (
    f"https://{ACCOUNT_FOR_URL}.snowflakecomputing.com"
    f"/api/v2/databases/{DATABASE}/schemas/{SCHEMA}/agents/{AGENT_NAME}:run"
)

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {PAT_TOKEN}",
    "Accept": "application/json",
    "X-Snowflake-Role": ROLE,
    "X-Snowflake-Account": SNOWFLAKE_ACCOUNT,
}


# ─────────────────────────────────────────────
# AGENT CALL — streaming
# ─────────────────────────────────────────────
def ask_agent_streaming(question: str, conversation_history: list = None):
    if conversation_history is None:
        conversation_history = []

    messages = conversation_history + [
        {"role": "user", "content": [{"type": "text", "text": question}]}
    ]

    stream_headers = {**HEADERS, "Accept": "text/event-stream"}

    with requests.post(
        AGENT_URL,
        headers=stream_headers,
        json={"messages": messages, "stream": True},
        stream=True,
        timeout=120
    ) as response:

        if response.status_code != 200:
            raise Exception(f"Error {response.status_code}: {response.text}")

        has_data = False
        current_event = ""
        all_events = []  # Debug: capture all event types and data
        for line in response.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8")

            # Track event type
            if decoded.startswith("event:"):
                current_event = decoded.split(":", 1)[1].strip()
                continue

            if not decoded.startswith("data:"):
                continue
            data_str = decoded[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                event = json.loads(data_str)
                all_events.append({"event_type": current_event, "data_keys": list(event.keys()), "data": str(event)[:200]})

                # Try to extract text from ANY event that has a "text" field
                text = event.get("text", "")
                if text and current_event not in ("response.thinking.delta", "response.status"):
                    has_data = True
                    yield text

                # Fallback: delta/content format
                for block in event.get("delta", {}).get("content", []):
                    if block.get("type") == "text":
                        has_data = True
                        yield block.get("text", "")

            except json.JSONDecodeError:
                continue

        if not has_data:
            # Show all captured event types for debugging
            unique_events = list({e["event_type"] for e in all_events})
            sample = json.dumps(all_events[:5], indent=2)
            yield f"⚠️ No text content found.\n\n**Event types seen:** {unique_events}\n\n**Sample events:**\n```json\n{sample}\n```"

        if not has_data:
            yield "⚠️ No response received from the agent. Please check your Snowflake agent configuration and PAT token."


# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Sales Intelligence Agent",
    page_icon="💼",
    layout="centered"
)

st.markdown("""
<style>
    .chat-header {
        background: linear-gradient(135deg, #1a73e8, #0d47a1);
        padding: 20px; border-radius: 12px;
        color: white; text-align: center; margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="chat-header">
    <h2>💼 Sales Intelligence Agent</h2>
    <p>Ask anything about your sales data</p>
</div>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# EXAMPLE QUESTIONS
# ─────────────────────────────────────────────
with st.expander("💡 Example questions"):
    examples = [
        "How many deals did Sarah Johnson win vs lose?",
        "What is the total revenue this quarter?",
        "Which sales rep has the highest win rate?",
        "Show me deals closed last month",
        "What is the average deal size by region?",
    ]
    for ex in examples:
        if st.button(ex, key=ex):
            st.session_state["prefill"] = ex


# ─────────────────────────────────────────────
# SESSION STATE
# ─────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent_history" not in st.session_state:
    st.session_state.agent_history = []


# ─────────────────────────────────────────────
# DISPLAY CHAT HISTORY
# ─────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑" if msg["role"] == "user" else "💼"):
        st.markdown(msg["content"])


# ─────────────────────────────────────────────
# CHAT INPUT
# ─────────────────────────────────────────────
prefill = st.session_state.pop("prefill", "")
user_input = st.chat_input("Ask about your sales data...") or prefill

if user_input:
    # Show user message
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(user_input)

    # Stream agent response
    with st.chat_message("assistant", avatar="💼"):
        placeholder = st.empty()
        full_response = ""

        try:
            for chunk in ask_agent_streaming(
                user_input,
                st.session_state.agent_history
            ):
                full_response += chunk
                placeholder.markdown(full_response + "▌")
            placeholder.markdown(full_response)

        except Exception as e:
            full_response = f"❌ {str(e)}"
            placeholder.error(full_response)
            st.error(f"Debug info — URL: {AGENT_URL}")

    # Save to history
    st.session_state.messages.append({"role": "assistant", "content": full_response})
    st.session_state.agent_history.append({
        "role": "user",
        "content": [{"type": "text", "text": user_input}]
    })
    st.session_state.agent_history.append({
        "role": "assistant",
        "content": [{"type": "text", "text": full_response}]
    })


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 💼 Sales Intelligence")
    st.markdown("---")
    st.caption(f"Agent: {AGENT_NAME}")
    st.caption(f"Role: {ROLE}")
    st.markdown("---")
    if st.button("🗑️ Clear conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.agent_history = []
        st.rerun()
    st.markdown("---")
    st.caption("Powered by Snowflake Cortex")

