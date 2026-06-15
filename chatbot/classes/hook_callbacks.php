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

require_once(__DIR__ . '/../lib.php');

use core\hook\output\before_standard_head_html_generation;
use core\hook\output\before_standard_top_of_body_html_generation;

/**
 * Page output hooks (CSS/JS must be queued before &lt;head&gt; is emitted).
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
class hook_callbacks {
    /**
     * @return int Real course id or 0 if not on a course page.
     */
    private static function resolve_course_id(): int {
        return \local_chatbot_resolve_page_course_id(0);
    }

    /**
     * Inject popup mount point at top of page body.
     *
     * @param before_standard_top_of_body_html_generation $hook
     */
    public static function before_standard_top_of_body_html_generation(
        before_standard_top_of_body_html_generation $hook
    ): void {
        if (during_initial_install()) {
            return;
        }

        if (defined('CLI_SCRIPT') && CLI_SCRIPT) {
            return;
        }

        if (defined('AJAX_SCRIPT') && AJAX_SCRIPT) {
            return;
        }

        global $PAGE;

        if (empty($PAGE) || !$PAGE->has_set_url()) {
            return;
        }

        $hook->add_html(\html_writer::div('', 'local-chatbot-root'));
    }

    /**
     * Register stylesheet and AMD module while the page requirements manager still accepts them.
     *
     * @param before_standard_head_html_generation $hook
     */
    public static function before_standard_head_html_generation(before_standard_head_html_generation $hook): void {
        global $PAGE;

        if (during_initial_install()) {
            return;
        }

        if (defined('CLI_SCRIPT') && CLI_SCRIPT) {
            return;
        }

        if (defined('AJAX_SCRIPT') && AJAX_SCRIPT) {
            return;
        }

        if (empty($PAGE) || !$PAGE->has_set_url()) {
            return;
        }

        $courseid = self::resolve_course_id();

        $welcome = trim((string)get_config('local_chatbot', 'welcomemessage'));
        if ($welcome === '') {
            $welcome = ($courseid > SITEID)
                ? get_string('welcomemessage_default', 'local_chatbot')
                : get_string('welcomemessage_global', 'local_chatbot');
        }

        $strings = [
            'generating' => get_string('generating', 'local_chatbot'),
            'attachfiles' => get_string('attachfiles', 'local_chatbot'),
            'menuattach' => get_string('menu_attach', 'local_chatbot'),
            'menugeneratequiz' => get_string('menu_generate_quiz', 'local_chatbot'),
            'menumoreactions' => get_string('menu_more_actions', 'local_chatbot'),
            'quizmodeactive' => get_string('quiz_mode_active', 'local_chatbot'),
            'quizmodeplaceholder' => get_string('quiz_mode_placeholder', 'local_chatbot'),
            'removeattachment' => get_string('remove_attachment', 'local_chatbot'),
            'closepreview' => get_string('close_preview', 'local_chatbot'),
            'previewunavailable' => get_string('preview_unavailable', 'local_chatbot'),
            'previewfiletitle' => get_string('preview_file_title', 'local_chatbot'),
            'historytitle' => get_string('history_title', 'local_chatbot'),
            'historysearch' => get_string('history_search', 'local_chatbot'),
            'historyempty' => get_string('history_empty', 'local_chatbot'),
            'paneltitle' => get_string('panel_title', 'local_chatbot'),
            'panelsubtitle' => get_string('panel_subtitle', 'local_chatbot'),
            'buttonlabel' => get_string('button_label', 'local_chatbot'),
            'inputplaceholder' => ($courseid > SITEID)
                ? get_string('input_placeholder_course', 'local_chatbot')
                : get_string('input_placeholder_global', 'local_chatbot'),
            'openingchat' => get_string('opening_chat', 'local_chatbot'),
            'deletecurrent' => get_string('history_delete_current', 'local_chatbot'),
            'closepanel' => get_string('close_panel', 'local_chatbot'),
            'deleteroomaria' => get_string('history_delete_room_aria', 'local_chatbot'),
            'confirmdeleteroom' => get_string('history_delete_room_confirm', 'local_chatbot'),
            'deleteall' => get_string('history_delete_all', 'local_chatbot'),
            'confirmdeleteall' => get_string('history_delete_all_confirm', 'local_chatbot'),
            'deletefailed' => get_string('history_delete_failed', 'local_chatbot'),
            'emptyreply' => get_string('error_empty_reply', 'local_chatbot'),
        ];

        $PAGE->requires->css('/local/chatbot/styles.css');
        $PAGE->requires->js_call_amd('local_chatbot/popup', 'init', [$welcome, $courseid, $strings]);
    }
}
