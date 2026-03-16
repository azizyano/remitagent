# Telegram Remote Control for RemitAgent

You can now control your RemitAgent remotely via Telegram! This allows you to monitor and stop the agent from anywhere without needing server access.

## Setup

1. **Make sure your `.env` file is configured:**
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_numeric_chat_id_here
   ```

2. **Get your Chat ID:**
   - Message [@userinfobot](https://t.me/userinfobot) on Telegram
   - It will reply with your numeric ID (e.g., `123456789`)
   - Use this number in your `.env` file

3. **Test your setup:**
   ```bash
   python test_telegram.py
   ```

## Available Commands

Once the agent is running, send these commands to your Telegram bot:

| Command | Description |
|---------|-------------|
| `/start` | Welcome message with available commands |
| `/help` | Show all available commands |
| `/status` | Check agent status (running, threshold, pairs, stats) |
| `/stats` | View trading statistics |
| `/stop` | **Emergency stop - Stops the agent immediately** |
| `/emergency` | Same as `/stop` - Emergency stop |

## Remote Emergency Stop

If you see the agent making bad trades or losing money:

1. **Open Telegram** (on your phone or computer)
2. **Find your bot chat**
3. **Send:** `/stop` or `/emergency`
4. **The agent will stop immediately** and send a confirmation message

The agent will also create an emergency stop file as a backup.

## Automatic Notifications

The bot will automatically send you notifications for:

- 🚀 **Agent Started** - When the agent begins monitoring
- 🟢 **Opportunities** - When profitable trades are detected
- ✅ **Trade Executed** - When a trade is successfully executed (with tx hash)
- ❌ **Trade Failed** - When a trade fails (with error message)
- 📊 **Daily Summary** - Daily statistics (every 24 hours)
- 🚨 **Emergency Stop** - When the agent is stopped

## Security

- Only the configured `TELEGRAM_CHAT_ID` can control the agent
- Commands from unauthorized users are ignored
- The emergency stop works even if the agent is in the middle of a trade

## Troubleshooting

### Bot doesn't respond to commands
- Make sure you sent `/start` to the bot first
- Verify your `TELEGRAM_CHAT_ID` is correct
- Check that the agent is running and logs show "Telegram command listener started"

### Can't stop the agent remotely
- Check if the agent is still running on the server
- Use the emergency stop file method as backup: `touch /tmp/remitagent_stop`
- Check agent logs for errors

### Notifications not working
- Run `python test_telegram.py` to verify configuration
- Check that `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env`
- Make sure you've messaged the bot at least once

## Example Usage

```bash
# Start the agent
python main.py --mode monitor

# In Telegram, you'll receive:
# "🚀 RemitAgent Started
#  Monitoring: cUSD-cEUR, cUSD-cKES, cEUR-cKES
#  Threshold: 0.5%
#  Interval: 300s
#  Remote Control: Send /stop or /emergency in Telegram to halt the agent immediately."

# Check status anytime
# Send in Telegram: /status
# Response: "📊 Agent Status
#  Running: Yes
#  Threshold: 0.5%
#  Adaptive Threshold: 0.75%
#  ..."

# Emergency stop
# Send in Telegram: /stop
# Response: "🚨 EMERGENCY STOP INITIATED
#  Stopping the agent now..."
```

## Safety Tips

1. **Keep your bot token secret** - Anyone with your token can send messages as your bot
2. **Use your numeric chat ID** - Usernames can change, numeric IDs are permanent
3. **Test the emergency stop** - Try `/stop` when the agent isn't trading to make sure it works
4. **Monitor the first few trades** - Keep an eye on notifications when you first start the agent

## Restarting After Emergency Stop

1. Remove the emergency stop file:
   ```bash
   rm /tmp/remitagent_stop
   ```

2. Restart the agent:
   ```bash
   python main.py --mode monitor
   ```

3. You'll receive a new startup notification in Telegram
