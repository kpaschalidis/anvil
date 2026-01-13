#!/usr/bin/env bash
#
# Scout Agent - Example Commands
#
# Make executable: chmod +x examples/scout_examples.sh
# Run: ./examples/scout_examples.sh

set -e

echo "🔍 Scout Agent - Example Usage"
echo "=============================="
echo ""

# Check if API key is set
if [ -z "$OPENAI_API_KEY" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ Error: No LLM API key found"
    echo ""
    echo "Please set one of:"
    echo "  export OPENAI_API_KEY='sk-...'"
    echo "  export ANTHROPIC_API_KEY='sk-ant-...'"
    echo ""
    echo "Or copy .env.example to .env and fill in your keys"
    exit 1
fi

echo "✅ API key detected"
echo ""

# Function to run example
run_example() {
    local num=$1
    local desc=$2
    shift 2
    local cmd="$@"
    
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Example $num: $desc"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Command:"
    echo "  $cmd"
    echo ""
    read -p "Run this example? [y/N] " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        eval "$cmd"
        echo ""
        echo "✅ Example $num completed"
    else
        echo "⏭️  Skipped"
    fi
    echo ""
}

# Example 1: Quick validation
run_example 1 \
    "Quick Research (5-10 min, ~\$0.10)" \
    "uv run scout run 'CRM software pain points' --profile quick"

# Example 2: Standard research
run_example 2 \
    "Standard Research (15-30 min, ~\$0.50)" \
    "uv run scout run 'project management tools' --profile standard --max-cost 1.0"

# Example 3: List sessions
run_example 3 \
    "List All Sessions" \
    "uv run scout list"

# Example 4: View stats
if uv run scout list | grep -q "completed"; then
    SESSION_ID=$(uv run scout list | grep "completed" | head -1 | awk '{print $1}')
    run_example 4 \
        "View Session Statistics" \
        "uv run scout stats $SESSION_ID"
    
    # Example 5: Export data
    run_example 5 \
        "Export to CSV" \
        "uv run scout export $SESSION_ID --format csv --output /tmp/scout_export.csv && cat /tmp/scout_export.csv | head -20"
else
    echo "ℹ️  Examples 4-5 require a completed session. Run Examples 1 or 2 first."
fi

# Example 6: Watch live (if there's a running session)
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Example 6: Watch Live Progress"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "To watch a session live, open two terminals:"
echo ""
echo "  Terminal 1: uv run scout run 'your topic' --profile standard"
echo "  Terminal 2: uv run scout watch <session_id> --stream snippets"
echo ""

# Example 7: Advanced features
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Example 7: Advanced Features"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Session tagging:"
echo "  uv run scout tag <session_id> 'tag1' 'tag2'"
echo ""
echo "Clone a session:"
echo "  uv run scout clone <session_id> --topic 'new related topic'"
echo ""
echo "Archive old sessions:"
echo "  uv run scout archive --days 30"
echo ""
echo "Use improved extraction prompt:"
echo "  uv run scout run 'topic' --extraction-prompt v2"
echo ""
echo "Custom limits:"
echo "  uv run scout run 'topic' --max-iterations 40 --max-documents 100"
echo ""
echo "JSON logging:"
echo "  uv run scout run 'topic' --log-format json > research.log"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✨ Examples complete!"
echo ""
echo "📚 For more information:"
echo "  - Read: SCOUT_QUICKSTART.md"
echo "  - Help: uv run scout --help"
echo "  - Docs: src/scout/README.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
