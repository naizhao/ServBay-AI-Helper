import discord
import os
import asyncio
from dotenv import load_dotenv
import dashscope # 确保导入
from dashscope import Application
from dashscope.api_entities.dashscope_response import Role
import http
import logging # 添加日志记录

# --- 日志配置 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- 配置 ---
load_dotenv() # 加载 .env 文件

DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DASHSCOPE_API_KEY = os.getenv('DASHSCOPE_API_KEY') # 先获取环境变量值
BAILIAN_APP_ID = os.getenv('BAILIAN_APP_ID')

# 检查环境变量
if not all([DISCORD_BOT_TOKEN, DASHSCOPE_API_KEY, BAILIAN_APP_ID]):
    logging.error("错误：请确保 .env 文件中设置了 DISCORD_BOT_TOKEN, DASHSCOPE_API_KEY, 和 BAILIAN_APP_ID！")
    # 提醒用户检查 .env 文件内容和位置
    logging.error("请确认：")
    logging.error("1. 项目根目录下存在名为 .env 的文件。")
    logging.error(f"2. .env 文件包含 'DASHSCOPE_API_KEY=你的百炼API Key' 这一行，并且 Key 是正确的。")
    logging.error(f"3. .env 文件包含 'DISCORD_BOT_TOKEN=你的机器人Token'。")
    logging.error(f"4. .env 文件包含 'BAILIAN_APP_ID=你的百炼应用AppId'。")
    exit()
else:
    logging.info(".env 文件加载成功。")

# --- 修复错误 1：显式设置 DashScope API Key ---
try:
    dashscope.api_key = DASHSCOPE_API_KEY
    logging.info("DashScope API Key 已成功设置。")
except Exception as e:
    logging.error(f"设置 DashScope API Key 时出错: {e}")
    exit()

# --- DashScope API 调用函数 ---
def call_bailian_app_via_dashscope(user_prompt: str, session_id: str = None, history: list = None) -> str:
    """
    使用 DashScope SDK 调用百炼应用 (Agent/Workflow/etc.)，并要求使用用户输入的语言回复。
    """
    # --- 实现默认使用用户输入的语言输出：在用户问题前添加指令 ---
    english_instruction = "Please respond exclusively in Input Language.\n\nUser Query: "
    final_prompt = english_instruction + user_prompt
    logging.info(f"发送给 DashScope 的最终 Prompt: {final_prompt[:100]}...") # 打印部分内容

    try:
        response = Application.call(
            app_id=BAILIAN_APP_ID,
            prompt=final_prompt, # 使用添加了指令的 Prompt
            # session_id=session_id,
            # history=history,
            # stream=False, # 如果需要流式，设为True并修改处理逻辑
        )

        logging.debug(f"DashScope 原始响应: {response}") # 打印完整响应供调试

        if response.status_code == http.HTTPStatus.OK:
            if hasattr(response, 'output') and hasattr(response.output, 'text'):
                result_text = response.output.text
                logging.info("DashScope 调用成功并获取到文本结果。")
                return result_text
            else:
                logging.warning(f"DashScope 响应成功，但结构不符合预期: {response}")
                return "Sorry, I received a response but couldn't extract the text content."
        else:
            error_msg = f"DashScope API call failed: Code: {response.status_code}, Message: {response.message}"
            if hasattr(response, 'output') and response.output:
                error_msg += f", Output: {response.output}"
            logging.error(error_msg)
            # 返回英文错误提示
            return f"Sorry, there was an error communicating with the Bailian application ({response.status_code}). Please try again later."

    except Exception as e:
        logging.exception(f"调用 DashScope API 时发生异常: {e}") # 使用 logging.exception 记录堆栈信息
        # 返回英文错误提示
        return "Sorry, an internal error occurred while processing your request."


