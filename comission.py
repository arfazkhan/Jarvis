import asyncio
import aiohttp
import json

async def commission():
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('ws://localhost:5580/ws') as ws:
            await ws.receive_json()
            # Try with discriminator
            await ws.send_json({
                'message_id': 'commission1',
                'command': 'commission_on_network',
                'args': {
                    'setup_pin_code': 21746026,
                    'ip_addr': '192.168.1.20'
                }
            })
            print('Commissioning on network...')
            for _ in range(30):
                r = await ws.receive_json()
                print(json.dumps(r, indent=2))
                if r.get('message_id') == 'commission1': break

asyncio.run(commission())