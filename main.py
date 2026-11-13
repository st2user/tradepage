import sqlite3
import hashlib
import secrets
import traceback
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

app = FastAPI()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def init_db():
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        
        # 1. users 表格
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                token TEXT
            )
        """)
        
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        admin = cursor.fetchone()
        if not admin:
            admin_token = secrets.token_hex(16)
            cursor.execute("INSERT INTO users (username, password_hash, token) VALUES (?, ?, ?)",
                           ("admin", hash_password("admin123"), admin_token))
            default_user_id = cursor.lastrowid
        else:
            default_user_id = admin[0]

        # 2. tabs 表格
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tabs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                sort_order INTEGER NOT NULL DEFAULT 0,
                tab_type TEXT NOT NULL DEFAULT 'matrix',
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        cursor.execute("PRAGMA table_info(tabs)")
        tab_cols = [c[1] for c in cursor.fetchall()]
        if "user_id" not in tab_cols:
            cursor.execute(f"ALTER TABLE tabs ADD COLUMN user_id INTEGER NOT NULL DEFAULT {default_user_id}")
        if "sort_order" not in tab_cols:
            cursor.execute("ALTER TABLE tabs ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        if "tab_type" not in tab_cols:
            cursor.execute("ALTER TABLE tabs ADD COLUMN tab_type TEXT NOT NULL DEFAULT 'matrix'")

        # 3. tab_pages 表格
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tab_pages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                tab_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '步驟頁',
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (tab_id) REFERENCES tabs (id) ON DELETE CASCADE
            )
        """)

        # 4. items 表格
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                tab_id INTEGER NOT NULL,
                page_id INTEGER DEFAULT 0,
                title TEXT NOT NULL,
                field1 TEXT DEFAULT '',
                field2 TEXT DEFAULT '',
                field3 TEXT DEFAULT '',
                category TEXT NOT NULL DEFAULT 'primary',
                is_active INTEGER DEFAULT 0,
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
                FOREIGN KEY (tab_id) REFERENCES tabs (id) ON DELETE CASCADE
            )
        """)
        cursor.execute("PRAGMA table_info(items)")
        item_cols = [c[1] for c in cursor.fetchall()]
        if "user_id" not in item_cols:
            cursor.execute(f"ALTER TABLE items ADD COLUMN user_id INTEGER NOT NULL DEFAULT {default_user_id}")
        if "sort_order" not in item_cols:
            cursor.execute("ALTER TABLE items ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        if "page_id" not in item_cols:
            cursor.execute("ALTER TABLE items ADD COLUMN page_id INTEGER DEFAULT 0")
        if "field1" not in item_cols:
            cursor.execute("ALTER TABLE items ADD COLUMN field1 TEXT DEFAULT ''")
        if "field2" not in item_cols:
            cursor.execute("ALTER TABLE items ADD COLUMN field2 TEXT DEFAULT ''")
        if "field3" not in item_cols:
            cursor.execute("ALTER TABLE items ADD COLUMN field3 TEXT DEFAULT ''")

        # 5. header_badges 表格
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS header_badges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                field1 TEXT NOT NULL DEFAULT '',
                field2 TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'green',
                label_green TEXT NOT NULL DEFAULT '升',
                label_red TEXT NOT NULL DEFAULT '跌',
                label_gray TEXT NOT NULL DEFAULT '平',
                sort_order INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)

        # 預設建立 SOP流程導引 為第一頁 (sort_order = 0)
        cursor.execute("SELECT id FROM tabs WHERE user_id = ? AND tab_type = 'wizard'", (default_user_id,))
        wizard_tab = cursor.fetchone()
        if not wizard_tab:
            cursor.execute("UPDATE tabs SET sort_order = sort_order + 1 WHERE user_id = ?", (default_user_id,))
            cursor.execute("INSERT INTO tabs (user_id, name, sort_order, tab_type) VALUES (?, 'SOP流程導引', 0, 'wizard')", (default_user_id,))
            w_tab_id = cursor.lastrowid
            
            cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, '第 1 頁：大趨勢確認', 0)", (default_user_id, w_tab_id))
            p1_id = cursor.lastrowid
            cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, '日線趨勢', 'EMA 排列', '20 > 50', '多頭順勢中', 'primary', 0, 0)", (default_user_id, w_tab_id, p1_id))
            
            cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, '第 2 頁：結構與信號驗證', 1)", (default_user_id, w_tab_id))
            p2_id = cursor.lastrowid
            cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, '回撤位踩穩', '0.618 斐波', '2650.50', '已收長下影線', 'primary', 0, 0)", (default_user_id, w_tab_id, p2_id))
            cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, '反向一票否決', '阻力檢查', 'R = 0', '上方無密集籌碼阻礙', 'primary', 0, 1)", (default_user_id, w_tab_id, p2_id))

        conn.commit()

init_db()

def get_current_user_id(authorization: str = Header(None)) -> int:
    if not authorization:
        raise HTTPException(status_code=401, detail="未授權，請先登入")
    token = authorization.replace("Bearer ", "").strip()
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE token = ?", (token,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="無效或已過期的 Token")
        return user[0]

# --- Pydantic 模型 ---
class UserAuth(BaseModel):
    username: str
    password: str

class TabCreate(BaseModel):
    name: str
    tab_type: str = "matrix"

class TabUpdate(BaseModel):
    name: str

class TabReorder(BaseModel):
    ordered_ids: List[int]

class TabPageCreate(BaseModel):
    title: str = "新頁面"

class TabPageUpdate(BaseModel):
    title: str

class ItemCreate(BaseModel):
    tab_id: int
    page_id: Optional[int] = 0
    title: str = ""
    field1: Optional[str] = ""
    field2: Optional[str] = ""
    field3: Optional[str] = ""
    category: str = "primary"

class ItemUpdate(BaseModel):
    title: Optional[str] = None
    field1: Optional[str] = None
    field2: Optional[str] = None
    field3: Optional[str] = None

class ItemReorder(BaseModel):
    ordered_ids: List[int]

class BadgeCreate(BaseModel):
    field1: str = ""
    field2: str = ""
    status: str = "green"
    label_green: str = "升"
    label_red: str = "跌"
    label_gray: str = "平"

class BadgeUpdate(BaseModel):
    field1: str = None
    field2: str = None
    status: str = None
    label_green: str = None
    label_red: str = None
    label_gray: str = None

class BadgeReorder(BaseModel):
    ordered_ids: List[int]

# --- 認證路由 ---
@app.post("/api/auth/register")
def register(payload: UserAuth):
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(status_code=400, detail="用戶名及密碼不能為空")
    
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="此用戶名已被註冊")
        
        token = secrets.token_hex(16)
        cursor.execute("INSERT INTO users (username, password_hash, token) VALUES (?, ?, ?)",
                       (username, hash_password(payload.password), token))
        user_id = cursor.lastrowid
        
        cursor.execute("INSERT INTO tabs (user_id, name, sort_order, tab_type) VALUES (?, 'SOP流程導引', 0, 'wizard')", (user_id,))
        w_tab_id = cursor.lastrowid
        cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, '第 1 頁：大趨勢確認', 0)", (user_id, w_tab_id))
        p1_id = cursor.lastrowid
        cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, '日線趨勢', 'EMA 排列', '20 > 50', '多頭順勢中', 'primary', 0, 0)", (user_id, w_tab_id, p1_id))
        
        cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, '第 2 頁：結構與信號驗證', 1)", (user_id, w_tab_id))
        p2_id = cursor.lastrowid
        cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, '回撤位踩穩', '0.618 斐波', '2650.50', '已收長下影線', 'primary', 0, 0)", (user_id, w_tab_id, p2_id))
        cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, '反向一票否決', '阻力檢查', 'R = 0', '上方無密集籌碼阻礙', 'primary', 0, 1)", (user_id, w_tab_id, p2_id))

        cursor.execute("INSERT INTO tabs (user_id, name, sort_order, tab_type) VALUES (?, '矩陣清單', 1, 'matrix')", (user_id,))
        m_tab_id = cursor.lastrowid
        cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, category, is_active, sort_order) VALUES (?, ?, 0, '主要條件項目 A', 'primary', 0, 0)", (user_id, m_tab_id))
        cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, category, is_active, sort_order) VALUES (?, ?, 0, '次要輔助項目 B', 'secondary', 0, 0)", (user_id, m_tab_id))
        cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, category, is_active, sort_order) VALUES (?, ?, 0, '反向警戒項目 C', 'reverse', 0, 0)", (user_id, m_tab_id))

        cursor.execute("INSERT INTO header_badges (user_id, field1, field2, status, label_green, label_red, label_gray, sort_order) VALUES (?, '指標1', 'Normal', 'green', '升', '跌', '平', 0)", (user_id,))
        conn.commit()
        
    return {"token": token, "username": username}

@app.post("/api/auth/login")
def login(payload: UserAuth):
    username = payload.username.strip()
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user or user[1] != hash_password(payload.password):
            raise HTTPException(status_code=401, detail="用戶名或密碼不正確")
        
        token = secrets.token_hex(16)
        cursor.execute("UPDATE users SET token = ? WHERE id = ?", (token, user[0]))
        conn.commit()
    return {"token": token, "username": username}

# --- Tabs 路由 ---
@app.get("/api/tabs")
def get_tabs(authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tabs WHERE user_id = ? ORDER BY sort_order ASC, id ASC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/tabs")
def add_tab(payload: TabCreate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    name = payload.name.strip() or ("SOP流程導引" if payload.tab_type == "wizard" else "新分頁")
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tabs WHERE user_id = ?", (user_id,))
        next_order = cursor.fetchone()[0]
        cursor.execute("INSERT INTO tabs (user_id, name, sort_order, tab_type) VALUES (?, ?, ?, ?)", (user_id, name, next_order, payload.tab_type))
        new_tab_id = cursor.lastrowid
        
        if payload.tab_type == "wizard":
            cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, '第 1 頁', 0)", (user_id, new_tab_id))
            
        conn.commit()
        return {"id": new_tab_id, "name": name, "sort_order": next_order, "tab_type": payload.tab_type}

@app.post("/api/tabs/{tab_id}/duplicate")
def duplicate_tab(tab_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, sort_order, tab_type FROM tabs WHERE id = ? AND user_id = ?", (tab_id, user_id))
        source_tab = cursor.fetchone()
        if not source_tab:
            raise HTTPException(status_code=404, detail="找不到原分頁")
        
        src_name, src_order, tab_type = source_tab
        new_name = f"{src_name} (副本)"
        
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM tabs WHERE user_id = ?", (user_id,))
        next_order = cursor.fetchone()[0]
        cursor.execute("INSERT INTO tabs (user_id, name, sort_order, tab_type) VALUES (?, ?, ?, ?)", (user_id, new_name, next_order, tab_type))
        new_tab_id = cursor.lastrowid
        
        if tab_type == "wizard":
            cursor.execute("SELECT id, title, sort_order FROM tab_pages WHERE tab_id = ? AND user_id = ? ORDER BY sort_order ASC, id ASC", (tab_id, user_id))
            pages = cursor.fetchall()
            for p in pages:
                cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, ?, ?)", (user_id, new_tab_id, p[1], p[2]))
                new_page_id = cursor.lastrowid
                cursor.execute("SELECT title, field1, field2, field3, category, sort_order FROM items WHERE tab_id = ? AND page_id = ? AND user_id = ?", (tab_id, p[0], user_id))
                p_items = cursor.fetchall()
                for itm in p_items:
                    cursor.execute("INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                                   (user_id, new_tab_id, new_page_id, itm[0], itm[1], itm[2], itm[3], itm[4], itm[5]))
        else:
            cursor.execute("SELECT title, field1, field2, field3, category, sort_order FROM items WHERE tab_id = ? AND user_id = ? ORDER BY sort_order ASC, id ASC", (tab_id, user_id))
            source_items = cursor.fetchall()
            for item in source_items:
                cursor.execute(
                    "INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) VALUES (?, ?, 0, ?, ?, ?, ?, ?, 0, ?)",
                    (user_id, new_tab_id, item[0], item[1], item[2], item[3], item[4], item[5])
                )
        
        conn.commit()
        return {"id": new_tab_id, "name": new_name, "sort_order": next_order, "tab_type": tab_type}

@app.put("/api/tabs/reorder")
def reorder_tabs(payload: TabReorder, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        for order, tab_id in enumerate(payload.ordered_ids):
            cursor.execute("UPDATE tabs SET sort_order = ? WHERE id = ? AND user_id = ?", (order, tab_id, user_id))
        conn.commit()
    return {"status": "reordered"}

@app.put("/api/tabs/{tab_id}")
def update_tab(tab_id: int, payload: TabUpdate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tabs SET name = ? WHERE id = ? AND user_id = ?", (name, tab_id, user_id))
        conn.commit()
    return {"status": "success"}

@app.delete("/api/tabs/{tab_id}")
def delete_tab(tab_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tabs WHERE user_id = ?", (user_id,))
        if cursor.fetchone()[0] <= 1:
            raise HTTPException(status_code=400, detail="不能刪除最後一個分頁")
        cursor.execute("DELETE FROM tab_pages WHERE tab_id = ? AND user_id = ?", (tab_id, user_id))
        cursor.execute("DELETE FROM items WHERE tab_id = ? AND user_id = ?", (tab_id, user_id))
        cursor.execute("DELETE FROM tabs WHERE id = ? AND user_id = ?", (tab_id, user_id))
        conn.commit()
    return {"status": "success"}

# --- Tab Pages 路由 ---
@app.get("/api/tabs/{tab_id}/pages")
def get_tab_pages(tab_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM tab_pages WHERE tab_id = ? AND user_id = ? ORDER BY sort_order ASC, id ASC", (tab_id, user_id)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/tabs/{tab_id}/pages")
def add_tab_page(tab_id: int, payload: TabPageCreate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1, COUNT(*) + 1 FROM tab_pages WHERE tab_id = ? AND user_id = ?", (tab_id, user_id))
        row = cursor.fetchone()
        next_order = row[0]
        page_num = row[1]
        title = payload.title.strip() if payload.title.strip() != "新頁面" else f"第 {page_num} 頁"
        cursor.execute("INSERT INTO tab_pages (user_id, tab_id, title, sort_order) VALUES (?, ?, ?, ?)", (user_id, tab_id, title, next_order))
        conn.commit()
        return {"id": cursor.lastrowid, "tab_id": tab_id, "title": title, "sort_order": next_order}

@app.put("/api/tab_pages/{page_id}")
def update_tab_page(page_id: int, payload: TabPageUpdate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title cannot be empty")
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE tab_pages SET title = ? WHERE id = ? AND user_id = ?", (title, page_id, user_id))
        conn.commit()
    return {"status": "success"}

@app.delete("/api/tab_pages/{page_id}")
def delete_tab_page(page_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT tab_id FROM tab_pages WHERE id = ? AND user_id = ?", (page_id, user_id))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Page not found")
        tab_id = row[0]
        cursor.execute("SELECT COUNT(*) FROM tab_pages WHERE tab_id = ? AND user_id = ?", (tab_id, user_id))
        if cursor.fetchone()[0] <= 1:
            raise HTTPException(status_code=400, detail="至少需保留一個步驟頁面")
        cursor.execute("DELETE FROM items WHERE page_id = ? AND user_id = ?", (page_id, user_id))
        cursor.execute("DELETE FROM tab_pages WHERE id = ? AND user_id = ?", (page_id, user_id))
        conn.commit()
    return {"status": "success"}

# --- Master Badges 路由 ---
@app.get("/api/badges")
def get_badges(authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM header_badges WHERE user_id = ? ORDER BY sort_order ASC, id ASC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/badges")
def add_badge(badge: BadgeCreate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    try:
        with sqlite3.connect("items.db") as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM header_badges WHERE user_id = ?", (user_id,))
            next_order = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO header_badges (user_id, field1, field2, status, label_green, label_red, label_gray, sort_order) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, badge.field1, badge.field2, badge.status, badge.label_green, badge.label_red, badge.label_gray, next_order)
            )
            conn.commit()
            new_id = cursor.lastrowid
            return {
                "id": new_id,
                "user_id": user_id,
                "field1": badge.field1,
                "field2": badge.field2,
                "status": badge.status,
                "label_green": badge.label_green,
                "label_red": badge.label_red,
                "label_gray": badge.label_gray,
                "sort_order": next_order
            }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.put("/api/badges/reorder")
def reorder_badges(payload: BadgeReorder, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        for order, badge_id in enumerate(payload.ordered_ids):
            cursor.execute("UPDATE header_badges SET sort_order = ? WHERE id = ? AND user_id = ?", (order, badge_id, user_id))
        conn.commit()
    return {"status": "badges_reordered"}

@app.put("/api/badges/{badge_id}")
def update_badge(badge_id: int, payload: BadgeUpdate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if payload.field1 is not None:
            updates.append("field1 = ?")
            params.append(payload.field1)
        if payload.field2 is not None:
            updates.append("field2 = ?")
            params.append(payload.field2)
        if payload.status is not None:
            updates.append("status = ?")
            params.append(payload.status)
        if payload.label_green is not None:
            updates.append("label_green = ?")
            params.append(payload.label_green)
        if payload.label_red is not None:
            updates.append("label_red = ?")
            params.append(payload.label_red)
        if payload.label_gray is not None:
            updates.append("label_gray = ?")
            params.append(payload.label_gray)
        
        if updates:
            params.extend([badge_id, user_id])
            cursor.execute(f"UPDATE header_badges SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
            conn.commit()
    return {"status": "success"}

@app.delete("/api/badges/{badge_id}")
def delete_badge(badge_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM header_badges WHERE id = ? AND user_id = ?", (badge_id, user_id))
        conn.commit()
    return {"status": "success"}

# --- Checklist Items 路由 ---
@app.get("/api/items")
def get_items(authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM items WHERE user_id = ? ORDER BY sort_order ASC, id ASC", (user_id,)).fetchall()
        return [dict(r) for r in rows]

@app.post("/api/items")
def add_item(item: ItemCreate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    cat = item.category if item.category in ["primary", "secondary", "reverse"] else "primary"
    page_id = item.page_id or 0
    
    title = (item.title or item.field1 or "新項目").strip()
    f1 = (item.field1 or title).strip()
    f2 = (item.field2 or "").strip()
    f3 = (item.field3 or "").strip()

    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM items WHERE user_id = ? AND tab_id = ? AND page_id = ?", (user_id, item.tab_id, page_id))
        next_order = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO items (user_id, tab_id, page_id, title, field1, field2, field3, category, is_active, sort_order) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """, 
            (user_id, item.tab_id, page_id, title, f1, f2, f3, cat, next_order)
        )
        conn.commit()
        return {
            "id": cursor.lastrowid, 
            "tab_id": item.tab_id, 
            "page_id": page_id, 
            "title": title, 
            "field1": f1,
            "field2": f2,
            "field3": f3,
            "category": cat, 
            "is_active": 0, 
            "sort_order": next_order
        }

