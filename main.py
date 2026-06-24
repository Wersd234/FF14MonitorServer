from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json
import sqlite3
import os

app = FastAPI()

# 数据库存储路径（将会被映射到 Docker 外部保证数据永不丢失）
DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "sync_states.db")


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.room_states: Dict[str, dict] = {}
        self.init_db()

    def init_db(self):
        """初始化 SQLite 数据库"""
        os.makedirs(DB_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # 创建一张表：房间号为主键，状态为 JSON 文本
        c.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY, 
                state_data TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def load_room_from_db(self, room_id: str) -> dict:
        """从硬盘数据库中唤醒房间数据"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT state_data FROM rooms WHERE room_id=?", (room_id,))
        row = c.fetchone()
        conn.close()

        if row:
            try:
                return json.loads(row[0])
            except:
                pass
        # 如果是彻头彻尾的新房间，给个空模板
        return {"type": "init", "data": [], "hp": 150000, "potency_mult": 35.0}

    def save_room_to_db(self, room_id: str, state_data: dict):
        """将最新的房间数据永久写入硬盘"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # REPLACE INTO：有则覆盖更新，无则插入新行
        c.execute("REPLACE INTO rooms (room_id, state_data) VALUES (?, ?)",
                  (room_id, json.dumps(state_data, ensure_ascii=False)))
        conn.commit()
        conn.close()

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()

        if room_id not in self.active_connections:
            self.active_connections[room_id] = []
            # 房间被激活时，优先从硬盘读取历史存档
            self.room_states[room_id] = self.load_room_from_db(room_id)

        self.active_connections[room_id].append(websocket)

        # 连上的瞬间，把云端数据发给刚上线的队员
        await websocket.send_text(json.dumps(self.room_states[room_id]))

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            self.active_connections[room_id].remove(websocket)
            # 即使所有人都退出了房间，数据依然保留在 SQLite 中！

    async def broadcast(self, message: str, room_id: str, sender: WebSocket):
        # 如果收到更新，不仅要存在 RAM 里，还要存进硬盘！
        try:
            payload = json.loads(message)
            if payload.get("type") in ["update", "init"]:
                self.room_states[room_id] = payload
                self.save_room_to_db(room_id, payload)  # 写入持久化存储
        except Exception as e:
            print(f"Error saving state: {e}")

        # 广播给房间里的其他队友
        for connection in self.active_connections.get(room_id, []):
            if connection != sender:
                await connection.send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/{room_id}")
async def websocket_endpoint(websocket: WebSocket, room_id: str):
    await manager.connect(websocket, room_id)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data, room_id, websocket)
    except WebSocketDisconnect:
        manager.disconnect(websocket, room_id)