import re

with open('telegram_bot.py', 'r') as f:
    content = f.read()

# Replace the hardcoded 1024 max_tokens with 4096
content = content.replace('response = await asyncio.to_thread(ask, prompt, None, 1024)', 'response = await asyncio.to_thread(ask, prompt, None, 4096)')

# Add markdown to HTML conversion
html_patch = """
    # Convert basic markdown to HTML for Telegram
    import html
    response = html.escape(response)
    # Convert **bold** to <b>bold</b>
    import re
    response = re.sub(r'\\*\\*(.*?)\\*\\*', r'<b>\\1</b>', response)
    # Convert *italic* to <i>italic</i>
    response = re.sub(r'\\*(.*?)\\*', r'<i>\\1</i>', response)
    
    # Telegram 4096 char limit
"""

content = content.replace('    # Telegram 4096 char limit', html_patch)

with open('telegram_bot.py', 'w') as f:
    f.write(content)
