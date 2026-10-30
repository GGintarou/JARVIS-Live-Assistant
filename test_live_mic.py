import os
import json
import asyncio
import time
import sounddevice as sd
import numpy as np
from google import genai
from google.genai import types

with open('config.json') as f:
    cfg = json.load(f)

if cfg.get('proxy'):
    os.environ['HTTP_PROXY'] = cfg['proxy']
    os.environ['HTTPS_PROXY'] = cfg['proxy']

client = genai.Client(api_key=cfg['gemini_api_key'])

async def test_live_mic_continuous():
    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Отвечай кратко на русском языке.")]
        )
    )

    print("Connecting to Gemini Live...")
    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        async def infinite_listener():
            while True:
                try:
                    async for msg in session.receive():
                        sc = msg.server_content
                        if sc:
                            if sc.output_transcription:
                                print(f"[GEMINI]: {sc.output_transcription.text}", flush=True)
                            if sc.turn_complete:
                                print("[TURN COMPLETE]\n", flush=True)
                except Exception as e:
                    print("Listener error:", e)
                    break

        ltask = asyncio.create_task(infinite_listener())

        # Stream audio from mic for 10 seconds
        loop = asyncio.get_running_loop()
        q = asyncio.Queue()

        def callback(indata, frames, time_info, status):
            loop.call_soon_threadsafe(q.put_nowait, indata.copy())

        print("\n>>> Listening for 10 seconds. Say something! <<<")
        with sd.InputStream(samplerate=16000, channels=1, dtype='int16', blocksize=1024, callback=callback):
            t_end = time.time() + 8
            while time.time() < t_end:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=0.1)
                    await session.send_realtime_input(audio=types.Blob(data=chunk.tobytes(), mime_type="audio/pcm;rate=16000"))
                except asyncio.TimeoutError:
                    pass

        print("Finished 10s streaming test.")
        ltask.cancel()

asyncio.run(test_live_mic_continuous())
