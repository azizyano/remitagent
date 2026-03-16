"""
Telegram notification system for RemitAgent.
Implements rate limiting, digest mode, and remote control commands.
"""
import asyncio
from typing import Dict, Any, List, Optional, Callable
from datetime import datetime, timedelta
from collections import deque

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from config import config
from logger import logger


class TelegramNotifier:
    """
    Telegram bot for sending notifications about opportunities and trades.
    Implements rate limiting, digest mode, and remote control commands.
    """
    
    def __init__(self):
        self.bot_token = config.notifications.telegram_bot_token
        self.chat_id = config.notifications.telegram_chat_id
        self.bot: Optional[Bot] = None
        self.application: Optional[Application] = None
        
        # Rate limiting
        self._message_history: deque = deque()
        self._message_window = 60  # 1 minute
        self._max_messages = 5  # Max messages per window
        self._digest_mode = False
        self._digest_buffer: List[Dict[str, Any]] = []
        
        # Command handlers
        self._stop_callback: Optional[Callable] = None
        self._status_callback: Optional[Callable[[], Dict[str, Any]]] = None
        self._is_running = False
        
        if self.bot_token and self.chat_id:
            self.bot = Bot(token=self.bot_token)
    
    @property
    def enabled(self) -> bool:
        """Check if notifications are enabled."""
        return self.bot is not None
    
    def register_stop_callback(self, callback: Callable):
        """Register callback for emergency stop command."""
        self._stop_callback = callback
    
    def register_status_callback(self, callback: Callable[[], Dict[str, Any]]):
        """Register callback for status command."""
        self._status_callback = callback
    
    async def start_command_listener(self):
        """Start listening for Telegram commands in background."""
        if not self.enabled or self.application:
            return
        
        try:
            # Build application
            self.application = Application.builder().token(self.bot_token).build()
            
            # Add command handlers
            self.application.add_handler(CommandHandler("start", self._cmd_start))
            self.application.add_handler(CommandHandler("help", self._cmd_help))
            self.application.add_handler(CommandHandler("status", self._cmd_status))
            self.application.add_handler(CommandHandler("stop", self._cmd_stop))
            self.application.add_handler(CommandHandler("emergency", self._cmd_stop))
            self.application.add_handler(CommandHandler("stats", self._cmd_stats))
            
            # Start the bot
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)
            
            self._is_running = True
            logger.info("Telegram command listener started")
            logger.info("Available commands: /start, /help, /status, /stop, /emergency, /stats")
            
        except Exception as e:
            logger.error(f"Failed to start Telegram command listener: {e}")
    
    async def stop_command_listener(self):
        """Stop the command listener."""
        if self.application:
            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
            self._is_running = False
            logger.info("Telegram command listener stopped")
    
    # Command Handlers
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        if not self._is_authorized(update.effective_chat.id):
            return
        
        await update.message.reply_text(
            "🚀 <b>RemitAgent Remote Control</b>\n\n"
            "You can control the agent with these commands:\n\n"
            "📊 <b>/status</b> - Check agent status\n"
            "📈 <b>/stats</b> - View trading statistics\n"
            "🛑 <b>/stop</b> or <b>/emergency</b> - Emergency stop\n"
            "❓ <b>/help</b> - Show this help message\n\n"
            "The agent will automatically send notifications for:\n"
            "• Trading opportunities\n"
            "• Executed trades\n"
            "• Failed trades\n"
            "• Daily summaries",
            parse_mode=ParseMode.HTML
        )
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        await self._cmd_start(update, context)
    
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        if not self._is_authorized(update.effective_chat.id):
            return
        
        if self._status_callback:
            try:
                status = self._status_callback()
                message = (
                    "📊 <b>Agent Status</b>\n\n"
                    f"<b>Running:</b> {'Yes' if status.get('running') else 'No'}\n"
                    f"<b>Threshold:</b> {status.get('threshold', 'N/A')}%\n"
                    f"<b>Adaptive Threshold:</b> {status.get('adaptive_threshold', 'N/A'):.2f}%\n"
                    f"<b>Interval:</b> {status.get('interval', 'N/A')}s\n"
                    f"<b>Pairs:</b> {', '.join(status.get('pairs', []))}\n\n"
                    f"<b>Plans Generated:</b> {status.get('stats', {}).get('plans_generated', 0)}\n"
                    f"<b>Opportunities Seen:</b> {status.get('stats', {}).get('opportunities_seen', 0)}\n"
                    f"<b>Trades Executed:</b> {status.get('stats', {}).get('trades_executed', 0)}\n"
                    f"<b>Total Savings:</b> ${status.get('stats', {}).get('total_savings', 0):.2f}"
                )
            except Exception as e:
                message = f"⚠️ Error getting status: {e}"
        else:
            message = "⚠️ Status callback not registered"
        
        await update.message.reply_text(message, parse_mode=ParseMode.HTML)
    
    async def _cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command."""
        await self._cmd_status(update, context)
    
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stop and /emergency commands."""
        if not self._is_authorized(update.effective_chat.id):
            return
        
        # Send immediate confirmation
        await update.message.reply_text(
            "🚨 <b>EMERGENCY STOP INITIATED</b>\n\n"
            "Stopping the agent now...",
            parse_mode=ParseMode.HTML
        )
        
        logger.critical("Emergency stop triggered via Telegram command")
        
        # Trigger the stop callback
        if self._stop_callback:
            try:
                self._stop_callback()
            except Exception as e:
                logger.error(f"Error in stop callback: {e}")
        
        # Also create emergency stop file as backup
        try:
            stop_file = config.safety.emergency_stop_file
            with open(stop_file, 'w') as f:
                f.write(f"Emergency stop triggered via Telegram at {datetime.utcnow().isoformat()}\n")
            logger.info(f"Emergency stop file created: {stop_file}")
        except Exception as e:
            logger.error(f"Failed to create emergency stop file: {e}")
    
    def _is_authorized(self, chat_id: int) -> bool:
        """Check if the chat ID is authorized."""
        try:
            # Support both numeric chat IDs and usernames
            expected = str(self.chat_id)
            actual = str(chat_id)
            
            # Check if it's a direct match or if expected is a username and actual is numeric
            if expected == actual:
                return True
            
            # Allow if configured chat_id matches (handles both username and numeric)
            if expected.lstrip('-').isdigit() and actual == expected:
                return True
                
            logger.warning(f"Unauthorized access attempt from chat ID: {chat_id}")
            return False
        except Exception as e:
            logger.error(f"Error checking authorization: {e}")
            return False
    
    def _check_rate_limit(self) -> bool:
        """
        Check if we're within rate limits.
        
        Returns:
            True if can send message, False if should use digest
        """
        now = datetime.utcnow()
        
        # Remove old messages from history
        while self._message_history and \
              (now - self._message_history[0]) > timedelta(seconds=self._message_window):
            self._message_history.popleft()
        
        # Check if over limit
        if len(self._message_history) >= self._max_messages:
            self._digest_mode = True
            return False
        
        self._message_history.append(now)
        return True
    
    async def send_message(self, message: str, parse_mode: str = ParseMode.HTML) -> bool:
        """
        Send a message to Telegram.
        
        Args:
            message: Message text
            parse_mode: Parse mode for message
            
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode,
                disable_web_page_preview=True
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    async def send_opportunity_alert(self, opportunity: Dict[str, Any]):
        """
        Send opportunity detected alert.
        
        Args:
            opportunity: Opportunity details
        """
        if not self.enabled:
            return
        
        emoji = "🟢" if opportunity.get("spread_percent", 0) > 1 else "🟡"
        
        message = f"""
{emoji} <b>Opportunity Detected</b>

