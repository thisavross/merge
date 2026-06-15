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
 * Upgrade steps for local_chatbot.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

/**
 * Upgrade the plugin.
 *
 * @param int $oldversion
 * @return bool
 */
function xmldb_local_chatbot_upgrade($oldversion) {
    global $DB;

    $dbman = $DB->get_manager();

    if ($oldversion < 2026032411) {
        upgrade_set_timeout(300);
        $table = new xmldb_table('local_chatbot_chunk');
        if ($dbman->table_exists($table)) {
            $dbman->drop_table($table);
        }
        upgrade_plugin_savepoint(true, 2026032411, 'local', 'chatbot');
    }

    if ($oldversion < 2026032500) {
        upgrade_set_timeout(300);

        require_once(__DIR__ . '/../lib.php');
        local_chatbot_ensure_message_table();

        upgrade_plugin_savepoint(true, 2026032500, 'local', 'chatbot');
    }

    if ($oldversion < 2026051600) {
        upgrade_set_timeout(300);

        require_once(__DIR__ . '/../lib.php');

        // Chat rooms table.
        $roomtable = new xmldb_table('local_chatbot_room');
        if (!$dbman->table_exists($roomtable)) {
            $roomtable->add_field('id', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, XMLDB_SEQUENCE, null);
            $roomtable->add_field('userid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
            $roomtable->add_field('courseid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
            $roomtable->add_field('title', XMLDB_TYPE_CHAR, '255', null, XMLDB_NOTNULL, null, 'New chat');
            $roomtable->add_field('timecreated', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
            $roomtable->add_field('timemodified', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);

            $roomtable->add_key('primary', XMLDB_KEY_PRIMARY, ['id']);
            $roomtable->add_key('userid', XMLDB_KEY_FOREIGN, ['userid'], 'user', ['id']);
            $roomtable->add_key('courseid', XMLDB_KEY_FOREIGN, ['courseid'], 'course', ['id']);
            $roomtable->add_index('local_chatbot_room_uc_mod', XMLDB_INDEX_NOTUNIQUE, ['userid', 'courseid', 'timemodified']);

            $dbman->create_table($roomtable);
        }

        // roomid on messages.
        $msgtable = new xmldb_table('local_chatbot_message');
        $roomfield = new xmldb_field('roomid', XMLDB_TYPE_INTEGER, '10', null, null, null, null);
        if ($dbman->table_exists($msgtable) && !$dbman->field_exists($msgtable, $roomfield)) {
            $dbman->add_field($msgtable, $roomfield);
        }

        local_chatbot_migrate_legacy_messages();

        // Enforce NOT NULL after migration.
        $roomfieldnn = new xmldb_field('roomid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
        if ($dbman->field_exists($msgtable, $roomfieldnn)) {
            $dbman->change_field_notnull($msgtable, $roomfieldnn);
        }

        // Foreign key roomid -> room (best effort).
        $key = new xmldb_key('roomid', XMLDB_KEY_FOREIGN, ['roomid'], 'local_chatbot_room', ['id']);
        if (!$dbman->find_key_name($msgtable, $key)) {
            $dbman->add_key($msgtable, $key);
        }

        upgrade_plugin_savepoint(true, 2026051600, 'local', 'chatbot');
    }

    if ($oldversion < 2026051601) {
        // Re-register web services after services.php / externallib parameter changes.
        upgrade_plugin_savepoint(true, 2026051601, 'local', 'chatbot');
    }

    if ($oldversion < 2026051602) {
        upgrade_plugin_savepoint(true, 2026051602, 'local', 'chatbot');
    }

    if ($oldversion < 2026052000) {
        // Re-register web services (quiz_mode on send_message).
        upgrade_plugin_savepoint(true, 2026052000, 'local', 'chatbot');
    }

    if ($oldversion < 2026052001) {
        // Re-register hooks (top-of-body mount point).
        upgrade_plugin_savepoint(true, 2026052001, 'local', 'chatbot');
    }

    if ($oldversion < 2026060100) {
        // Register course_updated observer (db/events.php) for background index warm-up.
        upgrade_plugin_savepoint(true, 2026060100, 'local', 'chatbot');
    }

    return true;
}
