# Rich Message Bot

A Telegram Rich Message composer inspired by the screenshots.

## Features
- Create New Message
- My Saved Messages (SQLite)
- Mini App composer
- Text formatting: bold, italic, underline, strike, spoiler, mark, code, sub/superscript
- Heading
- List
- Quote
- Table with add/remove rows and columns
- Expandable details
- Formula
- Single media by URL
- Collage/slideshow by URL
- Preview
- Code/HTML view
- Send directly as Telegram Rich Message
- aiohttp health server for Render

Telegram added Rich Messages in Bot API 10.1 and expanded the feature in 10.2/10.3. This project uses aiogram 3.31+, which exposes `sendRichMessage` and the Rich Message types.

## Termux quick test

1. Install Python and git:
   `pkg update && pkg upgrade`
   `pkg install python git`

2. Go to the project folder:
   `cd rich_message_bot`

3. Install:
   `pip install -r requirements.txt`

4. Create `.env` is optional. Termux can export variables:
   `export BOT_TOKEN="123:ABC"`
   `export WEBAPP_URL="http://127.0.0.1:8080"`

5. Start:
   `python bot.py`

The bot polling works locally. Open `http://127.0.0.1:8080/app?draft_id=...` in Chrome to test the composer UI.

Important: Telegram Mini Apps require a public HTTPS URL for the actual in-Telegram Web App. For full Telegram Mini App testing, deploy the same project to Render or expose the local server through a secure HTTPS tunnel.

## Render

Use the included `render.yaml`, or create a Python Web Service manually.

Build:
`pip install -r requirements.txt`

Start:
`python bot.py`

Environment variables:
- `BOT_TOKEN` = BotFather token
- `WEBAPP_URL` = your Render service URL, e.g. `https://rich-message-bot.onrender.com`

After deploy, set `WEBAPP_URL` to the final HTTPS URL and redeploy if necessary.

## Security note

This starter uses an unguessable draft UUID in the Mini App URL. For a public production bot, add Telegram WebApp `initData` validation on the server before accepting draft edits/sends.
