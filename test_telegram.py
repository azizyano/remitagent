"""
Test script to verify Telegram notifications and remote control are working.
Run this to check if your bot token and chat ID are configured correctly.
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

async def test_telegram():
    """Test Telegram notification and remote control."""
    from src.notifications.telegram_bot import TelegramNotifier
    
    notifier = TelegramNotifier()
    
    print("=" * 60)
    print("Telegram Notification & Remote Control Test")
    print("=" * 60)
    
    # Check configuration
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token:
        print("[FAIL] TELEGRAM_BOT_TOKEN not set in .env file")
        return False
    else:
        print(f"[OK] TELEGRAM_BOT_TOKEN is set (ends with ...{bot_token[-4:]})")
    
    if not chat_id:
        print("[FAIL] TELEGRAM_CHAT_ID not set in .env file")
        return False
    else:
        print(f"[OK] TELEGRAM_CHAT_ID is set: {chat_id}")
    
    print(f"[OK] Notifier enabled: {notifier.enabled}")
    print()
    
    # Try to send a test message
    print("Sending test message to Telegram...")
    try:
        success = await notifier.send_message(
            "<b>RemitAgent Test</b>\n\n"
            "If you see this message, your Telegram notifications are working!\n\n"
            "You will receive alerts for:\n"
            "• Trading opportunities\n"
            "• Executed trades\n"
            "• Failed trades\n"
            "• Daily summaries\n\n"
            "<b>Remote Control Commands:</b>\n"
            "• /status - Check agent status\n"
            "• /stats - View trading stats\n"
            "• /stop or /emergency - Stop the agent immediately\n"
            "• /help - Show all commands"
        )
        
        if success:
            print("[OK] Test message sent successfully!")
        else:
            print("[FAIL] Failed to send test message")
            return False
            
    except Exception as e:
        print(f"[FAIL] Error sending message: {e}")
        print()
        print("Troubleshooting tips:")
        print("1. Make sure your bot token is correct")
        print("2. Make sure you've started a chat with your bot (@YourBotName)")
        print("3. Make sure the chat ID is correct (use @userinfobot to get your ID)")
        print("4. If using a group chat, make sure the bot is added to the group")
        return False
    
    print()
    print("=" * 60)
    print("Testing Command Listener...")
    print("=" * 60)
    
    # Test command listener
    try:
        # Register test callbacks
        def test_stop():
            print("[OK] Stop callback triggered!")
        
        def test_status():
            return {"running": True, "stats": {"trades_executed": 5}}
        
        notifier.register_stop_callback(test_stop)
        notifier.register_status_callback(test_status)
        
        # Start command listener
        await notifier.start_command_listener()
        print("[OK] Command listener started successfully!")
        print()
        print("Try sending these commands to your bot on Telegram:")
        print("  /start - Welcome message")
        print("  /help  - Show commands")
        print("  /status - Get agent status")
        print("  /stats - Get trading stats")
        print("  /stop  - Test stop callback (won't actually stop anything)")
        print()
        print("The listener will run for 60 seconds for testing...")
        print("Send a command now!")
        
        await asyncio.sleep(60)
        
        await notifier.stop_command_listener()
        print("[OK] Command listener stopped")
        
    except Exception as e:
        print(f"[FAIL] Error with command listener: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print()
    print("=" * 60)
    print("All tests passed!")
    print("=" * 60)
    print()
    print("Your Telegram bot is configured correctly.")
    print("Run 'python main.py --mode monitor' to start the agent.")
    print()
    print("You can now control the agent remotely via Telegram:")
    print("  • /status - Check if agent is running")
    print("  • /stop or /emergency - Stop the agent immediately")
    print("  • You'll receive notifications for trades and opportunities")
    
    return True

if __name__ == "__main__":
    try:
        result = asyncio.run(test_telegram())
        exit(0 if result else 1)
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
        exit(0)
