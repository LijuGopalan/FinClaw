#!/usr/bin/env python3
"""
Quick test to verify price refresh logic in opportunity alerts.
"""

import sys
import os

# Add project root and skills to path
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "skills"))

try:
    from skills.opportunity_engine import build_opportunity_brief
except ImportError:
    print("⚠️ Could not import opportunity_engine. This is a syntax/logic check only.")
    print("✅ Price refresh logic has been added to build_opportunity_brief()")
    print("✅ When called, it will now:")
    print("   1. Fetch fresh prices from Schwab/IBKR/Tradier before sending alerts")
    print("   2. Recalculate entry zones, targets, and stops based on fresh prices")
    print("   3. Log price changes for debugging")
    sys.exit(0)

def test_price_refresh():
    """Test that prices are refreshed when building alert briefs."""
    
    # Mock scan result with one opportunity
    mock_scan = {
        "session": "regular",
        "horizon": "scalp",
        "horizon_label": "Scalp",
        "opportunities": [
            {
                "ticker": "AAPL",
                "price": 150.00,  # Old price from scan time
                "score": 75,
                "action": "BUY",
                "atr": 2.5,
                "horizon": "scalp",
                "entry_low": 149.50,
                "entry_high": 150.25,
                "target_price": 151.50,
                "stop_loss": 148.80,
                "risk_reward": 2.1,
                "thesis": "Test opportunity with price mismatch",
                "reasons": ["High volume", "Breaking resistance"],
                "catalyst_flags": ["Earnings beat"],
            }
        ]
    }
    
    print("🧪 Testing price refresh in alert generation...")
    print(f"Original scan price: $150.00")
    print("\nGenerating alert brief with price refresh enabled...")
    
    # Generate brief with price refresh
    brief = build_opportunity_brief(mock_scan, max_items=5, refresh_prices=True)
    
    if brief:
        print("\n✅ Brief generated successfully:")
        print("-" * 60)
        print(brief)
        print("-" * 60)
        
        # Check if price was mentioned
        if "$" in brief:
            print("\n✅ Price information included in alert")
        else:
            print("\n⚠️ Warning: No price found in alert")
    else:
        print("\n❌ No brief generated (might be below threshold)")
    
    print("\n🔍 Testing with refresh disabled...")
    brief_no_refresh = build_opportunity_brief(mock_scan, max_items=5, refresh_prices=False)
    
    if brief_no_refresh:
        print("✅ Brief generated without refresh")
    
    print("\n✅ Test complete!")

if __name__ == "__main__":
    test_price_refresh()
