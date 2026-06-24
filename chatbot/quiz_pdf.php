<?php
// local/chatbot/quiz_pdf.php
// Browser calls this → it proxies to FastAPI /quiz/pdf → returns PDF to browser.

require_once(__DIR__ . '/../../config.php');
require_login();

// sesskey may arrive as a query-string param (GET) or inside the JSON body.
// Normalise it into $_POST so require_sesskey() can find it.
if (empty($_POST['sesskey']) && empty($_GET['sesskey'])) {
    $raw = file_get_contents('php://input');
    $body = json_decode($raw, true) ?: [];
    if (!empty($body['sesskey'])) {
        $_POST['sesskey'] = $body['sesskey'];
    }
} else {
    $raw = file_get_contents('php://input');
    $body = json_decode($raw, true) ?: [];
}
require_sesskey();
if (empty($body) || empty($body['quiz_json'])) {
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

// 'inline' mode lets the browser render the PDF in an iframe (preview).
// 'attachment' mode (default) triggers a file download.
$inline = !empty($body['inline']);
$disposition = $inline ? 'inline' : 'attachment';

header('Content-Type: application/pdf');
header('Content-Disposition: ' . $disposition . '; filename="quiz.pdf"');
header('Content-Length: ' . strlen($pdf));
echo $pdf;