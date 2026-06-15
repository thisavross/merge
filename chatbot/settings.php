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
 * Plugin settings.
 *
 * @package    local_chatbot
 * @copyright  2026
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */

defined('MOODLE_INTERNAL') || die();

if ($hassiteconfig) {
    $settings = new admin_settingpage('local_chatbot', get_string('pluginname', 'local_chatbot'));
    $settings->add(new admin_setting_configtext(
        'local_chatbot/welcomemessage',
        get_string('welcomemessage', 'local_chatbot'),
        get_string('welcomemessage_desc', 'local_chatbot'),
        get_string('welcomemessage_default', 'local_chatbot'),
        PARAM_TEXT
    ));
    $settings->add(new admin_setting_configtext(
        'local_chatbot/fastapiurl',
        get_string('fastapiurl', 'local_chatbot'),
        get_string('fastapiurl_desc', 'local_chatbot'),
        'http://127.0.0.1:8787',
        PARAM_URL
    ));
    $settings->add(new admin_setting_configpasswordunmask(
        'local_chatbot/fastapisecret',
        get_string('fastapisecret', 'local_chatbot'),
        get_string('fastapisecret_desc', 'local_chatbot'),
        ''
    ));
    $ADMIN->add('localplugins', $settings);
}
