from fastapi import WebSocket


class WebSocketManager:

    def __init__(self):
        self.connections = {}

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        # Close any previous socket for this user before replacing it. Otherwise the
        # old zombie coroutine stays parked in receive_json(), and when it finally
        # dies its cleanup would evict THIS new connection (see disconnect()).
        old = self.connections.get(user_id)
        if old is not None and old is not websocket:
            try:
                await old.close(code=1000)
            except Exception:
                pass
        self.connections[user_id] = websocket

    def disconnect(self, user_id: str, websocket: WebSocket = None) -> bool:
        """Remove a user's connection. Returns True if a connection was removed.

        When `websocket` is given, only remove it if it's still the current socket
        for that user. This stops a stale/zombie socket's cleanup from evicting a
        newer live connection created by a reconnect.
        """
        current = self.connections.get(user_id)
        if current is None:
            return False
        if websocket is not None and current is not websocket:
            return False
        self.connections.pop(user_id, None)
        return True

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
