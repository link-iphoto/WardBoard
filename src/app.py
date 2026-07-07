from __future__ import annotations

import html
import json
import mimetypes
import re
import socket
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
SRC = Path(__file__).resolve().parent
DB_PATH = ROOT / "wardboard.sqlite3"
CONFIG_PATH = ROOT / "wardboard_config.json"


def load_server_config() -> tuple[str, int]:
    config = {"host": "127.0.0.1", "port": 58731}
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update({key: loaded[key] for key in ("host", "port") if key in loaded})
        except (OSError, json.JSONDecodeError):
            pass
    host = str(config.get("host") or "127.0.0.1")
    port = int(config.get("port") or 58731)
    return host, port


WARD_BOARD_HOST, WARD_BOARD_PORT = load_server_config()

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday"]
DAY_LABELS = {
    "monday": "月",
    "tuesday": "火",
    "wednesday": "水",
    "thursday": "木",
    "friday": "金",
}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT NOT NULL,
                bed_number TEXT NOT NULL,
                name TEXT NOT NULL,
                gender TEXT NOT NULL CHECK(gender IN ('male', 'female', 'other')),
                group_name TEXT NOT NULL CHECK(group_name IN ('A', 'B')),
                status TEXT NOT NULL CHECK(status IN ('admitted', 'discharged', 'deceased', 'hidden')),
                is_visible INTEGER NOT NULL DEFAULT 1,
                memo TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS wheelchairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheelchair_no TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('dedicated', 'shared')),
                storage_location TEXT NOT NULL DEFAULT '',
                memo TEXT NOT NULL DEFAULT '',
                is_visible INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day_of_week TEXT NOT NULL CHECK(day_of_week IN ('monday', 'tuesday', 'wednesday', 'thursday', 'friday')),
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                wheelchair_id INTEGER NOT NULL REFERENCES wheelchairs(id),
                start_slot INTEGER NOT NULL CHECK(start_slot >= 0 AND start_slot < 28),
                end_slot INTEGER NOT NULL CHECK(end_slot > 0 AND end_slot <= 28),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(end_slot > start_slot)
            );
            CREATE TABLE IF NOT EXISTS ward_settings (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                ward_name TEXT NOT NULL DEFAULT '○○病棟 3階',
                total_beds INTEGER NOT NULL DEFAULT 58,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT OR IGNORE INTO ward_settings(id) VALUES(1);
            """
        )
        if conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 0:
            seed(conn)
        conn.execute(
            """
            UPDATE assignments
            SET start_slot = 0, end_slot = 28, updated_at = CURRENT_TIMESTAMP
            WHERE wheelchair_id IN (SELECT id FROM wheelchairs WHERE kind = 'dedicated')
            """
        )


def seed(conn: sqlite3.Connection) -> None:
    patients = [
        ("301", "1", "山田 太郎", "male", "A", "admitted", 1, "リハビリ中"),
        ("301", "2", "佐藤 花子", "female", "A", "admitted", 1, "車椅子専用"),
        ("302", "1", "鈴木 一郎", "male", "A", "admitted", 1, ""),
        ("302", "2", "田中 裕子", "female", "A", "admitted", 1, "食事見守り"),
        ("302", "3", "高橋 次郎", "male", "B", "admitted", 1, ""),
        ("302", "4", "伊藤 美咲", "female", "B", "admitted", 1, "認知症ケア"),
        ("303", "1", "渡辺 三郎", "male", "B", "admitted", 1, ""),
        ("305", "1", "中村 明子", "female", "A", "admitted", 1, ""),
        ("306", "1", "小林 健一", "male", "B", "admitted", 1, "毎食"),
        ("307", "1", "加藤 幸子", "female", "A", "admitted", 1, "毎食"),
    ]
    conn.executemany(
        """
        INSERT INTO patients(room_number, bed_number, name, gender, group_name, status, is_visible, memo)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        patients,
    )
    wheelchairs = [
        ("01", "山田さん専用", "dedicated", "301-1 前", "専用クッション"),
        ("02", "リハビリ用1号車", "shared", "リハビリ室前", "軽量タイプ"),
        ("03", "リハビリ用2号車", "shared", "リハビリ室前", "多機能タイプ"),
        ("04", "食事用1号車", "shared", "食堂入口", "食事用テーブル付き"),
        ("05", "共用車椅子A", "shared", "ナースステーション横", "クッション付き"),
        ("06", "共用車椅子B", "shared", "デイルーム前", "ノーパンクタイヤ"),
        ("07", "シャワー用車椅子", "shared", "浴室前", "防水仕様"),
    ]
    conn.executemany(
        "INSERT INTO wheelchairs(wheelchair_no, name, kind, storage_location, memo) VALUES(?, ?, ?, ?, ?)",
        wheelchairs,
    )
    assignments = [
        ("monday", 1, 1, 3, 16, ""),
        ("monday", 3, 2, 1, 5, ""),
        ("monday", 2, 2, 6, 11, ""),
        ("monday", 5, 2, 13, 19, ""),
        ("monday", 4, 3, 3, 8, ""),
        ("monday", 6, 3, 9, 14, ""),
        ("monday", 7, 4, 1, 5, ""),
        ("monday", 8, 4, 9, 13, ""),
        ("monday", 2, 6, 20, 24, ""),
        ("monday", 7, 6, 12, 20, ""),
        ("monday", 3, 7, 6, 12, ""),
        ("monday", 4, 7, 15, 21, ""),
        ("tuesday", 1, 1, 3, 16, ""),
        ("tuesday", 8, 4, 8, 12, ""),
        ("tuesday", 4, 7, 14, 20, ""),
        ("wednesday", 1, 1, 3, 16, ""),
        ("wednesday", 2, 2, 4, 10, ""),
        ("thursday", 2, 2, 4, 10, ""),
        ("friday", 1, 1, 3, 16, ""),
    ]
    conn.executemany(
        "INSERT INTO assignments(day_of_week, patient_id, wheelchair_id, start_slot, end_slot, note) VALUES(?, ?, ?, ?, ?, ?)",
        assignments,
    )


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def normalize_patient_name(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("　", " ")).strip()