<b>Pair:</b> {opportunity.get('pair', 'Unknown')}
<b>Direction:</b> {opportunity.get('direction', 'Unknown')}
<b>Spread:</b> {opportunity.get('spread_percent', 0):.2f}%
<b>Confidence:</b> {opportunity.get('confidence', 'Unknown')}
<b>Profit:</b> ${opportunity.get('profit_usd', 0):.2f}

<i>Monitoring... Will execute if checks pass.</i>
"""
        
        if self._check_rate_limit():
            await self.send_message(message)
        else:
            self._digest_buffer.append({"type": "opportunity", "data": opportunity})
    
    async def send_trade_executed(
        self, 
        tx_hash: str, 
        pair: str, 
        amount: float, 
        savings: float
    ):
        """
        Send trade executed notification.
        
        Args:
            tx_hash: Transaction hash
            pair: Trading pair
            amount: Trade amount
            savings: Actual savings
        """
        if not self.enabled:
            return
        
        explorer_url = f"https://celoscan.io/tx/{tx_hash}"
        
        message = f"""
✅ <b>Trade Executed</b>

<b>Pair:</b> {pair}
<b>Amount:</b> ${amount:.2f}
<b>Savings:</b> ${savings:.2f}

<a href="{explorer_url}">View on Celo Explorer</a>
"""
        
        # Trade executed is important - send immediately
        await self.send_message(message)
    
    async def send_trade_failed(self, error: str, pair: str, amount: float):
        """
        Send trade failed notification.
        
        Args:
            error: Error message
            pair: Trading pair
            amount: Trade amount
        """
        if not self.enabled:
            return
        
        message = f"""
