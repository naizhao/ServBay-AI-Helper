import os
import asyncio
from dotenv import load_dotenv
import dashscope
from dashscope import Application
# from dashscope.api_entities.dashscope_response import Role # Keep if needed for history
import http
import logging
from telegram import Update, constants # Import constants for ChatAction
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters, CommandHandler

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Set higher logging level for httpx to avoid noisy INFO messages
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Configuration ---
load_dotenv()
logger.info("Loading environment variables...")

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY')
BAILIAN_APP_ID = os.getenv('BAILIAN_APP_ID')

# Check environment variables
if not all([TELEGRAM_BOT_TOKEN, DASHSCOPE_API_KEY, BAILIAN_APP_ID]):
    logger.error("ERROR: Missing required environment variables!")
    logger.error("Please ensure TELEGRAM_BOT_TOKEN, DASHSCOPE_API_KEY, and BAILIAN_APP_ID are set in your .env file or environment.")
    # Provide specific checks
    if not TELEGRAM_BOT_TOKEN: logger.error("- TELEGRAM_BOT_TOKEN is missing.")
    if not DASHSCOPE_API_KEY: logger.error("- DASHSCOPE_API_KEY is missing.")
    if not BAILIAN_APP_ID: logger.error("- BAILIAN_APP_ID is missing.")
    exit()
else:
    logger.info("Environment variables loaded successfully.")

# --- Set DashScope API Key ---
try:
    dashscope.api_key = DASHSCOPE_API_KEY
    logger.info("DashScope API Key has been set successfully.")
except Exception as e:
    logger.error(f"Error setting DashScope API Key: {e}")
    exit()

# --- DashScope API Call Function (Reused from Discord version) ---
def call_bailian_app_via_dashscope(user_prompt: str, session_id: str = None, history: list = None) -> str:
    """
    Calls the Bailian application using the DashScope SDK, instructing it to respond in the input language.
    """
    # Add instruction to respond in the input language
    # Consider if this instruction is always needed or if the model handles it well
    instruction = "Please respond exclusively in the language of the User Query below.\n\nUser Query: "
    final_prompt = instruction + user_prompt
    logger.info(f"Sending final prompt (first 100 chars) to DashScope: {final_prompt[:100]}...")

    try:
        response = Application.call(
            app_id=BAILIAN_APP_ID,
            prompt=final_prompt,
            # session_id=session_id, # Add if managing sessions
            # history=history,       # Add if passing history
        )
        logger.debug(f"Raw DashScope response: {response}")

        if response.status_code == http.HTTPStatus.OK:
            if hasattr(response, 'output') and hasattr(response.output, 'text'):
                result_text = response.output.text
                logger.info("DashScope call successful, text result obtained.")
                return result_text
            else:
                logger.warning(f"DashScope response OK, but structure unexpected: {response}")
                return "Sorry, I received a response but couldn't extract the text content."
        else:
            error_msg = f"DashScope API call failed: Code: {response.status_code}, Message: {response.message}"
            if hasattr(response, 'output') and response.output:
                error_msg += f", Output: {response.output}"
            logger.error(error_msg)
            return f"Sorry, there was an error communicating with the Bailian application (Code: {response.status_code}). Please try again later."

    except Exception as e:
        logger.exception(f"Exception occurred during DashScope API call: {e}")
        return "Sorry, an internal error occurred while processing your request."

