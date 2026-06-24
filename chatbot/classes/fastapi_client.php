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

namespace local_chatbot;

defined('MOODLE_INTERNAL') || die();

/**
 * Forwards chat requests to the FastAPI RAG service.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class fastapi_client {
    /*
     * POST /chat with JSON body. Returns [reply, error].
     *
     * @param string $question
     * @param int $courseid FastAPI rag course id (0 = search all enrolled courses for user_id)
     * @param int $userid
     * @param array<int, array{name: string, mime: string, data_base64: string}> $attachments
     * @param int $pagecourseid Current Moodle page course id (0 when not viewing a course)
     * @param string $wwwroot Moodle wwwroot URL for outbound links appended by RAG
     * @param int $roomid Moodle chat room id (Redis history scoping)
     * @param string $language Response language hint: id or en
     * @return array{reply: string, error: string, quiz_json: string, quiz_ready_for_pdf: bool}
     */
    public static function send_chat(
        string $question,
        int $courseid,
        int $userid,
        array $attachments = [],
        int $pagecourseid = 0,
        string $wwwroot = '',
        string $pending_quiz_json = '',
        bool $quiz_mode = false,
        int $roomid = 0,
        string $language = 'id'
    ): array {
        global $CFG;

        $base = trim((string)get_config('local_chatbot', 'fastapiurl'));
        if ($base === '') {
            return [
                'reply' => '',
                'error' => get_string('error_no_fastapi', 'local_chatbot'),
                'quiz_json' => '',
                'quiz_ready_for_pdf' => false,
            ];
        }

        $url = rtrim($base, '/') . '/chat';
        $secret = trim((string)get_config('local_chatbot', 'fastapisecret'));

        require_once($CFG->libdir . '/filelib.php');

        if ($wwwroot === '') {
            $wwwroot = $CFG->wwwroot;
        }

        // Send the same course on both fields so FastAPI summarize/quiz can use page_course_id fallback.
        $effectivecourse = max(0, $courseid);
        if ($effectivecourse <= 0 && $pagecourseid > 0) {
            $effectivecourse = $pagecourseid;
        }

        $payload = [
            'question' => $question,
            'course_id' => $effectivecourse,
            'page_course_id' => max($effectivecourse, max(0, $pagecourseid)),
            'user_id' => $userid,
            'room_id' => max(0, $roomid),
            'language' => $language !== '' ? $language : 'id',
            'moodle_wwwroot' => $wwwroot,
            'attachments' => array_values($attachments),
            'pending_quiz_json' => $pending_quiz_json,
            'force_quiz' => $quiz_mode,
        ];

        $json = json_encode($payload, JSON_UNESCAPED_UNICODE);
        if ($json === false) {
            return [
                'reply' => '',
                'error' => get_string('error_unexpected', 'local_chatbot'),
                'quiz_json' => '',
                'quiz_ready_for_pdf' => false,
            ];
        }

        $curl = new \curl(['ignoresecurity' => true]);
        $curl->setopt(['CURLOPT_TIMEOUT' => 600]);
        $curl->setHeader('Content-Type: application/json; charset=utf-8');
        if ($secret !== '') {
            $curl->setHeader('X-Chatbot-Secret: ' . $secret);
        }

        // Attempt up to 2 times — first query after container start can fail while
        // Ollama is still loading the model into memory (cold-start).
        $maxattempts = 2;
        $response = false;
        $httpcode  = 0;
        for ($attempt = 1; $attempt <= $maxattempts; $attempt++) {
            $response = $curl->post($url, $json);
            $info     = $curl->get_info();
            $httpcode = isset($info['http_code']) ? (int)$info['http_code'] : 0;
            if ($response !== false && $response !== '' && $httpcode < 400) {
                break; // success — no need to retry
            }
            if ($attempt < $maxattempts) {
                sleep(3); // brief pause before retry
                $curl = new \curl(['ignoresecurity' => true]);
                $curl->setopt(['CURLOPT_TIMEOUT' => 600]);
                $curl->setHeader('Content-Type: application/json; charset=utf-8');
                if ($secret !== '') {
                    $curl->setHeader('X-Chatbot-Secret: ' . $secret);
                }
            }
        }

        if ($response === false || $response === '' || $httpcode >= 400) {
            return [
                'reply'             => '',
                'thinking'          => '',
                'error'             => get_string('error_fastapi_http', 'local_chatbot'),
                'quiz_json'         => '',
                'quiz_ready_for_pdf' => false,
            ];
        }

        $data = json_decode($response, true);
        if (!is_array($data)) {
            return [
                'reply'             => '',
                'thinking'          => '',
                'error'             => get_string('error_fastapi_json', 'local_chatbot'),
                'quiz_json'         => '',
                'quiz_ready_for_pdf' => false,
            ];
        }

        if (!empty($data['error'])) {
            return [
                'reply'             => '',
                'thinking'          => '',
                'error'             => clean_param((string)$data['error'], PARAM_TEXT),
                'quiz_json'         => '',
                'quiz_ready_for_pdf' => false,
            ];
        }

        $reply = isset($data['reply']) ? (string)$data['reply'] : '';
        return [
            'reply'             => $reply,
            'thinking'          => isset($data['thinking']) ? (string)$data['thinking'] : '',
            'error'             => '',
            'quiz_json'         => isset($data['quiz_json']) ? (string)$data['quiz_json'] : '',
            'quiz_ready_for_pdf' => !empty($data['quiz_ready_for_pdf']),
        ];
    }

    /**
     * Ask FastAPI to refresh Chroma vectors for one course (non-blocking).
     *
     * @param int $courseid Moodle course id (> 1)
     */
    public static function request_course_reindex(int $courseid): void {
        global $CFG;

        if ($courseid <= 1) {
            return;
        }

        $base = trim((string)get_config('local_chatbot', 'fastapiurl'));
        if ($base === '') {
            return;
        }

        $url = rtrim($base, '/') . '/admin/reindex/course';
        $secret = trim((string)get_config('local_chatbot', 'fastapisecret'));

        $payload = json_encode([
            'course_id' => $courseid,
            'sync' => false,
        ], JSON_UNESCAPED_UNICODE);
        if ($payload === false) {
            return;
        }

        require_once($CFG->libdir . '/filelib.php');

        $curl = new \curl(['ignoresecurity' => true]);
        $curl->setopt([
            'CURLOPT_TIMEOUT' => 5,
            'CURLOPT_CONNECTTIMEOUT' => 3,
        ]);
        $curl->setHeader('Content-Type: application/json; charset=utf-8');
        if ($secret !== '') {
            $curl->setHeader('X-Chatbot-Secret: ' . $secret);
        }

        $curl->post($url, $payload);
    }
}
