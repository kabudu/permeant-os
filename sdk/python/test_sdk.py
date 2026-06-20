#!/usr/bin/env python3
import sys
import os
import subprocess
import time
import threading

# Add sdk/python directory to python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from permeantos import (
    AGENT_MEMORY_GRAPH_GRAPH_VERSION,
    AGENT_MEMORY_GRAPH_SCHEMA_ID,
    USXF_VERSION,
    AgentMemoryGraph,
    PermeantClient,
)

def test_memory_graph_and_metadata():
    print("Testing AgentMemoryGraph...")
    mg = AgentMemoryGraph(template_name="llama-3.1-instruct")
    
    # Attach turns
    mg.attach_agent_memory([128000, 1043, 3421, 400], "system")
    mg.attach_agent_memory([2993, 412, 1083], "user")
    mg.attach_agent_memory([890, 12, 594, 219], "assistant")
    
    chat_state = mg.to_usxf_chat_state()
    assert chat_state["template_name"] == "llama-3.1-instruct"
    assert chat_state["roles"] == ["system", "user", "assistant"]
    assert chat_state["turn_boundaries"] == [0, 4, 7, 11]
    
    header = mg.serialize_metadata_header("Llama-3.1-8B-Instruct", "7f8e9a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f")
    assert USXF_VERSION == "1.1"
    assert AGENT_MEMORY_GRAPH_GRAPH_VERSION == "0.1"
    assert AGENT_MEMORY_GRAPH_SCHEMA_ID == "https://www.permeantos.org/schemas/agent-memory-graph-v0.schema.json"
    assert header["usxf_version"] == USXF_VERSION
    assert header["seq_len"] == 11
    assert header["batch_size"] == 1
    assert len(header["block_hashes"]) == 1
    
    print("AgentMemoryGraph test: PASSED")

def main():
    test_memory_graph_and_metadata()
    print("All SDK unit tests: PASSED")

if __name__ == "__main__":
    main()
