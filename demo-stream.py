import streamlit as st
from langchain_ollama import ChatOllama

st.title("🦙 Ollama Stream with Token Usage")

@st.cache_resource
def load_model():
    # langchain_ollama automatically handles stream_usage internally
    return ChatOllama(model="llama3.2:latest", temperature=0.7)

model = load_model()
user_query = st.text_input("Ask anything:", placeholder="Type your message...")

if user_query:
    with st.chat_message("assistant"):
        # We need a container to display text and a dictionary to capture metadata
        text_placeholder = st.empty()
        usage_holder = {}
        
        def stream_generator():
            full_content = ""
            for chunk in model.stream(user_query):
                # 1. Yield text content for st.write_stream if it exists
                if chunk.content:
                    full_content += chunk.content
                    yield chunk.content
                
                # 2. Capture the usage metadata when the final chunk arrives
                if getattr(chunk, "usage_metadata", None):
                    usage_holder["metadata"] = chunk.usage_metadata

        # stream_generator handles text rendering automatically
        st.write_stream(stream_generator())
        
        # 3. Safely display token stats after the stream completes
        if "metadata" in usage_holder and usage_holder["metadata"]:
            meta = usage_holder["metadata"]
            st.caption(
                f"📊 **Tokens used:** "
                f"Input: {meta.get('input_tokens', 0)} | "
                f"Output: {meta.get('output_tokens', 0)} | "
                f"Total: {meta.get('total_tokens', 0)}"
            )
