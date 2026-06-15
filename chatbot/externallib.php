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
 * External API for local_chatbot.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

use context_course;
use core_external\external_api;
use core_external\external_function_parameters;
use core_external\external_multiple_structure;
use core_external\external_single_structure;
use core_external\external_value;

defined('MOODLE_INTERNAL') || die();

global $CFG;
require_once($CFG->dirroot . '/local/chatbot/lib.php');

/**
 * Web service functions.
 */
class local_chatbot_external extends external_api {

    /** Max attachment count per request. */
    public const ATTACHMENT_MAX_FILES = 5;

    /** Max decoded bytes per file. */
    public const ATTACHMENT_MAX_BYTES = 1572864;

    /**
     * Map client course context (0 = not in a course page) to DB room course id.
     *
     * @param int $courseid Course id from JS (may be 0).
     * @return int
     */
    private static function normalize_room_courseid(int $courseid): int {
        return SITEID;
    }

    /**
     * RAG course id sent to FastAPI: 0 = search all enrolled courses.
     *
     * @param int $courseid Course id from JS.
     * @return int
     */
    private static function rag_course_id_from_context(int $courseid): int {
        $resolved = \local_chatbot_resolve_page_course_id($courseid);
        return ($resolved > SITEID) ? $resolved : 0;
    }

    /**
     * Page context for link footer when answer used course DB chunks.
     *
     * @param int $courseid Course id from JS.
     * @return int 0 when not viewing a course page (&gt; site home).
     */
    private static function page_course_context(int $courseid): int {
        $resolved = \local_chatbot_resolve_page_course_id($courseid);
        return ($resolved > SITEID) ? $resolved : 0;
    }
    /**
     * Validate course access for the current user.
     *
     * @param int $courseid
     * @return \stdClass Course record
     */
    private static function require_course_access(int $courseid): \stdClass {
        if ($courseid <= 0 || $courseid == SITEID) {
            throw new moodle_exception('error_need_course', 'local_chatbot');
        }

        $course = get_course($courseid);
        $context = context_course::instance($course->id);
        self::validate_context($context);
        require_capability('moodle/course:view', $context);

        if (!can_access_course($course)) {
            throw new moodle_exception('error_course_access', 'local_chatbot');
        }

        return $course;
    }

