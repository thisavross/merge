<?php
// local/chatbot/quiz_pdf.php
// Browser calls this → it proxies to FastAPI /quiz/pdf → returns PDF to browser.

require_once(__DIR__ . '/../../config.php');
require_login();
require_sesskey();

$raw = file_get_contents('php://input');
$body = json_decode($raw, true);
if (!$body || empty($body['quiz_json'])) {
    http_response_code(400);
    exit('No quiz data');
}

$fastapiurl = get_config('local_chatbot', 'fastapiurl');
$fastapiurl = rtrim($fastapiurl, '/') . '/quiz/pdf';

$ch = curl_init($fastapiurl);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
    'quiz_json'  => $body['quiz_json'],
    'coursename' => $body['coursename'] ?? 'Course',
    'language'   => $body['language'] ?? 'id',
]));
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 30);

$pdf = curl_exec($ch);
$httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($httpcode !== 200 || !$pdf) {
    http_response_code(500);
    exit('PDF generation failed');
}

header('Content-Type: application/pdf');
header('Content-Disposition: attachment; filename="quiz.pdf"');
echo $pdf;