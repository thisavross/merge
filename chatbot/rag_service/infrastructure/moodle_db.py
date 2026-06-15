"""MySQL access for Moodle course metadata, enrolments, and file extraction."""

from __future__ import annotations

import html
import re
from typing import TYPE_CHECKING

import pymysql

from integrations.ocr_client import extract_moodle_course_file

if TYPE_CHECKING:
    from config import Settings


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _table(name: str, prefix: str) -> str:
    return f"{prefix}{name}"


def _mysql_connect_kwargs(settings: Settings) -> dict:
    """TCP or Unix socket (MAMP often requires socket for same creds as PHP)."""
    kwargs: dict = {
        "user": settings.mysql_user,
        "password": settings.mysql_password,
        "database": settings.mysql_database,
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }
    sock = (getattr(settings, "mysql_unix_socket", "") or "").strip()
    if sock:
        kwargs["unix_socket"] = sock
    else:
        kwargs["host"] = settings.mysql_host
        kwargs["port"] = int(settings.mysql_port)
    return kwargs


def _filedir_path_from_contenthash(settings: Settings, contenthash: str) -> str:
    """
    Moodle file_system_filedir stores binary content at:
      {dataroot}/filedir/<contenthash[0:2]>/<contenthash[2:4]>/<contenthash>
    """
    dataroot = (getattr(settings, "moodle_dataroot", "") or "").strip()
    ch = (contenthash or "").strip()
    if not dataroot or not ch or len(ch) < 4:
        return ""
    return f"{dataroot}/filedir/{ch[0:2]}/{ch[2:4]}/{ch}"


def get_course_meta(settings: Settings, course_id: int) -> tuple[str, int]:
    """Lightweight course row: (fullname, timemodified). No module/file scan."""
    conn = pymysql.connect(**_mysql_connect_kwargs(settings))
    p = settings.mysql_prefix
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT fullname, timemodified FROM {_table('course', p)} WHERE id = %s",
                (course_id,),
            )
            row = cur.fetchone()
            if not row:
                return "", 0
            name = _strip_html(str(row.get("fullname") or "")) or f"Course {course_id}"
            return name, int(row.get("timemodified") or 0)
    finally:
        conn.close()


