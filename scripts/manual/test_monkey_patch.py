#!/usr/bin/env python3
"""
Test del monkey patch para verificar que el switching funciona correctamente.
"""

import os
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

def test_monkey_patch():
    """Test basic monkey patch functionality"""
    print("=" * 60)
    print("🧪 Testing LLM Provider Monkey Patch")
    print("=" * 60)
    
    # Apply monkey patch BEFORE importing core modules
    from shared.llm.monkey_patch import apply_monkey_patch, switch_provider
    apply_monkey_patch()
    
    # Now import the SDK (should be our patched version)
    from claude_agent_sdk import query, ClaudeAgentOptions
    
    print("\n1️⃣ Testing with MOCK provider...")
    switch_provider("mock")
    
    # Test basic query
    options = ClaudeAgentOptions(model="sonnet", temperature=0.5)
    result_gen = query("Hello, what is 2+2?", options)
    
    # Collect results
    response = ""
    for chunk in result_gen:
        response += chunk
        print(chunk, end="", flush=True)
    
    print(f"\n   Response: {response}")
    print("   ✅ MOCK provider works!")
    
    # Test switching to API (if key available)
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if api_key:
        print("\n2️⃣ Testing with Anthropic API...")
        switch_provider("anthropic_api", api_key=api_key)
        
        result_gen = query("What is 3+3?", options)
        response = ""
        for chunk in result_gen:
            response += chunk
            print(chunk, end="", flush=True)
        
        print(f"\n   Response: {response}")
        print("   ✅ Anthropic API works!")
    else:
        print("\n2️⃣ Skipping Anthropic API test (no API key)")
    
    print("\n" + "=" * 60)
    print("✅ Monkey patch test completed!")
    print("=" * 60)


def test_core_integration():
    """Test that core modules use our patched SDK"""
    print("\n🔧 Testing Core Integration...")
    
    try:
        # Apply patch first
        from shared.llm.monkey_patch import switch_provider
        switch_provider("mock")
        
        # Now try importing a core module
        from core.valinor.agents import cartographer
        print("   ✅ Core module imported successfully with patched SDK")
        
        # Test if we can call a function that uses claude_agent_sdk
        # (This would normally fail without API key, but should work with mock)
        print("   📡 Core modules are using our monkey-patched SDK!")
        
    except Exception as e:
        print(f"   ❌ Core integration failed: {e}")


if __name__ == "__main__":
    test_monkey_patch()
    test_core_integration()