@app.put("/api/items/reorder")
def reorder_items(payload: ItemReorder, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        for order, item_id in enumerate(payload.ordered_ids):
            cursor.execute("UPDATE items SET sort_order = ? WHERE id = ? AND user_id = ?", (order, item_id, user_id))
        conn.commit()
    return {"status": "items_reordered"}

@app.put("/api/items/{item_id}")
def update_item_fields(item_id: int, payload: ItemUpdate, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        updates = []
        params = []
        if payload.title is not None:
            updates.append("title = ?")
            params.append(payload.title.strip())
        if payload.field1 is not None:
            updates.append("field1 = ?")
            params.append(payload.field1.strip())
            updates.append("title = ?")
            params.append(payload.field1.strip())
        if payload.field2 is not None:
            updates.append("field2 = ?")
            params.append(payload.field2.strip())
        if payload.field3 is not None:
            updates.append("field3 = ?")
            params.append(payload.field3.strip())

        if updates:
            params.extend([item_id, user_id])
            cursor.execute(f"UPDATE items SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
            conn.commit()
    return {"status": "success"}

@app.patch("/api/items/{item_id}/toggle")
def toggle_item(item_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE items 
            SET is_active = CASE 
                WHEN is_active = 0 THEN 1
                WHEN is_active = 1 THEN 2
                ELSE 0 
            END 
            WHERE id = ? AND user_id = ?
        """, (item_id, user_id))
        conn.commit()
    return {"status": "success"}

# 專為 Tick 開關設計 (ON = 1, OFF = 0)
@app.patch("/api/items/{item_id}/toggle_tick")
def toggle_item_tick(item_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE items 
            SET is_active = CASE 
                WHEN is_active = 1 THEN 0 
                ELSE 1 
            END 
            WHERE id = ? AND user_id = ?
        """, (item_id, user_id))
        conn.commit()
    return {"status": "success"}

@app.delete("/api/items/{item_id}")
def delete_item(item_id: int, authorization: str = Header(None)):
    user_id = get_current_user_id(authorization)
    with sqlite3.connect("items.db") as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM items WHERE id = ? AND user_id = ?", (item_id, user_id))
        conn.commit()
    return {"status": "success"}

app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)