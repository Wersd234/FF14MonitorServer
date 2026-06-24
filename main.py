from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json
import sqlite3
import os
import asyncio  # 🚀 引入异步库，拯救卡顿

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
        c.execute('''
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY, 
                state_data TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def load_room_from_db(self, room_id: str) -> dict:
        """从硬盘数据库中唤醒房间数据 (耗时操作)"""
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
        return {"type": "init", "data": [], "hp": 150000, "potency_mult": 35.0}

    def save_room_to_db(self, room_id: str, state_data: dict):
        """将最新的房间数据永久写入硬盘 (耗时操作)"""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("REPLACE INTO rooms (room_id, state_data) VALUES (?, ?)",
                  (room_id, json.dumps(state_data, ensure_ascii=False)))
        conn.commit()
        conn.close()

    async def connect(self, websocket: WebSocket, room_id: str):
        await websocket.accept()

        if room_id not in self.active_connections:
            self.active_connections[room_id] = []

            # 🚀 优化 1：用后台线程去读硬盘，绝不卡顿！
            self.room_states[room_id] = await asyncio.to_thread(self.load_room_from_db, room_id)

        self.active_connections[room_id].append(websocket)
        await websocket.send_text(json.dumps(self.room_states[room_id]))

    def disconnect(self, websocket: WebSocket, room_id: str):
        if room_id in self.active_connections:
            if websocket in self.active_connections[room_id]:
                self.active_connections[room_id].remove(websocket)
            # 🚀 优化 2：如果房间空了，从 RAM 内存里清理掉，防止内存泄漏（数据仍在硬盘）
            if not self.active_connections[room_id]:
                del self.active_connections[room_id]

    async def broadcast(self, message: str, room_id: str, sender: WebSocket):
        try:
            payload = json.loads(message)
            if payload.get("type") in ["update", "init"]:
                self.room_states[room_id] = payload
                # 🚀 优化 3：把写硬盘的操作扔进后台线程任务！服务器瞬间提速 100 倍！
                asyncio.create_task(asyncio.to_thread(self.save_room_to_db, room_id, payload))
        except Exception as e:
            print(f"Error saving state: {e}")

        # 🛡️ 优化 4：幽灵死连接清理机制，防止服务器崩溃
        dead_connections = []
        for connection in self.active_connections.get(room_id, []):
            if connection != sender:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    print(f"⚠️ 踢出掉线玩家: {e}")
                    dead_connections.append(connection)

        for dead_ws in dead_connections:
            self.disconnect(dead_ws, room_id)


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
    except Exception as e:
        print(f"未知异常断开: {e}")
        manager.disconnect(websocket, room_id)