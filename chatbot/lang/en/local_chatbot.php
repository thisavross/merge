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
 * Language strings.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

$string['pluginname'] = 'Moda — Moodle Assistant';
$string['welcomemessage'] = 'Welcome message';
$string['welcomemessage_desc'] = 'Initial message shown in the chatbot popup.';
$string['welcomemessage_default'] = 'Hi! I\'m Moda, your Moodle Assistant. Ask me anything about this course or company materials.';
$string['welcomemessage_global'] =
    'Hi! I\'m Moda. Ask about your enrolled courses or PT SMART / Sinarmas documents — I\'ll search across your courses when you\'re not inside a specific course page.';
$string['input_placeholder_course'] = 'Ask something about this course…';
$string['input_placeholder_global'] = 'Ask about your courses or company knowledge…';
$string['opening_chat'] = 'Opening a new chat…';
$string['button_label'] = 'Moda';
$string['fastapiurl'] = 'FastAPI base URL';
$string['fastapiurl_desc'] = 'Base URL of the RAG service (must expose POST /chat). Example: http://127.0.0.1:8787';
$string['fastapisecret'] = 'Shared secret (optional)';
$string['fastapisecret_desc'] = 'If set on the FastAPI service, Moodle sends the same value in the X-Chatbot-Secret header.';
$string['error_need_course'] = 'Open a real course page (not the site home) to use the course chatbot.';
$string['error_course_access'] = 'You do not have access to this course.';
$string['error_no_fastapi'] = 'FastAPI URL is not configured. Set it under Site administration → Plugins → Local plugins → Moodle AI chatbot.';
$string['error_fastapi_http'] = 'Could not reach the FastAPI service. Check that it is running and the URL is correct.';
$string['error_fastapi_json'] = 'The FastAPI service returned an invalid response.';
$string['error_unexpected'] = 'Something went wrong while contacting the chat service.';
$string['error_empty_reply'] = 'The assistant returned no text. Check that the FastAPI service is running and try again from a course page.';
$string['error_empty_message'] = 'Enter a message or attach at least one file.';
$string['generating'] = 'Generating answer…';
$string['attachfiles'] = 'Attach files';
$string['menu_attach'] = 'Attach image / file';
$string['menu_generate_quiz'] = 'Generate quiz';
$string['menu_more_actions'] = 'More actions';
$string['quiz_mode_active'] = 'Quiz mode';
$string['quiz_mode_placeholder'] = 'Describe your quiz (e.g. 10 multiple choice questions)…';
$string['remove_attachment'] = 'Remove attachment';
$string['close_preview'] = 'Close preview';
$string['preview_unavailable'] = 'Preview is not available for this file type. The file will still be sent with your message.';
$string['preview_file_title'] = 'File preview';
$string['attachments_label'] = 'Attachments';
$string['room_default_title'] = 'New chat';
$string['room_legacy_title'] = 'Previous conversation';
$string['room_no_messages'] = 'No messages yet';
$string['room_attachment_title'] = 'File attachment';
$string['error_invalid_room'] = 'This chat session is invalid. Close the chat and open it again.';
$string['history_title'] = 'Chat history';
$string['history_search'] = 'Search chats…';
$string['history_empty'] = 'No previous chats in this course.';
$string['history_delete_current'] = 'Delete this chat';
$string['close_panel'] = 'Close chat';
$string['history_delete_room_aria'] = 'Delete conversation';
$string['history_delete_room_confirm'] = 'Remove this conversation and all its messages? This cannot be undone.';
$string['history_delete_all'] = 'Clear all';
$string['history_delete_all_confirm'] = 'Delete every saved chat in this list? This cannot be undone.';
$string['history_delete_failed'] = 'Could not delete that chat. Try again or refresh the page.';
$string['history_new_chat'] = 'New chat';
$string['panel_title'] = 'Moda';
$string['panel_subtitle'] = 'Moodle Assistant';
$string['privacy:metadata'] = 'The chatbot forwards your question, course id, and user id to a configured FastAPI service. Chat messages may be stored in Moodle for this course.';
$string['privacy:metadata:local_chatbot_message'] = 'Stores chat messages per user and course for history in the popup.';
$string['privacy:metadata:local_chatbot_message:userid'] = 'The user id.';
$string['privacy:metadata:local_chatbot_message:courseid'] = 'The course id.';
$string['privacy:metadata:local_chatbot_message:role'] = 'Whether the line is from the user or the assistant.';
$string['privacy:metadata:local_chatbot_message:message'] = 'The message text.';
$string['privacy:metadata:local_chatbot_message:timecreated'] = 'When the message was saved.';
$string['privacy:metadata:local_chatbot_room'] = 'Stores chat session titles per user and course.';
$string['privacy:metadata:local_chatbot_room:title'] = 'Chat session title (usually first question).';
$string['privacy:metadata:local_chatbot_room:timemodified'] = 'Last activity in the chat session.';
$string['privacy:metadata:local_chatbot_message:roomid'] = 'Chat session the message belongs to.';
