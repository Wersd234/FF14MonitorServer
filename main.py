from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json

app = FastAPI()


class ConnectionManager:
    def __init__(self):
        # 记录每个房间(队伍)有哪些人连进来了
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # 记录每个房间当前排好的排轴和血量数据
        self.room_states: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()

        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
            # 如果是新房间，初始化一个空状态
            self.room_states[room_id] = {"type": "init", "data": [], "hp": 150000}

        self.active_connections[room_id].append(websocket)

        # 【核心体验】：当有队友刚连上来时，立刻把房间里最新的数据塞给他，保证断线重连不丢数据！
        await websocket.send_text(json.dumps(self.room_states[room_id]))

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)
            # 为了防止服务器内存爆满，如果房间里的人全退了，可以选择保留数据，或者这里做清理

    async def broadcast(self, message: str, room_id: str, sender: WebSocket):
        # 如果有人发来了更新，服务器自己偷偷记下一份快照
        try:
            payload = json.loads(message)
            if payload.get("type") == "update":
                self.room_states[room_id] = payload
        except Exception:
            pass

        # 向房间里【除发送者以外】的所有队友广播更新
        for connection in self.active_connections[room_id]:
            if connection != sender:
                await connection.send_text(message)


manager = ConnectionManager()


# WebSocket 入口：允许通过 ws://IP:8000/ws/房间号 连接
@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(websocket, room_id)
    try:
        while True:
            # 持续监听用户的排轴动作
            data = await websocket.receive_text()
            await manager.broadcast(data, room_id, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)