<?php
// This file is part of Moodle - http://moodle.org/
//
// Moodle is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// Moodle is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with Moodle.  If not, see <http://www.gnu.org/licenses/>.

/**
 * Library and chat room / message helpers.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

/**
 * Resolve the Moodle course id for the current page (used by UI + webservices).
 *
 * Prefers a valid client hint, then $PAGE context, course/view.php ?id=,
 * and mod/.../view.php ?id= (course module id).
 *
 * @param int $clientcourseid Course id from the browser (may be 0).
 * @return int Course id or 0 when not in a course context.
 */
function local_chatbot_resolve_page_course_id(int $clientcourseid = 0): int {
    global $DB, $PAGE;

    if ($clientcourseid > SITEID) {
        return $clientcourseid;
    }

    if (empty($PAGE) || !$PAGE->has_set_url()) {
        return 0;
    }

    $courseid = 0;
    if (!empty($PAGE->context)) {
        $coursecontext = $PAGE->context->get_course_context(false);
        if ($coursecontext) {
            $cid = (int) $coursecontext->instanceid;
            if ($cid > SITEID) {
                $courseid = $cid;
            }
        }
    }
    if ($courseid <= 0 && !empty($PAGE->course) && (int) $PAGE->course->id > SITEID) {
        $courseid = (int) $PAGE->course->id;
    }
    if ($courseid <= 0) {
        $path = $PAGE->url->get_path(false);
        if (strpos($path, 'course/view.php') !== false) {
            $id = $PAGE->url->param('id');
            if ($id !== null && $id !== '') {
                $cid = (int) $id;
                if ($cid > SITEID) {
                    $courseid = $cid;
                }
            }
        }
    }
    if ($courseid <= 0) {
        $path = $PAGE->url->get_path(false);
        if (strpos($path, 'mod/') !== false && strpos($path, '/view.php') !== false) {
            $cmid = $PAGE->url->param('id');
            if ($cmid !== null && $cmid !== '') {
                $fromcm = (int) $DB->get_field('course_modules', 'course', ['id' => (int) $cmid]);
                if ($fromcm > SITEID) {
                    $courseid = $fromcm;
                }
            }
        }
    }

    return $courseid;
}

/**
 * Create {local_chatbot_room} if missing.
 *
 * @return void
 */
