# RemitAgent Pool Expansion Guide

## Summary

I've expanded your RemitAgent to support additional profitable pools while keeping your existing working configuration intact.

## What Was Added

### 1. New Trading Pairs (in default config)

Your agent now monitors these additional pairs:

| Pair | Type | Why It's Profitable |
|------|------|---------------------|
| `cEUR-cCOP` | Composite | Euro to Colombian Peso corridor |
| `cEUR-cNGN` | Composite | Euro to Nigerian Naira corridor |
| `cKES-cCOP` | Composite | Cross-emerging market arbitrage |
| `cUSD-axlUSDC` | Cross-DEX | Mento vs Curve arbitrage |

**Full default pair list:**
```
cUSD-cEUR, cUSD-cKES, cUSD-cCOP, cUSD-cNGN, cUSD-cREAL, 
cEUR-cKES, cEUR-cCOP, cEUR-cNGN, cKES-cCOP, cUSD-axlUSDC
```

### 2. New Token Support

Added support for future expansion:

| Token | Type | Address |
|-------|------|---------|
| `USDm` | Mento v2 | 0xcebA9300f2b948710d2653dD7B07f33A8B32118C |
| `EURm` | Mento v2 | 0xE4F356EcBe573F492ED73b061c8C8ec846F0972d |
| `axlUSDC` | Bridged | 0xEB466342C4d449BC9f53A865D5Cb90586f405215 |

### 3. Enhanced DEX Support

Updated Uniswap V3 pool addresses:
- `cUSD-cEUR-0.05%` - Main arbitrage pool (verified)
- `cUSD-CELO-0.3%` - High liquidity CELO pool
- `cEUR-CELO-0.3%` - cEUR/CELO pool
- `cUSD-CELO-0.05%` - Low fee CELO pool

Added Curve Finance addresses for future integration.

## Should You Add More Pools?

### My Recommendation: **Start With Current Setup**

Your current configuration is well-balanced:

✅ **Pros of current setup:**
- Covers major African remittance corridors (KES, NGN)
- Includes South American corridor (COP)
- Cross-rate arbitrage (cEUR-cKES, etc.)
- Stablecoin arbitrage (cUSD-axlUSDC)
- 10 pairs is manageable for a single agent

⚠️ **Considerations before adding more:**
- More pairs = more API calls = higher latency
- Lower liquidity pairs may have higher slippage
- Mento spread is fixed (~0.5%), so opportunities depend on fiat rate volatility

### When to Expand Further

Add more pairs if:
1. **You're seeing consistent profits** with current pairs
2. **You have higher capital** to trade larger sizes
3. **You want geographic expansion** (add GHS, XOF, PHP, etc.)

### Suggested Future Additions (if needed)

If you want to expand later, these are good candidates:

```env
# African expansion
TARGET_PAIRS=cUSD-cEUR,cUSD-cKES,cUSD-cNGN,cUSD-GHS,cUSD-XOF,cEUR-cKES,cEUR-cNGN

# South American focus
TARGET_PAIRS=cUSD-cEUR,cUSD-cCOP,cUSD-cREAL,cUSD-MXN,cEUR-cCOP

# Asian corridors
TARGET_PAIRS=cUSD-cEUR,cUSD-PHP,cUSD-IDR,cUSD-VND

# Maximalist (all supported)
TARGET_PAIRS=cUSD-cEUR,cUSD-cKES,cUSD-cCOP,cUSD-cNGN,cUSD-cREAL,cUSD-GHS,cUSD-XOF,cUSD-PHP,cUSD-JPY,cEUR-cKES,cEUR-cCOP,cEUR-cNGN,cKES-cCOP,cUSD-axlUSDC
```

## Updated Token Support

The FX Oracle now supports:

| Token | Fiat | Use Case |
|-------|------|----------|
| cUSD, USDm, axlUSDC | USD | Base currency |
| cEUR, EURm | EUR | European corridor |
| cKES, KESm | KES | Kenyan corridor |
| cCOP, COPm | COP | Colombian corridor |
| cNGN, NGNm | NGN | Nigerian corridor |
| cREAL, BRLm | BRL | Brazilian corridor |
| GHSm | GHS | Ghanaian corridor (new) |
| XOFm | XOF | West African CFA (new) |
| ZARm | ZAR | South African Rand (new) |
| AUDm | AUD | Australian Dollar (new) |
| CHFm | CHF | Swiss Franc (new) |
| CADm | CAD | Canadian Dollar (new) |
| PHPm | PHP | Philippine Peso (new) |
| JPYm | JPY | Japanese Yen (new) |
| CELO | USD | Native token pricing |

## Migration Path: c-Tokens to m-Tokens

Mento is migrating from `cUSD/cEUR` to `USDm/EURm`. Your agent supports both.

**Current status:**
- Your `cUSD/cEUR` pairs work fine now
- Mento may reduce liquidity in c-tokens over time
- Agent is ready for m-tokens when you want to switch

**To migrate in the future:**
1. Update your `.env` pairs to use `USDm`, `EURm`, etc.
2. The FX Oracle already supports them
3. No code changes needed

## Testing Your Expanded Setup

```bash
# Test with new pairs
python main.py --mode single --pair cUSD-axlUSDC --amount 100

# Test with cross-pair
python main.py --mode single --pair cEUR-cCOP --amount 100

# Start monitoring with all pairs
python main.py --mode monitor
```

## Monitoring Recommendations

With more pairs, you'll get more notifications. The agent has rate limiting:
- Max 5 messages per minute
- Digest mode for many opportunities
- Important trades always sent immediately

To adjust notification frequency, modify in `src/notifications/telegram_bot.py`:
```python
self._max_messages = 5  # Increase if you want more frequent updates
```

## Capital Allocation Advice

With 10 pairs, consider:
- **Max trade size:** $100-500 per pair (set in `.env`)
- **Total exposure:** Don't exceed 50% of capital simultaneously
- **Slippage:** Larger trades on exotic pairs (cKES, cNGN) may have higher slippage

Example `.env` settings:
```env
MAX_TRADE_SIZE_USD=500  # Max per trade
SLIPPAGE_PROTECTION=0.5  # 0.5% max slippage
MIN_LIQUIDITY_DEPTH=10000  # $10k minimum pool
```

## Final Verdict

**Keep your current setup.** The 10 default pairs provide:
- Good geographic coverage
- Sufficient trading opportunities
- Manageable API load
- Diversified risk

**Add more pairs only if:**
1. You're consistently profitable
2. You want to specialize in a region
3. You have specific market knowledge

The agent is now future-proofed with support for 15+ currencies and multiple DEXs.