def validate_patient_name(value: str) -> tuple[str, str]:
    normalized = normalize_patient_name(value)
    if " " not in normalized:
        return normalized, "姓と名の間にスペースを入れてください。例：松本 八重子"
    parts = [part for part in normalized.split(" ") if part]
    if len(parts) < 2:
        return normalized, "姓と名の間にスペースを入れてください。例：松本 八重子"
    return " ".join(parts), ""


def rows(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with db() as conn:
        return conn.execute(query, params).fetchall()


def row(query: str, params: tuple = ()) -> sqlite3.Row | None:
    with db() as conn:
        return conn.execute(query, params).fetchone()


def visible_patients() -> list[sqlite3.Row]:
    return rows(
        """
        SELECT id, room_number, bed_number, room_number || '-' || bed_number AS bed_label,
               name, gender, group_name, status, memo
        FROM patients
        WHERE is_visible = 1 AND status = 'admitted'
        ORDER BY CAST(room_number AS INTEGER), room_number, CAST(bed_number AS INTEGER), bed_number
        """
    )


def visible_wheelchairs() -> list[sqlite3.Row]:
    return rows(
        """
        SELECT id, wheelchair_no, name, kind, storage_location, memo
        FROM wheelchairs
        WHERE is_visible = 1
        ORDER BY CAST(wheelchair_no AS INTEGER), wheelchair_no
        """
    )


def assignments_for_day(day: str) -> list[sqlite3.Row]:
    return rows(
        """
        SELECT a.id, a.day_of_week, a.patient_id, a.wheelchair_id, a.start_slot, a.end_slot, a.note,
               p.room_number, p.bed_number, p.room_number || '-' || p.bed_number AS bed_label,
               p.name AS patient_name, p.gender, p.group_name,
               p.status AS patient_status, p.is_visible AS patient_is_visible,
               w.wheelchair_no, w.name AS wheelchair_name, w.kind AS wheelchair_kind
        FROM assignments a
        JOIN patients p ON p.id = a.patient_id
        JOIN wheelchairs w ON w.id = a.wheelchair_id
        WHERE a.day_of_week = ?
        ORDER BY w.wheelchair_no, a.start_slot, p.room_number, p.bed_number
        """,
        (day,),
    )


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def validate_assignments(items: list[dict]) -> list[str]:
    errors: list[str] = []
    patient_ids = {int(r["id"]) for r in rows("SELECT id FROM patients")}
    wheelchair_ids = {int(r["id"]) for r in rows("SELECT id FROM wheelchairs")}
    by_wheelchair: dict[int, list[tuple[int, int]]] = {}
    by_patient: dict[int, list[tuple[int, int]]] = {}
    for index, item in enumerate(items, start=1):
        try:
            patient_id = int(item["patient_id"])
            wheelchair_id = int(item["wheelchair_id"])
            start = int(item["start_slot"])
            end = int(item["end_slot"])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{index}件目の予定データが不正です。")
            continue
        if patient_id not in patient_ids:
            errors.append(f"{index}件目の患者が見つかりません。")
        if wheelchair_id not in wheelchair_ids:
            errors.append(f"{index}件目の車椅子が見つかりません。")
        if start < 0 or end > 28 or end <= start:
            errors.append(f"{index}件目の時刻範囲が不正です。")
        for old_start, old_end in by_wheelchair.setdefault(wheelchair_id, []):
            if overlaps(start, end, old_start, old_end):
                errors.append("同じ車椅子の時間帯が重複しています。")
                break
        by_wheelchair[wheelchair_id].append((start, end))
        for old_start, old_end in by_patient.setdefault(patient_id, []):
            if overlaps(start, end, old_start, old_end):
                errors.append("同じ患者が同じ時間帯に複数の車椅子へ配置されています。")
                break
        by_patient[patient_id].append((start, end))
    return list(dict.fromkeys(errors))


def normalize_assignment_items(items: list[dict]) -> list[dict]:
    wheelchair_kinds = {int(r["id"]): r["kind"] for r in rows("SELECT id, kind FROM wheelchairs")}
    normalized: list[dict] = []
    for item in items:
        next_item = dict(item)
        try:
            wheelchair_id = int(next_item["wheelchair_id"])
        except (KeyError, TypeError, ValueError):
            normalized.append(next_item)
            continue
        if wheelchair_kinds.get(wheelchair_id) == "dedicated":
            next_item["start_slot"] = 0
            next_item["end_slot"] = 28
        normalized.append(next_item)
    return normalized


def slot_to_time(slot: int) -> str:
    minutes = 6 * 60 + slot * 30
    return f"{minutes // 60}:{minutes % 60:02d}"


def layout(active: str, title: str, subtitle: str, body: str, actions: str = "") -> bytes:
    nav = {
        "timeline": "/timeline",
        "patients": "/patients",
        "wheelchairs": "/wheelchairs",
        "print": "/print",
    }
    labels = {
        "timeline": "▣ タイムライン",
        "patients": "○ 患者情報",
        "wheelchairs": "♿ 車椅子情報",
        "print": "▤ 印刷",
    }
    links = "".join(f'<a class="{"active" if key == active else ""}" href="{url}">{labels[key]}</a>' for key, url in nav.items())
    html_doc = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WardBoard</title>
  <script>
    (function () {{
      var theme = localStorage.getItem("wardboard-theme") || "light";
      document.documentElement.dataset.theme = theme === "dark" ? "dark" : "light";
    }})();
  </script>
  <link rel="stylesheet" href="/static/styles.css">
</head>
<body>
  <aside class="sidebar">
    <div class="brand"><div class="brand-mark">♿</div><div><div class="brand-name">WardBoard</div><div class="brand-sub">病棟配置ボード</div></div></div>
    <nav class="nav">{links}</nav>
    <div class="ward-card"><div class="muted">病棟情報</div><strong>○○病棟 3階</strong><span>総ベッド数：58床</span></div>
    <div class="theme-card">
      <div class="theme-label">表示モード</div>
      <div class="theme-toggle" role="group" aria-label="表示モード">
        <button type="button" data-theme-choice="light">ライト</button>
        <button type="button" data-theme-choice="dark">ダーク</button>
      </div>
    </div>
    <div class="version">WardBoard v0.1.0</div>
  </aside>
  <main class="main">
    <header class="page-header"><div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div><div class="header-actions">{actions}</div></header>
    {body}
  </main>
  <script src="/static/theme.js?v=dark-mode-1"></script>
</body>
</html>"""
    return html_doc.encode("utf-8")


def render_timeline(query: dict[str, list[str]]) -> bytes:
    day = query.get("day", ["monday"])[0]
    if day not in DAYS:
        day = "monday"
    tabs = "".join(f'<a class="{"active" if item == day else ""}" href="/timeline?day={item}">{DAY_LABELS[item]}</a>' for item in DAYS)
    body = f"""
<section class="toolbar timeline-toolbar">
  <div class="day-tabs" data-current-day="{day}">{tabs}</div>
  <div class="range-tabs" aria-label="表示範囲">
    <span>表示範囲</span>
    <button class="segmented active" id="rangeDaytime" type="button">日中 9:00-17:00</button>
    <button class="segmented" id="rangeFull" type="button">全体 6:00-20:00</button>
  </div>
  <div class="delete-drop" id="deleteDropZone">削除はこちらへドロップ</div>
  <button class="button ghost" id="resetDay">リセット</button>
  <button class="button success" id="saveTimeline">保存する</button>
</section>
<section class="timeline-layout">
  <aside class="patient-panel">
    <h2>患者一覧</h2>
    <label class="search"><span>検索</span><input id="patientSearch" type="search" placeholder="患者名・ベッドで検索..."></label>
    <div class="patient-list" id="patientList"></div>
    <div class="help-card"><strong>使い方</strong><span>患者カードをタイムラインへ置くと1時間の予定になります。</span><span>バーをドラッグして移動、左右の端で伸縮できます。</span><span>保存するまで画面上の仮配置です。</span></div>
  </aside>
  <section class="board-shell">
    <div class="board-header"><div><h2>車椅子乗車タイムライン</h2><span id="saveState">未保存</span></div><div class="view-actions"><button class="segmented active" type="button">タイムライン</button><a class="segmented" href="/print">印刷プレビュー</a></div></div>
    <div class="timeline-scroll" id="timelineScroll"><div class="time-board" id="timeBoard"></div></div>
    <div class="legend"><span><i class="swatch pending"></i>仮配置</span><span><i class="swatch saved"></i>保存済み</span><span><i class="swatch dedicated"></i>専用車椅子</span><span><i class="swatch shared"></i>共用車椅子</span><span><i class="line-sample"></i>30分単位</span></div>
  </section>
</section>
<script src="/static/timeline.js?v=visible-label-3"></script>"""
    actions = '<a class="button secondary" href="/patients">患者マスタ</a><a class="button success" href="/wheelchairs">車椅子マスタ</a><a class="button secondary" href="/print">印刷</a>'
    return layout("timeline", "車椅子乗車タイムライン", "患者を車椅子に配置します", body, actions)


def patient_stats() -> dict[str, int]:
    stats = {"total": 0, "visible": 0, "admitted": 0, "discharged": 0, "deceased": 0, "hidden": 0}
    for item in rows("SELECT status, COUNT(*) AS count FROM patients GROUP BY status"):
        stats[item["status"]] = item["count"]
    stats["total"] = row("SELECT COUNT(*) AS count FROM patients")["count"]
    stats["visible"] = row("SELECT COUNT(*) AS count FROM patients WHERE is_visible = 1")["count"]
    return stats


def wheelchair_stats() -> dict[str, int]:
    stats = {"total": 0, "visible": 0, "dedicated": 0, "shared": 0}
    for item in rows("SELECT kind, COUNT(*) AS count FROM wheelchairs GROUP BY kind"):
        stats[item["kind"]] = item["count"]
    stats["total"] = row("SELECT COUNT(*) AS count FROM wheelchairs")["count"]
    stats["visible"] = row("SELECT COUNT(*) AS count FROM wheelchairs WHERE is_visible = 1")["count"]
    return stats


def render_stats(items: list[tuple[str, str]]) -> str:
    return '<section class="stats-grid">' + "".join(f'<div class="stat"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>' for label, value in items) + "</section>"


def render_patients(query: dict[str, list[str]], error: str = "") -> bytes:
    filters = {key: query.get(key, [""])[0] for key in ["q", "group_name", "status", "visible"]}
    filters["group_name"] = filters["group_name"] or "all"
    filters["visible"] = filters["visible"] or "all"
    sql = "SELECT *, room_number || '-' || bed_number AS bed_label FROM patients WHERE 1 = 1"
    params: list[str] = []
    if filters["q"]:
        sql += " AND (name LIKE ? OR room_number LIKE ? OR bed_number LIKE ? OR memo LIKE ?)"
        like = f"%{filters['q']}%"
        params.extend([like, like, like, like])
    if filters["group_name"] in ("A", "B"):
        sql += " AND group_name = ?"
        params.append(filters["group_name"])
    if filters["visible"] == "visible":
        sql += " AND is_visible = 1"
    elif filters["visible"] == "hidden":
        sql += " AND is_visible = 0"
    sql += " ORDER BY CAST(room_number AS INTEGER), room_number, CAST(bed_number AS INTEGER), bed_number"
    data = rows(sql, tuple(params))
    table_rows = "".join(patient_tr(r, i + 1) for i, r in enumerate(data))
    error_html = f'<div class="message error">{esc(error)}</div>' if error else ""
    body = f"""
{error_html}
<section class="patient-master-page">
  <div class="patient-master-actions">
    <form class="filters patient-master-filters" method="get">
      <input name="q" value="{esc(filters['q'])}" placeholder="患者名・部屋番号・ベッド番号で検索...">
      <select name="group_name">{options(filters['group_name'], [('all','全グループ'),('A','A'),('B','B')])}</select>
      <select name="visible">{options(filters['visible'], [('all','すべて'),('visible','表示中のみ'),('hidden','非表示のみ')])}</select>
      <button class="button primary">絞り込み</button><a class="button ghost" href="/patients">条件クリア</a>
    </form>
    <div class="patient-save-actions">
      <button class="button secondary" type="button" id="addPatientRow">新規患者を追加</button>
      <span id="patientSaveState">変更はありません</span>
      <button class="button success" type="button" id="savePatients" disabled>保存する</button>
    </div>
  </div>
  <div class="table-panel patient-table-panel">
    <table class="data-table editable-patient-table" id="patientMasterTable">
      <thead><tr><th>グループ</th><th>部屋番号</th><th>ベッド番号</th><th>氏名</th><th>性別</th><th>メモ</th><th>表示ON/OFF</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</section>
<script src="/static/masters.js?v=master-unified-1"></script>"""
    return layout("patients", "患者マスタ", "患者情報を登録・編集します", body, '<a class="button success" href="/timeline">タイムラインへ</a>')


def patient_tr(r: sqlite3.Row, index: int) -> str:
    row_class = "" if r["is_visible"] else "is-hidden"
    return f"""<tr class="{row_class}" data-id="{r['id']}">
<td><select data-field="group_name" data-original="{esc(r['group_name'])}"><option value="A" {"selected" if r["group_name"] == "A" else ""}>A</option><option value="B" {"selected" if r["group_name"] == "B" else ""}>B</option></select></td>
<td><input data-field="room_number" data-original="{esc(r['room_number'])}" value="{esc(r['room_number'])}"></td>
<td><input data-field="bed_number" data-original="{esc(r['bed_number'])}" value="{esc(r['bed_number'])}"></td>
<td><input data-field="name" data-original="{esc(r['name'])}" value="{esc(r['name'])}"><small class="field-error"></small></td>
<td><select data-field="gender" data-original="{esc(r['gender'])}"><option value="male" {"selected" if r["gender"] == "male" else ""}>男</option><option value="female" {"selected" if r["gender"] == "female" else ""}>女</option></select></td>
<td><input class="memo-input" data-field="memo" data-original="{esc(r['memo'])}" value="{esc(r['memo'])}"></td>
<td><label class="toggle-cell"><input type="checkbox" data-field="is_visible" data-original="{1 if r['is_visible'] else 0}" {"checked" if r["is_visible"] else ""}><span>{"ON" if r["is_visible"] else "OFF"}</span></label></td>
</tr>"""


def patient_form() -> str:
    return """
<form class="edit-panel" method="post" action="/patients" id="patientForm">
  <h2 id="patientFormTitle">新規患者を追加</h2><input type="hidden" name="patient_id" id="patient_id">
  <label>部屋番号<input name="room_number" id="room_number" required></label>
  <label>ベッド番号<input name="bed_number" id="bed_number" required></label>
  <label>氏名<input name="name" id="name" required><small class="field-error" id="nameError"></small></label>
  <label>性別<select name="gender" id="gender"><option value="male">男性</option><option value="female">女性</option><option value="other">その他</option></select></label>
  <label>グループ<select name="group_name" id="group_name"><option value="A">A</option><option value="B">B</option></select></label>
  <label>状態<select name="status" id="status"><option value="admitted">入院中</option><option value="discharged">退院</option><option value="deceased">死亡</option><option value="hidden">非表示</option></select></label>
  <label class="check"><input type="checkbox" name="is_visible" id="is_visible" checked> 表示ON</label>
  <label>メモ<textarea name="memo" id="memo" rows="3"></textarea></label>
  <div class="form-actions"><button class="button success">保存</button><button class="button ghost" type="button" id="clearPatientForm">クリア</button></div>
</form>"""


def render_wheelchairs(query: dict[str, list[str]]) -> bytes:
    filters = {key: query.get(key, [""])[0] for key in ["q", "kind", "visible"]}
    filters["kind"] = filters["kind"] or "all"
    filters["visible"] = filters["visible"] or "all"
    sql = "SELECT * FROM wheelchairs WHERE 1 = 1"
    params: list[str] = []
    if filters["q"]:
        sql += " AND (wheelchair_no LIKE ? OR name LIKE ? OR storage_location LIKE ? OR memo LIKE ?)"
        like = f"%{filters['q']}%"
        params.extend([like, like, like, like])
    if filters["kind"] in ("dedicated", "shared"):
        sql += " AND kind = ?"
        params.append(filters["kind"])
    if filters["visible"] == "visible":
        sql += " AND is_visible = 1"
    elif filters["visible"] == "hidden":
        sql += " AND is_visible = 0"
    sql += " ORDER BY CAST(wheelchair_no AS INTEGER), wheelchair_no"
    data = rows(sql, tuple(params))
    table_rows = "".join(wheelchair_tr(r, i + 1) for i, r in enumerate(data))
    body = f"""
<section class="master-page">
  <div class="master-actions">
  <form class="filters master-filters" method="get">
    <input name="q" value="{esc(filters['q'])}" placeholder="車椅子No・名称・保管場所で検索...">
    <select name="kind">{options(filters['kind'], [('all','全種別'),('dedicated','専用'),('shared','共用')])}</select>
    <select name="visible">{options(filters['visible'], [('all','すべて'),('visible','表示中のみ'),('hidden','非表示のみ')])}</select>
    <button class="button primary">絞り込み</button><a class="button ghost" href="/wheelchairs">条件クリア</a>
  </form>
    <div class="master-save-actions">
      <button class="button secondary" type="button" id="addWheelchairRow">新規車椅子を追加</button>
      <span id="wheelchairSaveState">変更はありません</span>
      <button class="button success" type="button" id="saveWheelchairs" disabled>保存する</button>
    </div>
  </div>
  <div class="table-panel master-table-panel">
    <table class="data-table editable-master-table wheelchair-master-table" id="wheelchairMasterTable">
      <thead><tr><th>車椅子No</th><th>名称</th><th>種別</th><th>保管場所</th><th>メモ</th><th>表示ON/OFF</th></tr></thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>
</section>
<script src="/static/masters.js?v=master-unified-1"></script>"""
    return layout("wheelchairs", "車椅子マスタ", "車椅子情報を登録・編集します", body, '<a class="button success" href="/timeline">タイムラインへ</a>')


def wheelchair_tr(r: sqlite3.Row, index: int) -> str:
    row_class = "" if r["is_visible"] else "is-hidden"
    return f"""<tr class="{row_class}" data-id="{r['id']}">
<td><input data-field="wheelchair_no" data-original="{esc(r['wheelchair_no'])}" value="{esc(r['wheelchair_no'])}"></td>
<td><input data-field="name" data-original="{esc(r['name'])}" value="{esc(r['name'])}"></td>
<td><select data-field="kind" data-original="{esc(r['kind'])}"><option value="shared" {"selected" if r["kind"] == "shared" else ""}>共用</option><option value="dedicated" {"selected" if r["kind"] == "dedicated" else ""}>専用</option></select></td>
<td><input data-field="storage_location" data-original="{esc(r['storage_location'])}" value="{esc(r['storage_location'])}"></td>
<td><input class="memo-input" data-field="memo" data-original="{esc(r['memo'])}" value="{esc(r['memo'])}"></td>
<td><label class="toggle-cell"><input type="checkbox" data-field="is_visible" data-original="{1 if r['is_visible'] else 0}" {"checked" if r["is_visible"] else ""}><span>{"ON" if r["is_visible"] else "OFF"}</span></label></td>
</tr>"""


def wheelchair_form() -> str:
    return """
<form class="edit-panel" method="post" action="/wheelchairs" id="wheelchairForm">
  <h2 id="wheelchairFormTitle">新規車椅子を追加</h2><input type="hidden" name="wheelchair_id" id="wheelchair_id">
  <label>車椅子No<input name="wheelchair_no" id="wheelchair_no" required></label>
  <label>名称<input name="name" id="wc_name" required></label>
  <label>種別<select name="kind" id="kind"><option value="shared">共用</option><option value="dedicated">専用</option></select></label>
  <label>保管場所<input name="storage_location" id="storage_location"></label>
  <label>メモ<textarea name="memo" id="wc_memo" rows="3"></textarea></label>
  <label class="check"><input type="checkbox" name="is_visible" id="wc_is_visible" checked> 表示ON</label>
  <div class="form-actions"><button class="button success">保存</button><button class="button ghost" type="button" id="clearWheelchairForm">クリア</button></div>
</form>"""


def options(current: str, values: list[tuple[str, str]]) -> str:
    return "".join(f'<option value="{esc(value)}" {"selected" if current == value else ""}>{esc(label)}</option>' for value, label in values)


def build_weekly_print() -> dict:
    week: dict[str, dict] = {}
    all_items: list[dict] = []
    for day in DAYS:
        data = [dict(item) for item in assignments_for_day(day)]
        for item in data:
            item["start_time"] = slot_to_time(item["start_slot"])
            item["end_time"] = slot_to_time(item["end_slot"])
            all_items.append(item)
        week[day] = {
            "morning": sorted([i for i in data if i["start_slot"] < 12], key=lambda x: (x["start_slot"], x["room_number"], x["bed_number"])),
            "later": sorted([i for i in data if i["start_slot"] >= 12], key=lambda x: (x["start_slot"], x["room_number"], x["bed_number"])),
        }
    day_count: dict[int, set[str]] = {}
    patient_row: dict[int, dict] = {}
    always: dict[int, dict] = {}
    for item in all_items:
        day_count.setdefault(item["patient_id"], set()).add(item["day_of_week"])
        patient_row[item["patient_id"]] = item
        if item["start_slot"] <= 1 and item["end_slot"] >= 26:
            always[item["patient_id"]] = item
    return {
        "days": week,
        "every_meal": [patient_row[pid] for pid, day_set in day_count.items() if len(day_set) >= 3],
        "always_up": list(always.values()),
    }


def render_print() -> bytes:
    weekly = build_weekly_print()
    cards = []
    for day in DAYS:
        morning = weekly["days"][day]["morning"]
        later = weekly["days"][day]["later"]
        count = max(len(morning), len(later), 1)
        trs = []
        for i in range(count):
            m = morning[i] if i < len(morning) else None
            l = later[i] if i < len(later) else None
            trs.append(f"<tr><td>{esc(m['bed_label'] + '　' + m['patient_name']) if m else ''}</td><td>{esc(l['start_time'] + '　' + l['bed_label'] + '　' + l['patient_name'] + '　' + l['wheelchair_name']) if l else ''}</td><td>{esc(l['end_time'] if l else m['end_time'] if m else '')}</td></tr>")
        cards.append(f'<section class="print-card"><h2>{DAY_LABELS[day]}曜日の離床表</h2><table><thead><tr><th>現在起きている人</th><th>これから起こす人</th><th>戻す時間</th></tr></thead><tbody>{"".join(trs)}</tbody></table></section>')
    always_rows = "".join(f"<tr><td>{esc(i['bed_label'] + '　' + i['patient_name'])}</td><td>{esc(i['note'])}</td></tr>" for i in weekly["always_up"]) or "<tr><td>なし</td><td></td></tr>"
    meal_rows = "".join(f"<tr><td>{esc(i['patient_name'])}</td><td>{esc(i['bed_label'])}</td></tr>" for i in weekly["every_meal"]) or "<tr><td>なし</td><td></td></tr>"
    cards.append(f'<section class="print-card list-card"><h2>常時起きる人・毎食起きる人一覧</h2><div class="two-col"><table><thead><tr><th>常時起きる人</th><th>備考</th></tr></thead><tbody>{always_rows}</tbody></table><table><thead><tr><th>毎食起きる人</th><th>部屋</th></tr></thead><tbody>{meal_rows}</tbody></table></div></section>')
    body = f'<section class="print-sheet"><div class="print-title">離床表（週間予定）</div><div class="print-grid">{"".join(cards)}</div></section>'
    return layout("print", "印刷", "月〜金の予定から離床表を生成します", body, '<button class="button primary" onclick="window.print()">印刷する</button>')


class WardBoardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/":
            self.redirect("/timeline")
        elif parsed.path == "/timeline":
            self.html(render_timeline(query))
        elif parsed.path == "/patients":
            self.html(render_patients(query))
        elif parsed.path == "/wheelchairs":
            self.html(render_wheelchairs(query))
        elif parsed.path == "/print":
            self.html(render_print())
        elif parsed.path == "/api/bootstrap":
            self.json({
                "days": DAYS,
                "dayLabels": DAY_LABELS,
                "patients": [dict(item) for item in visible_patients()],
                "wheelchairs": [dict(item) for item in visible_wheelchairs()],
            })
        elif parsed.path.startswith("/api/assignments/"):
            day = parsed.path.rsplit("/", 1)[-1]
            if day not in DAYS:
                self.json({"error": "invalid day"}, HTTPStatus.BAD_REQUEST)
            else:
                self.json({"assignments": [dict(item) for item in assignments_for_day(day)]})
        elif parsed.path.startswith("/static/"):
            self.static(parsed.path.removeprefix("/static/"))
        else:
            self.error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/assignments/"):
            day = parsed.path.rsplit("/", 1)[-1]
            self.save_assignments(day)
            return
        if parsed.path == "/api/wheelchairs/bulk":
            self.save_wheelchairs_bulk()
            return
        if parsed.path == "/api/patients/bulk":
            self.save_patients_bulk()
            return
        form = self.read_form()
        if parsed.path == "/patients":
            error = self.save_patient(form)
            if error:
                self.html(render_patients({}, error), HTTPStatus.BAD_REQUEST)
                return
            self.redirect("/patients")
        elif parsed.path == "/patients/toggle":
            with db() as conn:
                conn.execute("UPDATE patients SET is_visible = 1 - is_visible, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(form.get("id", "0")),))
            self.redirect("/patients")
        elif parsed.path == "/patients/hide":
            with db() as conn:
                conn.execute("UPDATE patients SET is_visible = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(form.get("id", "0")),))
            self.redirect("/patients")
        elif parsed.path == "/wheelchairs":
            self.save_wheelchair(form)
            self.redirect("/wheelchairs")
        elif parsed.path == "/wheelchairs/toggle":
            with db() as conn:
                conn.execute("UPDATE wheelchairs SET is_visible = 1 - is_visible, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(form.get("id", "0")),))
            self.redirect("/wheelchairs")
        elif parsed.path == "/wheelchairs/hide":
            with db() as conn:
                conn.execute("UPDATE wheelchairs SET is_visible = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(form.get("id", "0")),))
            self.redirect("/wheelchairs")
        else:
            self.error(HTTPStatus.NOT_FOUND)

    def save_assignments(self, day: str) -> None:
        if day not in DAYS:
            self.json({"error": "invalid day"}, HTTPStatus.BAD_REQUEST)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        items = normalize_assignment_items(payload.get("assignments", []))
        errors = validate_assignments(items)
        if errors:
            self.json({"ok": False, "errors": errors}, HTTPStatus.CONFLICT)
            return
        with db() as conn:
            conn.execute("DELETE FROM assignments WHERE day_of_week = ?", (day,))
            for item in items:
                conn.execute(
                    "INSERT INTO assignments(day_of_week, patient_id, wheelchair_id, start_slot, end_slot, note) VALUES(?, ?, ?, ?, ?, ?)",
                    (day, int(item["patient_id"]), int(item["wheelchair_id"]), int(item["start_slot"]), int(item["end_slot"]), item.get("note", "")),
                )
        self.json({"ok": True, "assignments": [dict(item) for item in assignments_for_day(day)]})

    def save_patients_bulk(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.json({"ok": False, "errors": ["保存データの形式が不正です。"]}, HTTPStatus.BAD_REQUEST)
            return

        items = payload.get("patients", [])
        if not isinstance(items, list):
            self.json({"ok": False, "errors": ["患者データの形式が不正です。"]}, HTTPStatus.BAD_REQUEST)
            return

        normalized: list[dict] = []
        errors: list[str] = []
        existing_ids = {int(r["id"]) for r in rows("SELECT id FROM patients")}
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                errors.append(f"{index}件目の患者データが不正です。")
                continue
            patient_id_raw = str(item.get("id", "") or "").strip()
            patient_id = int(patient_id_raw) if patient_id_raw.isdigit() else None
            if patient_id is not None and patient_id not in existing_ids:
                errors.append(f"{index}件目の患者が見つかりません。")

            group_name = str(item.get("group_name", "A")).strip()
            if group_name not in ("A", "B"):
                errors.append(f"{index}件目のグループはAまたはBを選択してください。")

            gender = str(item.get("gender", "male")).strip()
            if gender not in ("male", "female"):
                errors.append(f"{index}件目の性別は男または女を選択してください。")

            room_number = str(item.get("room_number", "")).strip()
            bed_number = str(item.get("bed_number", "")).strip()
            if not room_number:
                errors.append(f"{index}件目の部屋番号を入力してください。")
            if not bed_number:
                errors.append(f"{index}件目のベッド番号を入力してください。")

            name, name_error = validate_patient_name(str(item.get("name", "")))
            if name_error:
                errors.append(f"{index}件目: {name_error}")

            normalized.append(
                {
                    "client_id": str(item.get("client_id", "") or ""),
                    "id": patient_id,
                    "group_name": group_name,
                    "room_number": room_number,
                    "bed_number": bed_number,
                    "name": name,
                    "gender": gender,
                    "memo": str(item.get("memo", "")).strip(),
                    "is_visible": 1 if item.get("is_visible") in (1, "1", True, "true", "on") else 0,
                }
            )

        if errors:
            self.json({"ok": False, "errors": list(dict.fromkeys(errors))}, HTTPStatus.BAD_REQUEST)
            return

        saved: list[dict] = []
        with db() as conn:
            for item in normalized:
                data = (
                    item["room_number"],
                    item["bed_number"],
                    item["name"],
                    item["gender"],
                    item["group_name"],
                    item["is_visible"],
                    item["memo"],
                )
                if item["id"] is not None:
                    conn.execute(
                        """
                        UPDATE patients
                        SET room_number = ?, bed_number = ?, name = ?, gender = ?, group_name = ?,
                            is_visible = ?, memo = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (*data, item["id"]),
                    )
                    patient_id = item["id"]
                else:
                    cursor = conn.execute(
                        """
                        INSERT INTO patients(room_number, bed_number, name, gender, group_name, status, is_visible, memo)
                        VALUES(?, ?, ?, ?, ?, 'admitted', ?, ?)
                        """,
                        data,
                    )
                    patient_id = int(cursor.lastrowid)
                saved.append({**item, "id": patient_id})

        self.json({"ok": True, "patients": saved, "message": "患者マスタを保存しました"})

    def save_wheelchairs_bulk(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self.json({"ok": False, "errors": ["保存データの形式が不正です。"]}, HTTPStatus.BAD_REQUEST)
            return

        items = payload.get("wheelchairs", [])
        if not isinstance(items, list):
            self.json({"ok": False, "errors": ["車椅子データの形式が不正です。"]}, HTTPStatus.BAD_REQUEST)
            return

        normalized: list[dict] = []
        errors: list[str] = []
        existing_ids = {int(r["id"]) for r in rows("SELECT id FROM wheelchairs")}
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                errors.append(f"{index}件目の車椅子データが不正です。")
                continue
            wheelchair_id_raw = str(item.get("id", "") or "").strip()
            wheelchair_id = int(wheelchair_id_raw) if wheelchair_id_raw.isdigit() else None
            if wheelchair_id is not None and wheelchair_id not in existing_ids:
                errors.append(f"{index}件目の車椅子が見つかりません。")

            wheelchair_no = str(item.get("wheelchair_no", "")).strip()
            name = str(item.get("name", "")).strip()
            kind = str(item.get("kind", "shared")).strip()
            if not wheelchair_no:
                errors.append(f"{index}件目の車椅子Noを入力してください。")
            if not name:
                errors.append(f"{index}件目の名称を入力してください。")
            if kind not in ("shared", "dedicated"):
                errors.append(f"{index}件目の種別は共用または専用を選択してください。")

            normalized.append(
                {
                    "client_id": str(item.get("client_id", "") or ""),
                    "id": wheelchair_id,
                    "wheelchair_no": wheelchair_no,
                    "name": name,
                    "kind": kind,
                    "storage_location": str(item.get("storage_location", "")).strip(),
                    "memo": str(item.get("memo", "")).strip(),
                    "is_visible": 1 if item.get("is_visible") in (1, "1", True, "true", "on") else 0,
                }
            )

        if errors:
            self.json({"ok": False, "errors": list(dict.fromkeys(errors))}, HTTPStatus.BAD_REQUEST)
            return

        saved: list[dict] = []
        try:
            with db() as conn:
                for item in normalized:
                    data = (
                        item["wheelchair_no"],
                        item["name"],
                        item["kind"],
                        item["storage_location"],
                        item["memo"],
                        item["is_visible"],
                    )
                    if item["id"] is not None:
                        conn.execute(
                            """
                            UPDATE wheelchairs
                            SET wheelchair_no = ?, name = ?, kind = ?, storage_location = ?,
                                memo = ?, is_visible = ?, updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                            """,
                            (*data, item["id"]),
                        )
                        wheelchair_id = item["id"]
                    else:
                        cursor = conn.execute(
                            """
                            INSERT INTO wheelchairs(wheelchair_no, name, kind, storage_location, memo, is_visible)
                            VALUES(?, ?, ?, ?, ?, ?)
                            """,
                            data,
                        )
                        wheelchair_id = int(cursor.lastrowid)
                    saved.append({**item, "id": wheelchair_id})
        except sqlite3.IntegrityError:
            self.json({"ok": False, "errors": ["車椅子Noが重複しています。別の番号を入力してください。"]}, HTTPStatus.CONFLICT)
            return

        self.json({"ok": True, "wheelchairs": saved, "message": "車椅子情報を保存しました"})

    def save_patient(self, form: dict[str, str]) -> str:
        name, error = validate_patient_name(form.get("name", ""))
        if error:
            return error
        data = (
            form.get("room_number", "").strip(),
            form.get("bed_number", "").strip(),
            name,
            form.get("gender", "male"),
            form.get("group_name", "A"),
            form.get("status", "admitted"),
            1 if form.get("is_visible") == "on" else 0,
            form.get("memo", "").strip(),
        )
        patient_id = form.get("patient_id", "")
        with db() as conn:
            if patient_id:
                conn.execute(
                    """
                    UPDATE patients SET room_number = ?, bed_number = ?, name = ?, gender = ?, group_name = ?,
                    status = ?, is_visible = ?, memo = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
                    """,
                    (*data, int(patient_id)),
                )
            else:
                conn.execute(
                    "INSERT INTO patients(room_number, bed_number, name, gender, group_name, status, is_visible, memo) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                    data,
                )
        return ""

    def save_wheelchair(self, form: dict[str, str]) -> None:
        data = (
            form.get("wheelchair_no", "").strip(),
            form.get("name", "").strip(),
            form.get("kind", "shared"),
            form.get("storage_location", "").strip(),
            form.get("memo", "").strip(),
            1 if form.get("is_visible") == "on" else 0,
        )
        wheelchair_id = form.get("wheelchair_id", "")
        with db() as conn:
            if wheelchair_id:
                conn.execute(
                    """
                    UPDATE wheelchairs SET wheelchair_no = ?, name = ?, kind = ?, storage_location = ?,
                    memo = ?, is_visible = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
                    """,
                    (*data, int(wheelchair_id)),
                )
            else:
                conn.execute(
                    "INSERT INTO wheelchairs(wheelchair_no, name, kind, storage_location, memo, is_visible) VALUES(?, ?, ?, ?, ?, ?)",
                    data,
                )

    def read_form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        parsed = parse_qs(raw)
        return {key: values[0] for key, values in parsed.items()}

    def html(self, data: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def static(self, rel_path: str) -> None:
        path = (SRC / "static" / rel_path).resolve()
        if not path.is_file() or SRC.resolve() not in path.parents:
            self.error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def error(self, status: HTTPStatus) -> None:
        self.send_error(status)

    def log_message(self, format: str, *args: object) -> None:
        return


class WardBoardServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def run(host: str | None = None, port: int | None = None) -> None:
    host = host or WARD_BOARD_HOST
    port = port or WARD_BOARD_PORT
    init_db()
    try:
        server = WardBoardServer((host, port), WardBoardHandler)
    except OSError as exc:
        print(f"ポート {port} は使用中です。WardBoard を起動できません。")
        print("使用中のプロセスを確認してください。")
        raise SystemExit(1) from exc
    print(f"WardBoard running at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