# --- Telegram Bot Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends a welcome message when the /start command is issued."""
    await update.message.reply_text(
        "Hello! I am a bot powered by Bailian. "
        "Send me a message directly, or mention me in a group, and I will try to help."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming text messages."""
    message = update.message
    user = message.from_user
    chat_id = update.effective_chat.id # Get chat ID for logging
    chat_type = message.chat.type
    text = message.text

    # --- 增加日志：记录收到的原始消息 ---
    logger.info(f"Received message in chat {chat_id} (type: {chat_type}) from user {user.id} ({user.username}). Text: '{text}'")

    if not text:
        logger.info("Ignoring non-text message.")
        return

    should_respond = False
    user_prompt = text # Default

    try:
        bot_username = context.bot.username
        # --- 增加日志：记录获取到的 bot username ---
        logger.info(f"Bot username from context: {bot_username}")
    except Exception as e:
        logger.error(f"Could not get bot username: {e}")
        return # Cannot proceed without bot username for group logic

    if chat_type == 'private':
        should_respond = True
        logger.info(f"Processing private message.")
    elif chat_type in ['group', 'supergroup']:
        if bot_username and bot_username in text: # Ensure bot_username is not None
            should_respond = True
            user_prompt = text.replace(bot_username, '').strip()
            logger.info(f"Bot mentioned in group. Extracted prompt: '{user_prompt}'")
        else:
            # --- 增加日志：记录群组消息未提及 Bot ---
            logger.info("Message in group, but bot not mentioned.")

    # --- 关键修改：处理空 Prompt ---
    if should_respond and not user_prompt:
        logger.info("Bot mentioned, but no question followed. Sending help message.")
        # --- 发送提示信息给用户 ---
        await message.reply_text(
            f"Hello {user.mention_html()}! You mentioned me, but didn't ask a question. "
            f"Please mention me again followed by your query (e.g., {bot_username} how does photosynthesis work?).",
            parse_mode='HTML' # Use HTML for mention_html
        )
        return # Don't proceed to call Bailian

    if not should_respond:
        # --- 增加日志：记录为什么不响应 ---
        logger.info("Condition to respond not met. Ignoring message.")
        return

    # --- 确认进入处理流程 ---
    logger.info(f"Processing prompt: '{user_prompt[:100]}...'")

    # Send "typing..." action
    await context.bot.send_chat_action(
        chat_id=chat_id, action=constants.ChatAction.TYPING
    )

    # ... (Rest of the code: calling Bailian, sending response) ...
    # Call Bailian API
    try:
        bailian_response = await asyncio.to_thread(call_bailian_app_via_dashscope, user_prompt)
    except Exception as e:
        logger.exception(f"Error calling Bailian via asyncio.to_thread: {e}")
        bailian_response = "Sorry, an unexpected error occurred while getting the response."

    # Send the response back to Telegram (handle length limit)
    max_length = 4096
    if len(bailian_response) <= max_length:
        try:
            await message.reply_text(bailian_response)
        except Exception as e:
            logger.exception(f"Error sending reply to Telegram: {e}")
            try:
                 await context.bot.send_message(chat_id=chat_id, text="Sorry, I encountered an issue sending the response.")
            except Exception as send_e:
                 logger.error(f"Failed even to send generic error message: {send_e}")
    else:
        logger.info(f"Response length ({len(bailian_response)}) exceeds limit, splitting message.")
        try:
            await message.reply_text("The response is quite long, I'll send it in parts:")
            for i in range(0, len(bailian_response), max_length):
                part = bailian_response[i:i + max_length]
                await context.bot.send_message(chat_id=chat_id, text=part)
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception(f"Error sending split reply to Telegram: {e}")
            try:
                 await context.bot.send_message(chat_id=chat_id, text="Sorry, I encountered an issue sending the long response.")
            except Exception as send_e:
                 logger.error(f"Failed even to send generic error message for split failure: {send_e}")

# --- Main Execution ---
if __name__ == '__main__':
    logger.info("Building Telegram Application...")
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    start_handler = CommandHandler('start', start)
    message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message) # Handle text, ignore commands

    application.add_handler(start_handler)
    application.add_handler(message_handler)

    logger.info("Starting Telegram Bot Polling...")
    # Add readiness check? e.g., test DashScope connection
    # loop = asyncio.get_event_loop()
    # loop.run_until_complete(test_dashscope_connection()) # Define this async test func if needed

    application.run_polling(allowed_updates=Update.ALL_TYPES) # Start the bot