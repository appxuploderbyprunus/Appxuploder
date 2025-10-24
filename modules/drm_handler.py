import os
import re
import sys
import m3u8
import json
import time
import pytz
import asyncio
import requests
import subprocess
import urllib.parse
import yt_dlp
import tgcrypto
import cloudscraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from base64 import b64encode, b64decode
from logs import logging
from bs4 import BeautifulSoup
from aiohttp import ClientSession
from subprocess import getstatusoutput
from pytube import YouTube
from aiohttp import web
import random
from pyromod import listen
from pyrogram import Client, filters
from pyrogram.errors import FloodWait, PeerIdInvalid, UserIsBlocked, InputUserDeactivated
from pyrogram.errors.exceptions.bad_request_400 import StickerEmojiInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, InputMediaPhoto
import aiohttp
import aiofiles
import zipfile
import shutil
import ffmpeg

import saini as helper
import html_handler
import globals
from authorisation import add_auth_user, list_auth_users, remove_auth_user
from broadcast import broadcast_handler, broadusers_handler
from text_handler import text_to_txt
from youtube_handler import ytm_handler, y2t_handler, getcookies_handler, cookies_handler
from utils import progress_bar
from vars import API_ID, API_HASH, BOT_TOKEN, OWNER, CREDIT, AUTH_USERS, TOTAL_USERS, cookies_file_path
from vars import api_url # This now has your Koyeb link!
from globals import cwtoken, cptoken, pwtoken # NEW: Ensures tokens are available for decryption

# ----- New Decryption Logic Function (Called by your main handler) -----
def get_keys_from_api(url, user_id):
    """Fetches MPD URL and Decryption Keys from the specified API."""
    try:
        # Construct the API request URL using the template from vars.py
        api_request_url = api_url.format(url=urllib.parse.quote(url, safe=''), user_id=user_id)
        
        logging.info(f"API Request URL: {api_request_url}")
        
        # Pass CW_TOKEN as a header for platforms that require it
        headers = {}
        if cwtoken:
            headers['Authorization'] = f'Bearer {cwtoken}'
            
        response = requests.get(api_request_url, headers=headers, timeout=30)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        
        data = response.json()
        
        # Check for error message in response data
        if 'error' in data:
            raise Exception(f"API Error: {data['error']}")
            
        mpd_url = data.get('MPD', data.get('mpd_url'))
        keys = data.get('KEYS', data.get('keys'))
        
        if not mpd_url or not keys:
            raise Exception("API did not return valid MPD URL or Decryption Keys.")
            
        return mpd_url, keys
        
    except requests.exceptions.RequestException as e:
        logging.error(f"API Request Failed: {e}")
        raise Exception(f"Failed to reach Decryption API: {e}")
    except json.JSONDecodeError:
        logging.error(f"API returned invalid JSON: {response.text}")
        raise Exception("Decryption API returned invalid response.")
    except Exception as e:
        logging.error(f"Decryption API Error: {e}")
        raise e

