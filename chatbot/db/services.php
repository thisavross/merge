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
 * Web service definitions.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

$functions = [
    'local_chatbot_create_room' => [
        'classname' => 'local_chatbot_external',
        'methodname' => 'create_room',
        'classpath' => 'local/chatbot/externallib.php',
        'description' => 'Create a new chat room for the current user in a course.',
        'type' => 'read',
        'ajax' => true,
        'loginrequired' => true,
    ],
    'local_chatbot_list_rooms' => [
        'classname' => 'local_chatbot_external',
        'methodname' => 'list_rooms',
        'classpath' => 'local/chatbot/externallib.php',
        'description' => 'List chat rooms (history) for search and sidebar.',
        'type' => 'read',
        'ajax' => true,
        'loginrequired' => true,
    ],
    'local_chatbot_send_message' => [
        'classname' => 'local_chatbot_external',
        'methodname' => 'send_message',
        'classpath' => 'local/chatbot/externallib.php',
        'description' => 'Forward a message to the FastAPI RAG service.',
        'type' => 'read',
        'ajax' => true,
        'loginrequired' => true,
    ],
    'local_chatbot_get_history' => [
        'classname' => 'local_chatbot_external',
        'methodname' => 'get_chat_history',
        'classpath' => 'local/chatbot/externallib.php',
        'description' => 'Load stored chat messages for a room.',
        'type' => 'read',
        'ajax' => true,
        'loginrequired' => true,
    ],
    'local_chatbot_delete_room' => [
        'classname' => 'local_chatbot_external',
        'methodname' => 'delete_room',
        'classpath' => 'local/chatbot/externallib.php',
        'description' => 'Delete one chat room and its messages.',
        'type' => 'write',
        'ajax' => true,
        'loginrequired' => true,
    ],
    'local_chatbot_delete_all_rooms' => [
        'classname' => 'local_chatbot_external',
        'methodname' => 'delete_all_rooms',
        'classpath' => 'local/chatbot/externallib.php',
        'description' => 'Delete every chat room for the user in the current scope.',
        'type' => 'write',
        'ajax' => true,
        'loginrequired' => true,
    ],
];