function local_chatbot_ensure_room_table(): void {
    static $ensured = false;
    if ($ensured) {
        return;
    }

    if (during_initial_install()) {
        return;
    }

    global $DB;

    $dbman = $DB->get_manager();
    $table = new xmldb_table('local_chatbot_room');

    if ($dbman->table_exists($table)) {
        $ensured = true;
        return;
    }

    $table->add_field('id', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, XMLDB_SEQUENCE, null);
    $table->add_field('userid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
    $table->add_field('courseid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
    $table->add_field('title', XMLDB_TYPE_CHAR, '255', null, XMLDB_NOTNULL, null, 'New chat');
    $table->add_field('timecreated', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
    $table->add_field('timemodified', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);

    $table->add_key('primary', XMLDB_KEY_PRIMARY, ['id']);
    $table->add_key('userid', XMLDB_KEY_FOREIGN, ['userid'], 'user', ['id']);
    $table->add_key('courseid', XMLDB_KEY_FOREIGN, ['courseid'], 'course', ['id']);
    $table->add_index('local_chatbot_room_uc_mod', XMLDB_INDEX_NOTUNIQUE, ['userid', 'courseid', 'timemodified']);

    $dbman->create_table($table);
    $ensured = true;
}

/**
 * Create {local_chatbot_message} if missing; ensure roomid column exists.
 *
 * @return void
 */
function local_chatbot_ensure_message_table(): void {
    static $ensured = false;
    if ($ensured) {
        return;
    }

    if (during_initial_install()) {
        return;
    }

    global $DB;

    local_chatbot_ensure_room_table();

    $dbman = $DB->get_manager();
    $table = new xmldb_table('local_chatbot_message');

    if (!$dbman->table_exists($table)) {
        $table->add_field('id', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, XMLDB_SEQUENCE, null);
        $table->add_field('roomid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
        $table->add_field('userid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
        $table->add_field('courseid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
        $table->add_field('role', XMLDB_TYPE_CHAR, '12', null, XMLDB_NOTNULL, null, null);
        $table->add_field('message', XMLDB_TYPE_TEXT, 'big', null, XMLDB_NOTNULL, null, null);
        $table->add_field('timecreated', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);

        $table->add_key('primary', XMLDB_KEY_PRIMARY, ['id']);
        $table->add_key('roomid', XMLDB_KEY_FOREIGN, ['roomid'], 'local_chatbot_room', ['id']);
        $table->add_key('userid', XMLDB_KEY_FOREIGN, ['userid'], 'user', ['id']);
        $table->add_key('courseid', XMLDB_KEY_FOREIGN, ['courseid'], 'course', ['id']);
        $table->add_index('local_chatbot_msg_room_time', XMLDB_INDEX_NOTUNIQUE, ['roomid', 'timecreated']);
        $table->add_index('local_chatbot_msg_uc', XMLDB_INDEX_NOTUNIQUE, ['userid', 'courseid']);

        $dbman->create_table($table);
        $ensured = true;
        return;
    }

    $field = new xmldb_field('roomid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
    if (!$dbman->field_exists($table, $field)) {
        $dbman->add_field($table, $field);
    }

    $ensured = true;
}

/**
 * Create a new empty chat room.
 *
 * @param int $userid
 * @param int $courseid
 * @param string $title
 * @return int Room id
 */
function local_chatbot_room_create(int $userid, int $courseid, string $title = ''): int {
    global $DB;

    local_chatbot_ensure_room_table();

    $now = time();
    if ($title === '') {
        $title = get_string('room_default_title', 'local_chatbot');
    }
    $title = \core_text::substr($title, 0, 255);

    $record = (object) [
        'userid' => $userid,
        'courseid' => $courseid,
        'title' => $title,
        'timecreated' => $now,
        'timemodified' => $now,
    ];

    return (int) $DB->insert_record('local_chatbot_room', $record);
}

/**
 * Verify room belongs to user and course.
 *
 * @param int $roomid
 * @param int $userid
 * @param int $courseid
 * @return bool
 */
function local_chatbot_room_validate(int $roomid, int $userid, int $courseid): bool {
    global $DB;

    local_chatbot_ensure_room_table();

    return $DB->record_exists('local_chatbot_room', [
        'id' => $roomid,
        'userid' => $userid,
    ]);
}

/**
 * Delete one chat room and all its messages (must belong to user and course).
 *
 * @param int $userid
 * @param int $courseid
 * @param int $roomid
 * @return bool True if a room was removed
 */
function local_chatbot_room_delete(int $userid, int $courseid, int $roomid): bool {
    global $DB;

    local_chatbot_ensure_message_table();

    if (!local_chatbot_room_validate($roomid, $userid, $courseid)) {
        return false;
    }

    $DB->delete_records('local_chatbot_message', ['roomid' => $roomid]);
    $DB->delete_records('local_chatbot_room', ['id' => $roomid, 'userid' => $userid]);

    return true;
}

/**
 * Delete every chat room (and messages) for this user in the given course scope.
 *
 * @param int $userid
 * @param int $courseid
 * @return void
 */
function local_chatbot_rooms_delete_all_for_user(int $userid, int $courseid): void {
    global $DB;

    local_chatbot_ensure_room_table();
    local_chatbot_ensure_message_table();

    $roomids = $DB->get_fieldset_select(
        'local_chatbot_room',
        'id',
        'userid = ? AND courseid = ?',
        [$userid, $courseid]
    );

    foreach ($roomids as $rid) {
        local_chatbot_room_delete($userid, $courseid, (int) $rid);
    }
}

/**
 * Update room title and modified time (e.g. from first user message).
 *
 * @param int $roomid
 * @param string|null $title If set, updates title (max 255 chars).
 * @return void
 */
function local_chatbot_room_touch(int $roomid, ?string $title = null): void {
    global $DB;

    local_chatbot_ensure_room_table();

    $record = $DB->get_record('local_chatbot_room', ['id' => $roomid], 'id', MUST_EXIST);
    $record->timemodified = time();
    if ($title !== null && $title !== '') {
        $record->title = \core_text::substr(trim($title), 0, 255);
    }
    $DB->update_record('local_chatbot_room', $record);
}

/**
 * List chat rooms for sidebar history (newest first).
 *
 * @param int $userid
 * @param int $courseid
 * @param string $search Optional keyword search in title or message text.
 * @param int $limit
 * @return array<int, stdClass>
 */
function local_chatbot_room_list(int $userid, int $courseid, string $search = '', int $limit = 50): array {
    global $DB;

    local_chatbot_ensure_room_table();
    local_chatbot_ensure_message_table();

    $params = [
        'userid' => $userid,
        'courseid' => $courseid,
    ];

    $searchsql = '';
    if ($search !== '') {
        $like = '%' . $DB->sql_like_escape($search) . '%';
        $params['searchtitle'] = $like;
        $params['searchmsg'] = $like;
        $searchsql = ' AND (
            ' . $DB->sql_like('r.title', ':searchtitle', false) . '
            OR EXISTS (
                SELECT 1 FROM {local_chatbot_message} m
                 WHERE m.roomid = r.id AND ' . $DB->sql_like('m.message', ':searchmsg', false) . '
            )
        )';
    }

    $sql = "SELECT r.id, r.title, r.timecreated, r.timemodified,
                   (SELECT m.message
                      FROM {local_chatbot_message} m
                     WHERE m.roomid = r.id AND m.role = 'user'
                  ORDER BY m.timecreated DESC, m.id DESC
                     LIMIT 1) AS preview
              FROM {local_chatbot_room} r
             WHERE r.userid = :userid AND r.courseid = :courseid
                   {$searchsql}
          ORDER BY r.timemodified DESC, r.id DESC";

    return $DB->get_records_sql($sql, $params, 0, $limit);
}

/**
 * Save one chat message row.
 *
 * @param int $roomid
 * @param int $userid
 * @param int $courseid
 * @param string $role user|assistant
 * @param string $message
 * @return int Insert id
 */
function local_chatbot_message_save(
    int $roomid,
    int $userid,
    int $courseid,
    string $role,
    string $message
): int {
    global $DB;

    local_chatbot_ensure_message_table();

    if (!local_chatbot_room_validate($roomid, $userid, $courseid)) {
        throw new coding_exception('Invalid chat room');
    }

    if ($role !== 'user' && $role !== 'assistant') {
        throw new coding_exception('Invalid role');
    }

    $record = (object) [
        'roomid' => $roomid,
        'userid' => $userid,
        'courseid' => $courseid,
        'role' => $role,
        'message' => $message,
        'timecreated' => time(),
    ];

    $id = (int) $DB->insert_record('local_chatbot_message', $record);
    local_chatbot_room_touch($roomid);

    return $id;
}

/**
 * List messages in a room (oldest first).
 *
 * @param int $roomid
 * @param int $userid
 * @param int $courseid
 * @param int $limit
 * @return array<int, stdClass>
 */
function local_chatbot_message_list_room(
    int $roomid,
    int $userid,
    int $courseid,
    int $limit = 200
): array {
    global $DB;

    local_chatbot_ensure_message_table();

    if (!local_chatbot_room_validate($roomid, $userid, $courseid)) {
        return [];
    }

    return $DB->get_records_sql(
        'SELECT id, role, message, timecreated
           FROM {local_chatbot_message}
          WHERE roomid = ? AND userid = ? AND courseid = ?
       ORDER BY timecreated ASC, id ASC',
        [$roomid, $userid, $courseid],
        0,
        $limit
    );
}

/**
 * Migrate legacy messages (no roomid) into one room per user/course.
 *
 * @return void
 */
function local_chatbot_migrate_legacy_messages(): void {
    global $DB;

    local_chatbot_ensure_room_table();
    local_chatbot_ensure_message_table();

    $dbman = $DB->get_manager();
    $table = new xmldb_table('local_chatbot_message');
    $field = new xmldb_field('roomid');
    if (!$dbman->field_exists($table, $field)) {
        return;
    }

    $orphans = $DB->get_records_sql(
        'SELECT DISTINCT userid, courseid
           FROM {local_chatbot_message}
          WHERE roomid IS NULL OR roomid = 0'
    );

    foreach ($orphans as $row) {
        $userid = (int) $row->userid;
        $courseid = (int) $row->courseid;
        $roomid = local_chatbot_room_create($userid, $courseid, get_string('room_legacy_title', 'local_chatbot'));
        $DB->execute(
            'UPDATE {local_chatbot_message}
                SET roomid = ?
              WHERE userid = ? AND courseid = ? AND (roomid IS NULL OR roomid = 0)',
            [$roomid, $userid, $courseid]
        );
        local_chatbot_room_touch($roomid);
    }
}

/**
 * Inject chatbot popup container before page body.
 *
 * @return string
 */
function local_chatbot_before_standard_top_of_body_html(): string {
    global $PAGE;

    if (during_initial_install()) {
        return '';
    }

    if (defined('CLI_SCRIPT') && CLI_SCRIPT) {
        return '';
    }

    if (defined('AJAX_SCRIPT') && AJAX_SCRIPT) {
        return '';
    }

    if (empty($PAGE) || !$PAGE->has_set_url()) {
        return '';
    }

    return html_writer::div('', 'local-chatbot-root');
}
