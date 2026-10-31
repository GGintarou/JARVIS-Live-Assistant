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

# Test audio tone as simulated user speech
sr = 16000
t = np.linspace(0, 0.8, int(sr * 0.8), False)
simulated_speech = (np.sin(300 * 2 * np.pi * t) * 4000).astype(np.int16).tobytes()

async def benchmark_client_content_latency():
    tools_decl = [
        types.FunctionDeclaration(
            name="open_url",
            description="Открывает ссылку или сайт в браузере.",
            behavior="NON_BLOCKING",
            parameters={"type": "OBJECT", "properties": {"url": {"type": "STRING"}}, "required": ["url"]}
        ),
        types.FunctionDeclaration(
            name="open_youtube",
            description="Открывает YouTube или рандомное видео / поиск.",
            behavior="NON_BLOCKING",
            parameters={"type": "OBJECT", "properties": {"action": {"type": "STRING"}}}
        )
    ]

    connect_config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        output_audio_transcription=types.AudioTranscriptionConfig(),
        system_instruction=types.Content(
            parts=[types.Part(text="Ты Джарвис. Отвечай кратко на русском языке. Всегда вызывай инструменты, когда просят открыть браузер или ютуб.")]
        ),
        tools=[types.Tool(function_declarations=tools_decl)]
    )

    print("Connecting...")
    async with client.aio.live.connect(model="gemini-3.8-live", config=connect_config) as session:
        print("Connected.")

        latencies = []

        async def listener():
            nonlocal t_send
            while True:
                try:
                    async for msg in session.receive():
                        sc = msg.server_content
                        if sc and sc.model_turn:
                            if t_send is not None:
                                dt = time.time() - t_send
                                latencies.append(dt)
                                print(f"⚡ FIRST AUDIO PACKET IN {dt*1000:.0f} ms! (Trans: {sc.output_transcription.text if sc.output_transcription else ''})")
                                t_send = None
                        if msg.tool_call:
                            print(f"⚡ TOOL CALLED: {msg.tool_call.function_calls[0].name} in {(time.time()-t_send)*1000:.0f} ms!")
                            resp = types.FunctionResponse(
                                id=msg.tool_call.function_calls[0].id,
                                name=msg.tool_call.function_calls[0].name,
                                response={"result": "ok"}
                            )
                            await session.send_tool_response(function_responses=[resp])
                except Exception as e:
                    break

        asyncio.create_task(listener())

        test_prompts = [
            "Jarvis, открой мой браузер",
            "Открой YouTube и открой рандомное видео",
            "Привет, Джарвис, как дела?"
        ]

        for p in test_prompts:
            print(f"\n--- PROMPT: '{p}' ---")
            t_send = time.time()
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text=p)])],
                turn_complete=True
            )
            await asyncio.sleep(3.0)

        if latencies:
            print(f"\n==========================================")
            print(f"AVERAGE LATENCY: {sum(latencies)/len(latencies)*1000:.0f} ms")
            print(f"MIN LATENCY:     {min(latencies)*1000:.0f} ms")
            print(f"MAX LATENCY:     {max(latencies)*1000:.0f} ms")
            print(f"==========================================")

asyncio.run(benchmark_client_content_latency())
