<?php
/**
 * Bybit API Proxy
 * CORSの問題を回避するためのサーバーサイドプロキシ
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Cache-Control: max-age=60'); // 1分キャッシュ

$symbol = isset($_GET['symbol']) ? $_GET['symbol'] : 'BTCUSDT';
$interval = isset($_GET['interval']) ? $_GET['interval'] : 'D';
$limit = isset($_GET['limit']) ? intval($_GET['limit']) : 100;

// パラメータのバリデーション
$allowedSymbols = ['BTCUSDT', 'ETHUSDT'];
$allowedIntervals = ['1', '3', '5', '15', '30', '60', '120', '240', '360', '720', 'D', 'W', 'M'];

if (!in_array($symbol, $allowedSymbols)) {
    $symbol = 'BTCUSDT';
}
if (!in_array($interval, $allowedIntervals)) {
    $interval = 'D';
}
if ($limit < 1 || $limit > 200) {
    $limit = 100;
}

$url = "https://api.bybit.com/v5/market/kline?category=spot&symbol={$symbol}&interval={$interval}&limit={$limit}";

$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, $url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 10);
curl_setopt($ch, CURLOPT_SSL_VERIFYPEER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    'Accept: application/json',
    'User-Agent: BTC-Analysis-Proxy/1.0'
]);

$response = curl_exec($ch);
$httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$error = curl_error($ch);
curl_close($ch);

if ($error) {
    http_response_code(500);
    echo json_encode(['error' => 'Failed to fetch data', 'details' => $error]);
    exit;
}

if ($httpCode !== 200) {
    http_response_code($httpCode);
    echo json_encode(['error' => 'Bybit API error', 'httpCode' => $httpCode]);
    exit;
}

echo $response;
