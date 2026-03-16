# RemitAgent 🌍💸

An autonomous agent that monitors remittance corridors on Celo, detects optimal swap rates between DEX liquidity and Mento FPMM rates, and executes trades when spreads exceed user-defined thresholds. Features Telegram remote control for emergency stops and real-time notifications.

## 🎯 Why This Wins

- **Unique to Celo**: Mento FPMMs provide real-world FX rates on-chain (0.05-0.3% cost vs 3-7% traditional)
- **Real utility**: Addresses $4B annual remittance fee loss in Africa
- **Technical showcase**: Combines subgraphs, oracles, DEX aggregation, and agent autonomy
- **Remote Control**: Stop the agent from anywhere via Telegram commands

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    RemitAgent Core                          │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │   Subgraph   │  │    Mento     │  │      0x API      │  │
│  │   Client     │  │   Client     │  │     Client       │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  FX Oracle   │  │ Risk Manager │  │    Executor      │  │
│  │(Frankfurter) │  │              │  │   (with nonce    │  │
│  │              │  │              │  │    locking)      │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│  Telegram Bot (Remote Control)  │  FastAPI Dashboard        │
└─────────────────────────────────────────────────────────────┘
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repo-url>
cd remitagent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your values:

```env
# Required
CELO_RPC_URL=https://forno.celo.org
CELO_PRIVATE_KEY=your_private_key
CELO_WALLET_ADDRESS=your_wallet_address

# Telegram Notifications & Remote Control
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_numeric_chat_id

# Agent Settings
MIN_SPREAD_THRESHOLD=0.5
CHECK_INTERVAL_SECONDS=300
TARGET_PAIRS=cUSD-cEUR,cUSD-cKES,cEUR-cKES
```

**Get Telegram credentials:**
- Bot Token: Message [@BotFather](https://t.me/BotFather) and create a new bot
- Chat ID: Message [@userinfobot](https://t.me/userinfobot) to get your numeric ID

### 3. Test Telegram Setup

```bash
python test_telegram.py
```

This verifies your bot can receive notifications and respond to commands.

### 4. Run the Agent

```bash
# Start autonomous monitoring
python main.py --mode monitor

# Run single check
python main.py --mode single --pair cUSD-cEUR --amount 100

# Run backtest
python main.py --mode backtest --days 7

# Start dashboard
python main.py --mode dashboard --port 8000
```

## 🤖 Telegram Remote Control

Once the agent is running, control it remotely via Telegram:

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with available commands |
| `/help` | Show all commands |
| `/status` | Check agent status and statistics |
| `/stats` | View trading statistics |
| `/stop` | **Emergency stop - Stops the agent immediately** |
| `/emergency` | Same as `/stop` |

### Emergency Stop Example

If you see the agent making bad trades:

1. Open Telegram on your phone
2. Find your bot chat
3. Send: `/stop`
4. Agent stops immediately and sends confirmation

See [TELEGRAM_REMOTE_CONTROL.md](TELEGRAM_REMOTE_CONTROL.md) for detailed setup and troubleshooting.

## 📊 Supported Trading Pairs

### Default Pairs (3)
- `cUSD-cEUR` - USD to Euro
- `cUSD-cKES` - USD to Kenyan Shilling  
- `cEUR-cKES` - Euro to Kenyan Shilling

### Expanded Pairs (10)
For more opportunities, add these pairs to your `.env`:
```env
TARGET_PAIRS=cUSD-cEUR,cUSD-cKES,cUSD-cCOP,cUSD-cNGN,cUSD-cREAL,cEUR-cKES,cEUR-cCOP,cEUR-cNGN,cKES-cCOP,cUSD-axlUSDC
```

Includes:
- African corridors: KES (Kenya), NGN (Nigeria)
- South American: COP (Colombia), BRL (Brazil)
- Cross-DEX arbitrage: cUSD-axlUSDC (Mento vs Curve)

See [POOL_EXPANSION_GUIDE.md](POOL_EXPANSION_GUIDE.md) for recommendations on expanding pairs.

## 📊 API Endpoints

When running in dashboard mode:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Current agent status |
| `/opportunities` | GET | Recent opportunities |
| `/trades` | GET | Trade history |
| `/pairs` | GET | Supported pairs with rates |
| `/simulate` | POST | Dry-run trade calculation |
| `/health` | GET | Health check |

## 🛡️ Safety Features

- **Slippage Protection**: Max 0.5% slippage on any trade
- **Trade Size Limit**: Max $1,000 per trade (configurable)
- **Liquidity Check**: Minimum $10,000 pool TVL
- **Cooldown Period**: 15 minutes between trades on same pair
- **Emergency Stop**: Telegram command or touch file to halt
- **Gas Price Check**: Ensure reasonable gas costs
- **Remote Control**: Stop the agent from anywhere via Telegram

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_opportunities.py -v

# Test Telegram setup
python test_telegram.py
```

## 🔧 Project Structure

```
remitagent/
├── .env.example              # Environment template
├── requirements.txt          # Python dependencies
├── config.py                 # Configuration loader
├── logger.py                 # Structured logging
├── main.py                   # CLI entry point
├── test_telegram.py          # Telegram test script
├── src/
│   ├── data/
│   │   ├── subgraph_client.py    # Uniswap V3 queries
│   │   ├── mento_client.py       # Mento FPMM integration
│   │   ├── zeroex_client.py      # DEX aggregation
│   │   └── fx_oracle.py          # Off-chain FX rates
│   ├── core/
│   │   ├── agent.py              # Main RemitAgent
│   │   ├── risk_manager.py       # Safety checks
│   │   ├── executor.py           # Transaction execution
│   │   ├── memory.py             # Trade history & learning
│   │   ├── planner.py            # Agentic planning
│   │   └── simulator.py          # Trade simulation
│   ├── notifications/
│   │   └── telegram_bot.py       # Telegram alerts & remote control
│   └── api/
│       └── dashboard.py          # FastAPI routes
├── tests/
│   └── test_opportunities.py     # Unit tests
├── POOL_EXPANSION_GUIDE.md       # Guide to adding pairs
└── TELEGRAM_REMOTE_CONTROL.md    # Remote control documentation
```

## 💡 How It Works

1. **Data Collection**: Fetches rates from Mento FPMMs, Uniswap V3, 0x API, and off-chain FX sources
2. **Opportunity Detection**: Compares rates to find spreads above threshold
3. **Risk Assessment**: Validates liquidity, gas costs, and safety checks
4. **Execution**: Simulates trades, validates profit, then executes with proper nonce management
5. **Notification**: Sends Telegram alerts for opportunities, trades, and daily summaries
6. **Remote Control**: Listens for Telegram commands to stop the agent or check status

## 🔗 Useful Links

- [Celo Explorer](https://celoscan.io)
- [Mento Protocol Docs](https://docs.mento.org)
- [Uniswap V3 Subgraph](https://thegraph.com/explorer)
- [0x API Docs](https://0x.org/docs)

## ⚠️ Disclaimer

This is experimental software for hackathon demonstration. Use at your own risk. Always test with small amounts first. Never commit private keys to git.

## 📄 License

MIT License - See LICENSE file for details.

---

Built with ❤️ for the Celo Hackathon
