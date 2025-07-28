#!/usr/bin/env python3
"""Test the POC WebSocket implementation"""

import asyncio
import json
import websockets

async def test_poc():
    uri = "ws://localhost:8001/ws"
    
    async with websockets.connect(uri) as websocket:
        print("✅ Connected to POC WebSocket")
        
        # Wait for connection message
        response = await websocket.recv()
        data = json.loads(response)
        print(f"📥 Connection: {data}")
        
        # Send a test message
        message = {
            "type": "message",
            "content": "hello"
        }
        
        await websocket.send(json.dumps(message))
        print(f"📤 Sent: {message['content']}")
        
        # Listen for responses
        print("📥 Waiting for responses...")
        while True:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                data = json.loads(response)
                
                print(f"📥 Received: {json.dumps(data, indent=2)}")
                
                # If it's an input request, send a response
                if data.get("type") == "input_request":
                    user_msg = {
                        "type": "message",
                        "content": "test"
                    }
                    await websocket.send(json.dumps(user_msg))
                    print(f"📤 Sent user response: {user_msg['content']}")
                    
            except asyncio.TimeoutError:
                print("⏱️ Timeout waiting for response")
                break
            except Exception as e:
                print(f"❌ Error: {e}")
                break

if __name__ == "__main__":
    asyncio.run(test_poc())