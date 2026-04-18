def send_prompt(prompt_text, context):
    return {
        "response_text": "MOCK_RESPONSE\n\n# Example output\n- domains:\n  - Example\n- bounded_contexts:\n  - ExampleContext\n",
        "prompt_hash": context["meta"]["prompt_hash"],
        "rag_sources": context["meta"].get("rag_sources", []),
        "model": "mock"
    }

