import json
from channels.generic.websocket import AsyncWebsocketConsumer


class DoorConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.accept()

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except Exception:
            return
        # Echo command or route if needed
        await self.send(text_data=json.dumps({'ack': True, **data}))

    async def disconnect(self, code):
        pass
