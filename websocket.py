from fastapi import WebSocket


class WebSocketManager:

    def __init__(self):
        self.connections = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.connections[user_id] = websocket

    def disconnect(self, user_id: str):
        self.connections.pop(user_id, None)

    async def send_message(self, receiver_id: str, message: dict) -> bool:
        websocket = self.connections.get(receiver_id)
        if websocket:
            try:
                await websocket.send_json(message)
                return True
            except Exception as e:
                print(f"Error sending to {receiver_id}: {e}")
                return False
        return False

    def is_online(self, user_id: str) -> bool:
        return user_id in self.connections

    def get_online_users(self) -> list:
        return list(self.connections.keys())


manager = WebSocketManager()
