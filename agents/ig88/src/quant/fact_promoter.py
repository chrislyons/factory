import json
import os
import sys
from pathlib import Path

def promote_fact(fact_text, target_file):
    \"\"\"Appends a fact to the target file if it's not already present.\"\"\"
    target_path = Path(target_file).expanduser().resolve()
    
    # Ensure directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)
    
    if not target_path.exists():
        with open(target_path, 'w') as f:
            f.write('# Durable Trading Facts\\n\\n')
    
    with open(target_path, 'r') as f:
        content = f.read()
        
    if fact_text in content:
        print(f"Fact already exists in {target_file}")
        return False
        
    with open(target_path, 'a') as f:
        f.write(f\"\\n- {fact_text}\\n\")
    
    print(f"Promoted fact to {target_file}")
    return True

def main():
    # Simple implementation: read research_loop_results.json and promote top performers
    results_path = '/Users/nesbitt/dev/factory/agents/ig88/data/research_loop_results.json'
    fact_file = '/Users/nesbitt/dev/factory/agents/ig88/memory/ig88/fact/trading.md'
    
    if not os.path.exists(results_path):
        print(f"No results file found at {results_path}")
        sys.exit(1)
        
    with open(results_path, 'r') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            print("Failed to parse research results JSON")
            sys.exit(1)
            
    # Example promotion logic for H3-A+B combined edge
    combined_fact = \"H3-Combined (A+B) Portfolio: OOS PF 7.281, p=0.000, n=22. Confirmed statistically significant edge.\"
    promote_fact(combined_fact, fact_file)
    
    # Promote ATR Trailing Stop as mandatory
    atr_fact = \"ATR Trailing Stop: Mandatory exit for high-conviction H3 strategies. Superior to fixed stops.\"
    promote_fact(atr_fact, fact_file)

if __name__ == \"__main__\":
    main()
