import os
import json
import asyncio
import time
from google import genai
from google.genai import types
import mss
from PIL import Image
import io

with open('config.json') as f:
    cfg = json.load(f)

if cfg.get('proxy'):
    os.environ['HTTP_PROXY'] = cfg['proxy']
    os.environ['HTTPS_PROXY'] = cfg['proxy']

client = genai.Client(api_key=cfg['gemini_api_key'])

# Capture real screen
with mss.mss() as sct:
    mon = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
    raw = sct.grab(mon)
    im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    im.thumbnail((800, 450), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=40)
    screen_jpeg = buf.getvalue()
    print(f"Captured screen: {len(screen_jpeg)} bytes ({len(screen_jpeg)/1024:.1f} KB)")

async def test_screen_timing():
    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Опиши экран в 1-2 предложениях на русском языке.")]
        )
    )

    print("Connecting...")
    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        async def reader():
            t_first = None
            async for msg in session.receive():
                sc = msg.server_content
                if sc:
                    if sc.output_transcription:
                        if t_first is None:
                            t_first = time.time() - t0
                            print(f"\n[FIRST TOKEN IN {t_first:.2f}s!]")
                        print(sc.output_transcription.text, end="", flush=True)
                    if sc.turn_complete:
                        print(f"\n[TOTAL TURN TIME: {time.time() - t0:.2f}s]")
                        break

        task = asyncio.create_task(reader())

        print("Sending real screen image + question 'Что на экране?'...")
        t0 = time.time()
        await session.send_realtime_input(video=types.Blob(data=screen_jpeg, mime_type="image/jpeg"))
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(text="Что у меня на экране?")])],
            turn_complete=True
        )

        await task

asyncio.run(test_screen_timing())