def load_course_plaintext(
    settings: Settings,
    course_id: int,
    *,
    skip_metadata: bool = True,
) -> tuple[str, int]:
    """Return (plain_text, timemodified) for the course, including extracted course files."""
    conn = pymysql.connect(**_mysql_connect_kwargs(settings))
    p = settings.mysql_prefix

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT id, fullname, shortname, summary, summaryformat, timemodified "
                f"FROM {_table('course', p)} WHERE id = %s",
                (course_id,),
            )
            row = cur.fetchone()
            if not row:
                return "", 0

            parts: list[str] = []
            coursefullname = _strip_html(str(row.get("fullname") or ""))

            if not skip_metadata:
                parts.append(f"Course full name: {coursefullname}")
                parts.append(f"Short name: {_strip_html(str(row.get('shortname') or ''))}")
                summary = row.get("summary") or ""
                if summary:
                    parts.append(f"Course summary: {_strip_html(str(summary))}")

            timemodified = int(row.get("timemodified") or 0)

            if not skip_metadata:
                cur.execute(
                    f"SELECT section, name, summary FROM {_table('course_sections', p)} "
                    f"WHERE course = %s ORDER BY section",
                    (course_id,),
                )

                for sec in cur.fetchall():
                    sn = sec.get("name") or f"Section {sec.get('section')}"
                    parts.append(f"Section {sec.get('section')}: {_strip_html(str(sn))}")
                    if sec.get("summary"):
                        parts.append(_strip_html(str(sec["summary"])))

            cur.execute(f"SELECT name FROM {_table('modules', p)}")
            valid_mods = {r["name"] for r in cur.fetchall()}

            cur.execute(
                f"SELECT cm.instance, m.name AS modname, cm.section "
                f"FROM {_table('course_modules', p)} cm "
                f"JOIN {_table('modules', p)} m ON m.id = cm.module "
                f"WHERE cm.course = %s AND cm.deletioninprogress = 0 AND cm.visible = 1 "
                f"ORDER BY cm.section, cm.id",
                (course_id,),
            )
            for cm in cur.fetchall():
                modname = str(cm["modname"])
                instance = int(cm["instance"])
                label = f"Activity ({modname}) #{instance}"
                if modname in valid_mods:
                    try:
                        cur.execute(
                            f"SELECT name FROM {_table(modname, p)} WHERE id = %s",
                            (instance,),
                        )
                        name_row = cur.fetchone()
                        if name_row and name_row.get("name"):
                            label = f"Activity: {_strip_html(str(name_row['name']))} ({modname})"
                    except pymysql.Error:
                        pass
                if not skip_metadata:
                    parts.append(label)

            if (getattr(settings, "moodle_dataroot", "") or "").strip():
                max_files = int(getattr(settings, "course_file_max_files", 60) or 60)
                max_bytes = int(getattr(settings, "course_file_max_bytes", 8 * 1024 * 1024) or (8 * 1024 * 1024))
                max_chars_per_file = int(getattr(settings, "course_file_max_chars_per_file", 40000) or 40000)
                max_total_chars = int(getattr(settings, "course_file_max_total_chars", 200000) or 200000)

                file_parts: list[str] = []
                extracted_chars = 0
                tm_max = timemodified
                collected_files = 0

                sql_course_ctx = (
                    f"SELECT f.id, f.component, f.filearea, f.filename, f.contenthash, "
                    f"       f.filepath, f.mimetype, f.timemodified, f.filesize "
                    f"  FROM {_table('context', p)} ctx "
                    f"  JOIN {_table('files', p)} f ON f.contextid = ctx.id "
                    f" WHERE ctx.contextlevel = 50 AND ctx.instanceid = %s AND f.filename <> '.' "
                    f" ORDER BY f.timemodified DESC "
                    f" LIMIT %s"
                )
                sql_module_ctx = (
                    f"SELECT f.id, f.component, f.filearea, f.filename, f.contenthash, "
                    f"       f.filepath, f.mimetype, f.timemodified, f.filesize "
                    f"  FROM {_table('course_modules', p)} cm "
                    f"  JOIN {_table('context', p)} ctx ON ctx.instanceid = cm.id AND ctx.contextlevel = 70 "
                    f"  JOIN {_table('files', p)} f ON f.contextid = ctx.id "
                    f" WHERE cm.course = %s AND f.filename <> '.' "
                    f" ORDER BY f.timemodified DESC "
                    f" LIMIT %s"
                )

                file_rows: list[dict] = []
                cur.execute(sql_course_ctx, (course_id, max_files))
                file_rows.extend(cur.fetchall())
                cur.execute(sql_module_ctx, (course_id, max_files))
                file_rows.extend(cur.fetchall())

                file_rows = sorted(file_rows, key=lambda r: int(r.get("timemodified") or 0), reverse=True)
                seen_ids: set[int] = set()

                for fr in file_rows:
                    if collected_files >= max_files:
                        break
                    if extracted_chars >= max_total_chars:
                        break

                    fid = fr.get("id")
                    if fid in seen_ids:
                        continue
                    seen_ids.add(fid)

                    contenthash = (fr.get("contenthash") or "").strip()
                    filename = str(fr.get("filename") or "").strip()
                    mimetype = str(fr.get("mimetype") or "").strip()
                    component = str(fr.get("component") or "").strip()
                    filearea = str(fr.get("filearea") or "").strip()
                    filesize = fr.get("filesize")
                    tm = int(fr.get("timemodified") or 0)

                    if not contenthash or len(contenthash) < 4 or not filename:
                        continue

                    if filesize is not None:
                        try:
                            if int(filesize) > max_bytes:
                                file_parts.append(
                                    f"--- File skipped (too large): {component}/{filearea}/{filename} ---"
                                )
                                collected_files += 1
                                tm_max = max(tm_max, tm)
                                continue
                        except Exception:
                            pass

                    disk_path = _filedir_path_from_contenthash(settings, contenthash)
                    if not disk_path:
                        continue

                    try:
                        with open(disk_path, "rb") as fh:
                            data = fh.read(max_bytes + 1)
                    except Exception:
                        continue

                    if filesize is not None:
                        try:
                            if len(data) > max_bytes:
                                file_parts.append(
                                    f"--- File skipped (too large): {component}/{filearea}/{filename} ---"
                                )
                                collected_files += 1
                                tm_max = max(tm_max, tm)
                                continue
                        except Exception:
                            pass

                    try:
                        extracted = extract_moodle_course_file(
                            settings, filename, data, mimetype
                        )
                    except Exception:
                        extracted = ""

                    header = f"--- File: {component}/{filearea}/{filename} (mime={mimetype}) ---"
                    if extracted.strip():
                        extracted = extracted.strip()
                        if len(extracted) > max_chars_per_file:
                            extracted = extracted[:max_chars_per_file] + "\n\n[...truncated...]"
                        file_parts.append(f"{header}\n{extracted}")
                        extracted_chars += len(extracted)
                    else:
                        file_parts.append(f"{header}\n[No extracted text for this file]")

                    collected_files += 1
                    tm_max = max(tm_max, tm)

                if file_parts:
                    parts.append("Course attached files (extracted):")
                    parts.extend(file_parts)
                    timemodified = max(timemodified, tm_max)

        return "\n\n".join(line for line in parts if line), timemodified
    finally:
        conn.close()


def list_enrolled_course_ids(settings: Settings, user_id: int, *, limit: int = 48) -> list[int]:
    """Course ids the user is actively enrolled in (visible courses only)."""
    if user_id <= 1:
        return []

    conn = pymysql.connect(**_mysql_connect_kwargs(settings))
    p = settings.mysql_prefix
    tbl_course = _table("course", p)
    tbl_enrol = _table("enrol", p)
    tbl_ue = _table("user_enrolments", p)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT c.id AS cid, c.sortorder "
                f"FROM {tbl_course} c "
                f"JOIN {tbl_enrol} e ON e.courseid = c.id AND e.status = 0 "
                f"JOIN {tbl_ue} ue ON ue.enrolid = e.id AND ue.status = 0 "
                f"WHERE ue.userid = %s AND c.id > 1 AND c.visible = 1 "
                f"GROUP BY c.id, c.sortorder "
                f"ORDER BY c.sortorder ASC, c.id ASC "
                f"LIMIT %s",
                (user_id, int(limit)),
            )
            rows = cur.fetchall() or []
        return [int(r["cid"]) for r in rows if r.get("cid")]
    finally:
        conn.close()