# --- Discord Bot 设置 ---
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    logging.info(f'机器人已登录: {client.user.name} (ID: {client.user.id})')
    logging.info(f'使用百炼应用 AppId: {BAILIAN_APP_ID}')
    logging.info('------')
    # 建议：在此处也检查一次 DashScope API 是否可用（例如发送一个简单的测试请求）
    # test_response = await asyncio.to_thread(call_bailian_app_via_dashscope, "Hello")
    # logging.info(f"DashScope API 测试连接响应: {test_response[:100]}...")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    mentioned = client.user in message.mentions

    if mentioned:
        user_prompt = ""
        mention_patterns = [f'<@!{client.user.id}>', f'<@{client.user.id}>']
        temp_content = message.content
        for pattern in mention_patterns:
            # 尝试移除开头的 mention
            if temp_content.startswith(pattern):
                user_prompt = temp_content[len(pattern):].strip()
                break
            # 尝试移除中间或结尾的 mention (取前面的内容作为 prompt)
            # 注意：这种分割可能不总是符合用户意图，如果 mention 在句中
            parts = temp_content.split(pattern, 1)
            if len(parts) > 1:
                 # 优先取 mention 前面的部分，如果前面为空，再取后面的
                 front_part = parts[0].strip()
                 back_part = parts[1].strip()
                 user_prompt = front_part if front_part else back_part
                 if user_prompt: # 确保提取到了内容
                     break

        if not user_prompt:
            # 使用英文回复提示信息
            await message.channel.send(f"{message.author.mention} Hello! How can I help you? (Please @mention me and ask your question)")
            return

        logging.info(f"Received query from {message.author} ({message.author.id}): {user_prompt}")

        # 使用英文发送提示
        thinking_message = await message.channel.send("🤔 Thinking...")

        try:
            bailian_response = await asyncio.to_thread(call_bailian_app_via_dashscope, user_prompt)

        except Exception as e:
            # 记录详细错误，但给用户通用英文提示
            logging.exception(f"Error processing message or calling Bailian: {e}")
            bailian_response = "Sorry, an unexpected error occurred while getting the response."

        response_content = f"{message.author.mention} {bailian_response}"

        try:
            if len(response_content) <= 2000:
                await thinking_message.edit(content=response_content)
            else:
                # 使用英文提示分段发送
                await thinking_message.edit(content=f"{message.author.mention} The response is quite long, sending it in parts:")
                # 发送第一部分（带 mention）
                first_part_content = response_content[:1950] # 预留一些空间
                await message.channel.send(first_part_content)
                # 发送剩余部分（不带 mention）
                remaining_content = bailian_response[len(first_part_content) - len(message.author.mention) - 1:] # 减去 mention 和空格的长度
                parts = [remaining_content[i:i+1980] for i in range(0, len(remaining_content), 1980)] # 后续部分可以更长
                for part in parts:
                    await message.channel.send(part)

        except discord.errors.NotFound:
            logging.warning("Couldn't edit thinking message (likely deleted). Sending new message.")
            # 分段发送逻辑同上，但使用 send 而不是 edit
            if len(response_content) <= 2000:
                 await message.channel.send(response_content)
            else:
                 await message.channel.send(f"{message.author.mention} The response is quite long, sending it in parts:")
                 first_part_content = response_content[:1950]
                 await message.channel.send(first_part_content)
                 remaining_content = bailian_response[len(first_part_content) - len(message.author.mention) -1:]
                 parts = [remaining_content[i:i+1980] for i in range(0, len(remaining_content), 1980)]
                 for part in parts:
                     await message.channel.send(part)
        except Exception as e:
            logging.exception(f"Error sending/editing Discord message: {e}")
            # 使用英文发送错误消息
            await message.channel.send(f"{message.author.mention} Sorry, there was an issue sending the reply.")


# --- 运行 Bot ---
if __name__ == "__main__":
    logging.info("Starting Discord Bot...")
    # 可以在这里添加更多启动检查
    if not DASHSCOPE_API_KEY:
        logging.critical("DASHSCOPE_API_KEY 未设置，机器人无法启动。")
    else:
        client.run(DISCORD_BOT_TOKEN)