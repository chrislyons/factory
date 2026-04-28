#!/usr/bin/env python3
"""
Quality comparison: Qwen3.5-2B vs Qwen3.5-4B Claude Opus Distill
Tests reasoning, instruction following, tool calling awareness, and escalation judgment.
"""
import sys, gc, json, time
import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import stream_generate

MODELS = {
    "2B": "/Users/nesbitt/models/Qwen3.5-2B-6bit",
    "4B-distill": "/Users/nesbitt/models/MLX-Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled-v2-6bit",
}

TESTS = [
    {
        "name": "simple_task",
        "desc": "Should handle directly, no escalation needed",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Respond concisely."},
            {"role": "user", "content": "What is the capital of France?"}
        ],
        "expect": "Direct answer: Paris"
    },
    {
        "name": "math_reasoning",
        "desc": "Multi-step math — tests raw reasoning ability",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Think step by step."},
            {"role": "user", "content": "A model uses 3.42 GB of memory for weights. Its KV cache grows at 32 KB per token. If it has 21 GB available and needs to keep 5 GB for overhead, what is the maximum context length in tokens? Show your work."}
        ],
        "expect": "21 - 5 - 3.42 = 12.58 GB. 12.58 GB / 32 KB = ~402,944 tokens"
    },
    {
        "name": "instruction_following",
        "desc": "Structured output — tests instruction compliance",
        "messages": [
            {"role": "system", "content": "Respond with exactly 3 bullet points. No more, no less."},
            {"role": "user", "content": "List 3 benefits of KV cache quantization for LLM inference."}
        ],
        "expect": "Exactly 3 bullet points"
    },
    {
        "name": "code_reasoning",
        "desc": "Code analysis — tests technical understanding",
        "messages": [
            {"role": "system", "content": "You are a technical assistant."},
            {"role": "user", "content": "What does this Python one-liner do?\n\nresult = [x for x in range(100) if all(x % i != 0 for i in range(2, int(x**0.5) + 1)) and x > 1]"}
        ],
        "expect": "Identifies it as a prime number sieve generating primes up to 99"
    },
    {
        "name": "summarization",
        "desc": "Compress long context — tests aux-quality for compression role",
        "messages": [
            {"role": "system", "content": "Summarize the following in 2 sentences."},
            {"role": "user", "content": "The flash-moe C/Metal inference engine was ported from its original Qwen3.5-397B-A17B target to DJLougen's Ornstein3.6-35B-A3B-MLX-6bit fine-tune. Five bugs were found and fixed: wrong expert count (4 vs 8), missing think token in chat template, GPU 8-bit dequant kernel corrupting routing scores, missing bits=8 field in BatchMatvecSpec, and wrong prompt tokenization. The model now runs at 7.2 tok/s on Whitebox (Mac Studio M1 Max, 32GB) with coherent reasoning output. The main bottleneck is SSD expert I/O at 47% of time and 6-bit dequant compute at 22%."}
        ],
        "expect": "Concise 2-sentence summary"
    },
    {
        "name": "escalation_decision",
        "desc": "Complex reasoning — should recognize this needs deep thinking",
        "messages": [
            {"role": "system", "content": "You are a fast assistant. For simple tasks, respond directly. For complex analysis requiring deep reasoning, say ESCALATE and explain why."},
            {"role": "user", "content": "Analyze the tradeoffs between running two small inference models versus one large model with speculative decoding on a 32GB unified memory system with SSD-backed expert streaming. Consider latency, throughput, memory pressure, and model quality."}
        ],
        "expect": "Should ESCALATE"
    },
    {
        "name": "tool_call_recognition",
        "desc": "Should recognize this needs a tool, not a text response",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. When a user asks you to perform an action that requires running code or accessing system resources, respond with a JSON tool call like: {\"tool\": \"run_command\", \"args\": {\"command\": \"...\"}}"},
            {"role": "user", "content": "Check if the flash-moe process is running on this machine."}
        ],
        "expect": "JSON tool call with ps/pgrep command"
    },
    {
        "name": "context_understanding",
        "desc": "Multi-turn conversation — tests context tracking",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "I have a Mac Studio M1 Max with 32GB RAM. I'm running a 35B MoE model that uses 3GB resident memory and streams expert weights from SSD."},
            {"role": "assistant", "content": "Understood. You have 32GB unified memory with a 35B MoE model using 3GB resident. That leaves about 29GB available."},
            {"role": "user", "content": "I want to add a 2B model alongside it. The 2B uses 1.5GB and its KV cache grows at 12KB per token. Can I get 256K context on both?"}
        ],
        "expect": "Should calculate: 2B at 256K = 1.5 + 3.1 KV + overhead ≈ 7GB. 35B = 6GB. Total ≈ 18GB. Yes, fits."
    },
]


def run_test(model, tokenizer, test, max_tokens=300):
    """Run a single test and return the response."""
    gc.collect()
    mx.metal.clear_cache()

    messages = test["messages"]
    try:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False,
                                                add_generation_prompt=True,
                                                enable_thinking=False)
    except TypeError:
        prompt = tokenizer.apply_chat_template(messages, tokenize=False,
                                                add_generation_prompt=True)
    
    tokens = tokenizer.encode(prompt, add_special_tokens=False)
    
    t0 = time.perf_counter()
    response_text = ""
    last_resp = None
    for resp in stream_generate(model, tokenizer, tokens, max_tokens=max_tokens):
        response_text += resp.text
        last_resp = resp
    elapsed = time.perf_counter() - t0
    
    tps = last_resp.generation_tps if last_resp else 0
    return response_text, elapsed, tps


def main():
    all_results = {}
    
    for model_name, model_path in MODELS.items():
        print(f"\n{'='*60}")
        print(f"Loading {model_name}: {model_path}")
        print(f"{'='*60}")
        model, tokenizer = load(model_path)
        
        all_results[model_name] = []
        
        for test in TESTS:
            print(f"\n--- {test['name']}: {test['desc']} ---")
            print(f"  Expected: {test['expect']}")
            sys.stdout.flush()
            
            try:
                response, elapsed, tps = run_test(model, tokenizer, test)
                all_results[model_name].append({
                    "name": test["name"],
                    "desc": test["desc"],
                    "expect": test["expect"],
                    "response": response.strip(),
                    "elapsed_s": round(elapsed, 1),
                    "tps": round(tps, 1),
                })
                display = response.strip()[:600]
                if len(response.strip()) > 600:
                    display += "..."
                print(f"  [{elapsed:.1f}s, {tps:.1f} tok/s]")
                print(f"  Response: {display}")
            except Exception as e:
                print(f"  FAILED: {e}")
                all_results[model_name].append({
                    "name": test["name"],
                    "error": str(e)
                })
            sys.stdout.flush()
        
        del model, tokenizer
        gc.collect()
        mx.metal.clear_cache()
    
    out_path = "/tmp/quality_comparison_2b_vs_4b.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\n\nResults saved to {out_path}")
    print("Review responses side-by-side to assess quality differences.")


if __name__ == "__main__":
    main()
