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

namespace local_chatbot\privacy;

use core_privacy\local\metadata\collection;
use core_privacy\local\request\approved_contextlist;
use core_privacy\local\request\approved_userlist;
use core_privacy\local\request\contextlist;
use core_privacy\local\request\transform;
use core_privacy\local\request\userlist;
use core_privacy\local\request\writer;

/**
 * Privacy API: chat messages stored in local_chatbot_message.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class provider implements
    \core_privacy\local\metadata\provider,
    \core_privacy\local\request\plugin\provider,
    \core_privacy\local\request\core_userlist_provider {

    /**
     * Ensure {local_chatbot_message} exists before any direct DB access from this class.
     *
     * @return void
     */
    private static function ensure_message_table(): void {
        global $CFG;
        require_once($CFG->dirroot . '/local/chatbot/lib.php');
        \local_chatbot_ensure_message_table();
    }

    /**
     * @param collection $collection
     * @return collection
     */
    public static function get_metadata(collection $collection): collection {
        $collection->add_database_table('local_chatbot_room', [
            'userid' => 'privacy:metadata:local_chatbot_message:userid',
            'courseid' => 'privacy:metadata:local_chatbot_message:courseid',
            'title' => 'privacy:metadata:local_chatbot_room:title',
            'timecreated' => 'privacy:metadata:local_chatbot_message:timecreated',
            'timemodified' => 'privacy:metadata:local_chatbot_room:timemodified',
        ], 'privacy:metadata:local_chatbot_room');

        $collection->add_database_table('local_chatbot_message', [
            'roomid' => 'privacy:metadata:local_chatbot_message:roomid',
            'userid' => 'privacy:metadata:local_chatbot_message:userid',
            'courseid' => 'privacy:metadata:local_chatbot_message:courseid',
            'role' => 'privacy:metadata:local_chatbot_message:role',
            'message' => 'privacy:metadata:local_chatbot_message:message',
            'timecreated' => 'privacy:metadata:local_chatbot_message:timecreated',
        ], 'privacy:metadata:local_chatbot_message');

        return $collection;
    }

    /**
     * @param int $userid
     * @return contextlist
     */
    public static function get_contexts_for_userid(int $userid): contextlist {
        global $DB;

        self::ensure_message_table();

        $contextlist = new contextlist();

        $courseids = $DB->get_fieldset_sql(
            'SELECT DISTINCT courseid FROM {local_chatbot_message} WHERE userid = ?',
            [$userid]
        );
        foreach ($courseids as $cid) {
            $contextlist->add_context(\context_course::instance($cid));
        }

        return $contextlist;
    }

    /**
     * @param approved_contextlist $contextlist
     */
    public static function export_user_data(approved_contextlist $contextlist): void {
        global $DB;

        self::ensure_message_table();

        if (empty($contextlist->get_userids())) {
            return;
        }
        $userid = (int) reset($contextlist->get_userids());

        foreach ($contextlist->get_contexts() as $context) {
            if ($context->contextlevel != CONTEXT_COURSE) {
                continue;
            }
            $courseid = (int) $context->instanceid;
            $rows = $DB->get_records('local_chatbot_message', ['userid' => $userid, 'courseid' => $courseid],
                'timecreated ASC', 'id, role, message, timecreated');
            if (!$rows) {
                continue;
            }
            $data = [];
            foreach ($rows as $r) {
                $data[] = [
                    'role' => $r->role,
                    'message' => $r->message,
                    'time' => transform::datetime($r->timecreated),
                ];
            }
            writer::with_context($context)->export_data(
                [get_string('pluginname', 'local_chatbot')],
                (object) ['messages' => $data]
            );
        }
    }

    /**
     * @param approved_contextlist $contextlist
     */
    public static function delete_data_for_all_users_in_context(\context $context): void {
        global $DB;

        self::ensure_message_table();

        if ($context->contextlevel != CONTEXT_COURSE) {
            return;
        }
        $DB->delete_records('local_chatbot_message', ['courseid' => (int) $context->instanceid]);
    }

    /**
     * @param int $userid
     */
    public static function delete_data_for_user(approved_contextlist $contextlist): void {
        global $DB;

        self::ensure_message_table();

        if (empty($contextlist->get_userids())) {
            return;
        }
        $userid = (int) reset($contextlist->get_userids());

        foreach ($contextlist->get_contexts() as $context) {
            if ($context->contextlevel != CONTEXT_COURSE) {
                continue;
            }
            $DB->delete_records('local_chatbot_message', [
                'userid' => $userid,
                'courseid' => (int) $context->instanceid,
            ]);
        }
    }

    /**
     * @param userlist $userlist
     */
    public static function get_users_in_context(userlist $userlist): void {
        $context = $userlist->get_context();
        if ($context->contextlevel != CONTEXT_COURSE) {
            return;
        }

        self::ensure_message_table();

        global $DB;
        $sql = "SELECT DISTINCT userid FROM {local_chatbot_message} WHERE courseid = ?";
        $userlist->add_from_sql('userid', $sql, [(int) $context->instanceid]);
    }

    /**
     * @param approved_userlist $userlist
     */
    public static function delete_data_for_users(approved_userlist $userlist): void {
        global $DB;

        self::ensure_message_table();

        $context = $userlist->get_context();
        if ($context->contextlevel != CONTEXT_COURSE) {
            return;
        }
        $courseid = (int) $context->instanceid;
        $userids = $userlist->get_userids();
        if (!$userids) {
            return;
        }
        list($insql, $params) = $DB->get_in_or_equal($userids, SQL_PARAMS_NAMED);
        $params['courseid'] = $courseid;
        $DB->delete_records_select(
            'local_chatbot_message',
            "courseid = :courseid AND userid $insql",
            $params
        );
    }
}