# ----- Main Handler Function (Structure modified to use the new API function) -----
async def drm_handler(bot: Client, m: Message):
    if not globals.processing_request:
        globals.processing_request = True
    else:
        await m.reply_text("⛔️ **An existing task is running.** Please use `/stop` to cancel it or wait for it to finish.", quote=True)
        return

    try:
        # Initial code to get user ID, links, and set up variables (assuming this part is correct from your original code)
        user_id = m.from_user.id
        # ... (Your logic to get 'raw_text', 'channel_id', 'b_name', 'raw_text2', etc.) ...
        
        if m.reply_to_message and m.reply_to_message.document and m.reply_to_message.document.file_name.endswith('.txt'):
            file_path = await m.reply_to_message.download()
            with open(file_path, "r") as f:
                links = f.read().splitlines()
            # ... (Rest of your file name/batch name logic) ...
            
        else:
             # Logic for direct text input or reply to single link (use the provided snippet structure)
            raw_text = m.text if m.text else m.caption
            links = raw_text.splitlines() if raw_text else []
            # ... (Rest of your single link logic) ...


        if not links:
            await m.reply_text("❌ **No links found.** Please provide a valid list of links or reply to a `.txt` file.", quote=True)
            globals.processing_request = False
            return
            
        # Initialization for counts (assuming these are defined in your original code)
        count = 1
        failed_count = 0
        v2_count = 0
        mpd_count = 0
        m3u8_count = 0
        yt_count = 0
        drm_count = 0
        zip_count = 0
        other_count = 0
        pdf_count = 0
        img_count = 0
        
        # Start processing links
        for url in links:
            if globals.cancel_requested:
                await m.reply_text("🚫 **Task Cancelled** by user.", quote=True)
                break
                
            url = url.strip()
            if not url:
                continue

            # Check if the link is a DRM link (Appx/Classplus pattern)
            is_drm_link = "appx" in url.lower() or "classplus" in url.lower() or any(ext in url for ext in ["mpd", "p-cdn.net"])

            if is_drm_link:
                name1 = f"Decrypted_Video_{count}" # Placeholder name
                
                # Use the new API for decryption
                try:
                    mpd_url, keys = get_keys_from_api(url, user_id)
                    
                    # Format keys for yt-dlp
                    key_list = [f"{k['kid']}:{k['key']}" for k in keys]
                    decryption_keys = ','.join(key_list)
                    
                    # yt-dlp options for DRM download
                    # Note: We use the mpd_url returned by the API, and the keys
                    ydl_opts = {
                        'format': 'best',
                        'external_downloader': 'aria2c',
                        'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M'],
                        'allow_unplayable_formats': True,
                        'skip_download': False,
                        'restrictfilenames': True,
                        'no_check_certificate': True,
                        'ignoreerrors': True,
                        'logtostderr': False,
                        'quiet': True,
                        'no_warnings': True,
                        'add_metadata': True,
                        'http_headers': {
                            'Authorization': f'Bearer {cwtoken}' # Use the CW_TOKEN as a header fallback
                        },
                        'allow_multiple_keys': True,
                        'decryption_keys': decryption_keys, # Pass the keys directly
                        'outtmpl': f"downloads/{b_name}/{name1}.%(ext)s" # Use placeholder name for yt-dlp
                    }

                    # Download the video using yt-dlp
                    await m.reply_text(f"Decrypting and downloading DRM link {count}/{len(links)}: {name1}", quote=True)
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([mpd_url])
                        
                    # Find the downloaded file and upload it (assuming helper.send_video is used for upload)
                    downloaded_file = next((os.path.join(f"downloads/{b_name}", f) for f in os.listdir(f"downloads/{b_name}") if f.startswith(name1)), None)
                    
                    if downloaded_file:
                        await helper.send_video(bot, m, downloaded_file, name1, user_id) # Call your existing upload function
                        os.remove(downloaded_file) # Clean up
                    else:
                        raise Exception("Downloaded file not found after yt-dlp execution.")
                        
                    drm_count += 1
                    
                except Exception as e:
                    # Log and report the failure
                    logging.error(f"DRM Link Decryption/Download Failed for {name1}: {str(e)}")
                    await m.reply_text(f'<b>-┈━═.•°💔 Failed 💔°•.═━┈-</b>\n**Name** =>> `{str(count).zfill(3)} {name1}`\n**Url** =>> {url}\n\n<blockquote expandable><i><b>Failed Reason: {str(e)}</b></i></blockquote>', disable_web_page_preview=True)
                    failed_count += 1
                
            # ... (Your original code for handling non-DRM links like M3U8, MP4, PDF, etc. goes here) ...
            # The structure of your existing code for non-DRM links (which calls helper functions) should be placed here.
            
            count += 1
            
        # Final summary message
        success_count = len(links) - failed_count
        video_count = v2_count + mpd_count + m3u8_count + yt_count + drm_count + zip_count + other_count
        
        # ... (Your original final message logic, adapted below) ...
        
        final_caption = (
            "<b>-┈━═.•°✅ Completed ✅°•.═━┈-</b>\n"
            f"<blockquote><b>🎯Batch Name : {b_name}</b></blockquote>\n"
            f"<blockquote>🔗 Total URLs: {len(links)} \n"
            f"┃   ┠🔴 Total Failed URLs: {failed_count}\n"
            f"┃   ┠🟢 Total Successful URLs: {success_count}\n"
            f"┃   ┃   ┠🎥 Total Video URLs: {video_count}\n"
            f"┃   ┃   ┠📄 Total PDF URLs: {pdf_count}\n"
            f"┃   ┃   ┠📸 Total IMAGE URLs: {img_count}</blockquote>\n"
        )
        
        await bot.send_message(channel_id, final_caption)

    except Exception as e:
        await m.reply_text(f"An unexpected error occurred: {str(e)}", quote=True)
    finally:
        globals.processing_request = False
        globals.cancel_requested = False
        # Clean up downloaded files/folders (assuming you have cleanup logic)
        # shutil.rmtree(f"downloads/{b_name}", ignore_errors=True)
        # os.remove(file_path) # if a file was uploaded