❌ <b>Trade Failed</b>

<b>Pair:</b> {pair}
<b>Amount:</b> ${amount:.2f}
<b>Error:</b> <code>{error[:200]}</code>

<i>Will retry on next check cycle.</i>
"""
        await self.send_message(message)
    
    async def send_daily_summary(
        self, 
        opportunities_seen: int, 
        trades_executed: int, 
        total_savings: float
    ):
        """
        Send daily summary notification.
        
        Args:
            opportunities_seen: Number of opportunities
            trades_executed: Number of trades executed
            total_savings: Total savings in USD
        """
        if not self.enabled:
            return
        
        message = f"""
📊 <b>Daily Summary</b>

<b>Opportunities Seen:</b> {opportunities_seen}
<b>Trades Executed:</b> {trades_executed}
<b>Total Savings:</b> ${total_savings:.2f}

<i>RemitAgent is actively monitoring remittance corridors.</i>
"""
        await self.send_message(message)
    
    async def send_emergency_stop(self):
        """Send emergency stop notification."""
        if not self.enabled:
            return
        
        message = """
🚨 <b>EMERGENCY STOP ACTIVATED</b>

RemitAgent has been halted via emergency stop file.
Manual intervention required to resume operations.

To restart the agent:
1. Remove the emergency stop file
2. Restart the agent manually
"""
        await self.send_message(message)
    
    async def send_digest_summary(self):
        """
        Send digest summary when rate limit is hit.
        Combines multiple opportunities into one message.
        """
        if not self._digest_buffer or not self.enabled:
            return
        
        opportunities = [item for item in self._digest_buffer if item["type"] == "opportunity"]
        
        if not opportunities:
            return
        
        message_lines = ["📋 <b>Opportunity Digest</b>\n"]
        
        for opp in opportunities[:10]:  # Max 10 in digest
            data = opp["data"]
            message_lines.append(
                f"• {data.get('pair')}: {data.get('spread_percent', 0):.2f}% spread"
            )
        
        if len(opportunities) > 10:
            message_lines.append(f"\n... and {len(opportunities) - 10} more")
        
        await self.send_message("\n".join(message_lines))
        
        # Clear buffer and reset digest mode
        self._digest_buffer = []
        self._digest_mode = False
    
    async def check_and_send_digest(self):
        """Check if we should send a digest and send it."""
        if self._digest_mode and self._digest_buffer:
            await self.send_digest_summary()