    /**
     * @return external_function_parameters
     */
    public static function create_room_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(
                PARAM_INT,
                'Page course id or 0 for site-wide scope',
                VALUE_DEFAULT,
                0
            ),
        ]);
    }

    /**
     * Create a new chat room (new conversation).
     *
     * @param int $courseid
     * @return array
     */
    public static function create_room(int $courseid): array {
        global $USER;

        $params = self::validate_parameters(self::create_room_parameters(), [
            'courseid' => $courseid,
        ]);

        require_login();
        $roomcid = self::normalize_room_courseid((int) $params['courseid']);
        if ($roomcid > SITEID) {
            self::require_course_access($roomcid);
        }

        $roomid = local_chatbot_room_create((int) $USER->id, $roomcid);

        return ['roomid' => $roomid];
    }

    /**
     * @return external_single_structure
     */
    public static function create_room_returns(): external_single_structure {
        return new external_single_structure([
            'roomid' => new external_value(PARAM_INT, 'New room id'),
        ]);
    }

    /**
     * @return external_function_parameters
     */
    public static function list_rooms_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(
                PARAM_INT,
                'Page course id or 0 for site-wide scope',
                VALUE_DEFAULT,
                0
            ),
            'search' => new external_value(PARAM_TEXT, 'Search in title or messages', VALUE_DEFAULT, ''),
        ]);
    }

    /**
     * List chat rooms for history sidebar.
     *
     * @param int $courseid
     * @param string $search
     * @return array
     */
    public static function list_rooms(int $courseid, string $search = ''): array {
        global $USER;

        $params = self::validate_parameters(self::list_rooms_parameters(), [
            'courseid' => $courseid,
            'search' => $search,
        ]);

        require_login();
        $roomcid = self::normalize_room_courseid((int) $params['courseid']);
        if ($roomcid > SITEID) {
            self::require_course_access($roomcid);
        }

        $search = trim($params['search']);
        $rows = local_chatbot_room_list((int) $USER->id, $roomcid, $search, 50);

        $rooms = [];
        foreach ($rows as $r) {
            $preview = $r->preview ?? '';
            if ($preview === '') {
                $preview = get_string('room_no_messages', 'local_chatbot');
            }
            $rooms[] = [
                'roomid' => (int) $r->id,
                'title' => $r->title,
                'preview' => $preview,
                'timemodified' => (int) $r->timemodified,
            ];
        }

        return ['rooms' => $rooms];
    }

    /**
     * @return external_single_structure
     */
    public static function list_rooms_returns(): external_single_structure {
        return new external_single_structure([
            'rooms' => new external_multiple_structure(
                new external_single_structure([
                    'roomid' => new external_value(PARAM_INT, 'Room id'),
                    'title' => new external_value(PARAM_TEXT, 'Room title'),
                    'preview' => new external_value(PARAM_TEXT, 'Last user message preview'),
                    'timemodified' => new external_value(PARAM_INT, 'Last activity'),
                ])
            ),
        ]);
    }

    /**
     * Parameters.
     *
     * @return external_function_parameters
     */
    public static function send_message_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(
                PARAM_INT,
                'Page course id (>1) or 0 for dashboard / global scope',
                VALUE_DEFAULT,
                0
            ),
            'roomid' => new external_value(PARAM_INT, 'Chat room id (0 = create new)', VALUE_DEFAULT, 0),
            'message' => new external_value(PARAM_RAW, 'User message', VALUE_DEFAULT, ''),
            'attachmentsjson' => new external_value(PARAM_RAW, 'Optional JSON array of {name,mime,data_base64}', VALUE_DEFAULT, ''),
            'pending_quiz_json' => new external_value(PARAM_RAW, 'JSON of current unconfirmed quiz', VALUE_DEFAULT, ''),
            'quiz_mode' => new external_value(PARAM_BOOL, 'Force quiz generation flow', VALUE_DEFAULT, false),
        ]);
    }

    /**
     * Send a message and receive an AI reply (course-scoped RAG).
     *
     * @param int $courseid
     * @param int $roomid
     * @param string $message
     * @param string $attachmentsjson
     * @param string $pending_quiz_json
     * @param bool $quiz_mode
     * @return array
     */
    public static function send_message(
        int $courseid,
        int $roomid,
        string $message,
        string $attachmentsjson = '',
        string $pending_quiz_json = '',
        bool $quiz_mode = false
    ): array {
        global $USER;

        $params = self::validate_parameters(self::send_message_parameters(), [
            'courseid' => $courseid,
            'roomid' => $roomid,
            'message' => $message,
            'attachmentsjson' => $attachmentsjson,
            'pending_quiz_json' => $pending_quiz_json,
            'quiz_mode' => $quiz_mode,
        ]);
        $courseid = (int) $params['courseid'];
        $roomid = (int) $params['roomid'];
        $message = trim($params['message']);
        $attachmentsjson = $params['attachmentsjson'];
        $pending_quiz_json = $params['pending_quiz_json'];
        $quiz_mode = !empty($params['quiz_mode']);

        require_login();

        $attachments = self::parse_attachments($attachmentsjson);

        if ($message === '' && empty($attachments)) {
            return [
                'reply' => '',
                'error' => get_string('error_empty_message', 'local_chatbot'),
            ];
        }

        $roomcid = self::normalize_room_courseid($courseid);

        try {
            if ($roomcid > SITEID) {
                self::require_course_access($roomcid);
            }
        } catch (\Throwable $e) {
            return [
                'reply' => '',
                'error' => $e->getMessage(),
            ];
        }

        if ($roomid <= 0) {
            $roomid = local_chatbot_room_create((int) $USER->id, $roomcid);
        } else if (!local_chatbot_room_validate($roomid, (int) $USER->id, $roomcid)) {
            return [
                'reply' => '',
                'error' => get_string('error_invalid_room', 'local_chatbot'),
            ];
        }

        core_php_time_limit::raise(240);

        $ragcourseid = self::rag_course_id_from_context($courseid);

        global $CFG;
        try {
            $result = \local_chatbot\fastapi_client::send_chat(
                $message,
                $ragcourseid,
                (int) $USER->id,
                $attachments,
                self::page_course_context($courseid),
                $CFG->wwwroot,
                $pending_quiz_json,
                $quiz_mode,
                $roomid,
                current_language() === 'en' ? 'en' : 'id'
            );
        } catch (\Throwable $e) {
            return [
                'reply' => '',
                'error' => get_string('error_unexpected', 'local_chatbot'),
            ];
        }

        if ($result['error'] === '' && $result['reply'] === '') {
            $result['error'] = get_string('error_empty_reply', 'local_chatbot');
        }

        if (empty($result['error']) && $result['reply'] !== '') {
            $userstore = $message;
            if (!empty($attachments)) {
                $names = array_map(static function ($a) {
                    return $a['name'] ?? '';
                }, $attachments);
                $names = array_filter($names);
                if ($names) {
                    $userstore .= "\n[" . get_string('attachments_label', 'local_chatbot') . ': ' . implode(', ', $names) . ']';
                }
            }

            $rows = local_chatbot_message_list_room($roomid, (int) $USER->id, $roomcid, 1);
            if (empty($rows)) {
                $title = $message !== '' ? $message : get_string('room_attachment_title', 'local_chatbot');
                local_chatbot_room_touch($roomid, $title);
            }

            local_chatbot_message_save($roomid, (int) $USER->id, $roomcid, 'user', $userstore);
            local_chatbot_message_save($roomid, (int) $USER->id, $roomcid, 'assistant', $result['reply']);
        }

        return [
            'reply' => $result['reply'],
            'error' => $result['error'],
            'roomid' => $roomid,
            'quiz_json' => $result['quiz_json'] ?? '',
            'quiz_ready_for_pdf' => !empty($result['quiz_ready_for_pdf']),
        ];
    }

    /**
     * @param string $attachmentsjson
     * @return array<int, array{name: string, mime: string, data_base64: string}>
     */
    private static function parse_attachments(string $attachmentsjson): array {
        $attachmentsjson = trim($attachmentsjson);
        if ($attachmentsjson === '') {
            return [];
        }
        $decoded = json_decode($attachmentsjson, true);
        if (!is_array($decoded)) {
            return [];
        }
        $out = [];
        $count = 0;
        foreach ($decoded as $item) {
            if ($count >= self::ATTACHMENT_MAX_FILES) {
                break;
            }
            if (!is_array($item)) {
                continue;
            }
            $name = isset($item['name']) ? clean_param((string) $item['name'], PARAM_FILE) : '';
            $mime = isset($item['mime']) ? clean_param((string) $item['mime'], PARAM_TEXT) : '';
            $b64 = isset($item['data_base64']) ? (string) $item['data_base64'] : '';
            $b64 = preg_replace('/\s+/', '', $b64);
            if ($name === '' || $b64 === '') {
                continue;
            }
            $raw = base64_decode($b64, true);
            if ($raw === false || strlen($raw) > self::ATTACHMENT_MAX_BYTES) {
                continue;
            }
            $out[] = [
                'name' => $name,
                'mime' => $mime,
                'data_base64' => base64_encode($raw),
            ];
            $count++;
        }

        return $out;
    }

    /**
     * Return structure.
     *
     * @return external_single_structure
     */
    public static function send_message_returns(): external_single_structure {
        return new external_single_structure([
            'reply' => new external_value(PARAM_RAW, 'Assistant reply'),
            'error' => new external_value(PARAM_TEXT, 'Error message if any', VALUE_DEFAULT, ''),
            'roomid' => new external_value(PARAM_INT, 'Chat room id used', VALUE_DEFAULT, 0),
            'quiz_json' => new external_value(PARAM_RAW, 'Pending quiz JSON', VALUE_DEFAULT, ''),
            'quiz_ready_for_pdf' => new external_value(PARAM_BOOL, 'User confirmed quiz', VALUE_DEFAULT, false),
        ]);
    }

    /**
     * @return external_function_parameters
     */
    public static function get_chat_history_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(
                PARAM_INT,
                'Page course id or 0 for site-wide scope',
                VALUE_DEFAULT,
                0
            ),
            'roomid' => new external_value(PARAM_INT, 'Chat room id', VALUE_DEFAULT, 0),
        ]);
    }

    /**
     * Load stored chat messages for a room.
     *
     * @param int $courseid
     * @param int $roomid
     * @return array
     */
    public static function get_chat_history(int $courseid, int $roomid): array {
        global $USER;

        $params = self::validate_parameters(self::get_chat_history_parameters(), [
            'courseid' => $courseid,
            'roomid' => $roomid,
        ]);
        $courseid = (int) $params['courseid'];
        $roomid = (int) $params['roomid'];

        require_login();

        $roomcid = self::normalize_room_courseid($courseid);

        try {
            if ($roomcid > SITEID) {
                self::require_course_access($roomcid);
            }
        } catch (\Throwable $e) {
            return ['messages' => []];
        }

        if ($roomid <= 0) {
            return ['messages' => []];
        }

        if (!local_chatbot_room_validate($roomid, (int) $USER->id, $roomcid)) {
            return ['messages' => []];
        }

        $rows = local_chatbot_message_list_room($roomid, (int) $USER->id, $roomcid, 200);
        $messages = [];
        foreach ($rows as $r) {
            $messages[] = [
                'role' => $r->role,
                'message' => $r->message,
                'timecreated' => (int) $r->timecreated,
            ];
        }

        return ['messages' => $messages];
    }

    /**
     * @return external_single_structure
     */
    public static function get_chat_history_returns(): external_single_structure {
        return new external_single_structure([
            'messages' => new external_multiple_structure(
                new external_single_structure([
                    'role' => new external_value(PARAM_TEXT, 'user or assistant'),
                    'message' => new external_value(PARAM_RAW, 'Message text'),
                    'timecreated' => new external_value(PARAM_INT, 'Unix time'),
                ])
            ),
        ]);
    }

    /**
     * @return external_function_parameters
     */
    public static function delete_room_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(
                PARAM_INT,
                'Page course id or 0 for site-wide scope',
                VALUE_DEFAULT,
                0
            ),
            'roomid' => new external_value(PARAM_INT, 'Room id to delete'),
        ]);
    }

    /**
     * Delete one chat session and its messages.
     *
     * @param int $courseid
     * @param int $roomid
     * @return array
     */
    public static function delete_room(int $courseid, int $roomid): array {
        global $USER;

        $params = self::validate_parameters(self::delete_room_parameters(), [
            'courseid' => $courseid,
            'roomid' => $roomid,
        ]);

        require_login();

        $roomcid = self::normalize_room_courseid((int) $params['courseid']);
        $roomid = (int) $params['roomid'];

        try {
            if ($roomcid > SITEID) {
                self::require_course_access($roomcid);
            }
        } catch (\Throwable $e) {
            return ['success' => false];
        }

        if ($roomid <= 0) {
            return ['success' => false];
        }

        $ok = local_chatbot_room_delete((int) $USER->id, $roomcid, $roomid);

        return ['success' => $ok];
    }

    /**
     * @return external_single_structure
     */
    public static function delete_room_returns(): external_single_structure {
        return new external_single_structure([
            'success' => new external_value(PARAM_BOOL, 'Whether the room was deleted'),
        ]);
    }

    /**
     * @return external_function_parameters
     */
    public static function delete_all_rooms_parameters(): external_function_parameters {
        return new external_function_parameters([
            'courseid' => new external_value(
                PARAM_INT,
                'Page course id or 0 for site-wide scope',
                VALUE_DEFAULT,
                0
            ),
        ]);
    }

    /**
     * Delete all chat sessions for this user in the resolved course scope.
     *
     * @param int $courseid
     * @return array
     */
    public static function delete_all_rooms(int $courseid): array {
        global $USER;

        $params = self::validate_parameters(self::delete_all_rooms_parameters(), [
            'courseid' => $courseid,
        ]);

        require_login();

        $roomcid = self::normalize_room_courseid((int) $params['courseid']);

        try {
            if ($roomcid > SITEID) {
                self::require_course_access($roomcid);
            }
        } catch (\Throwable $e) {
            return ['success' => false];
        }

        local_chatbot_rooms_delete_all_for_user((int) $USER->id, $roomcid);

        return ['success' => true];
    }

    /**
     * @return external_single_structure
     */
    public static function delete_all_rooms_returns(): external_single_structure {
        return new external_single_structure([
            'success' => new external_value(PARAM_BOOL, 'Whether the operation completed'),
        ]);
    }
}
