<?php
/**
 * CoinGecko API Proxy
 * CORSおよびCSPの問題を回避するためのサーバーサイドプロキシ
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Cache-Control: max-age=300'); // 5分キャッシュ

$coin = isset($_GET['coin']) ? $_GET['coin'] : 'bitcoin';
$vs_currency = isset($_GET['vs_currency']) ? $_GET['vs_currency'] : 'usd';
$days = isset($_GET['days']) ? intval($_GET['days']) : 90;

// パラメータのバリデーション
$allowedCoins = ['bitcoin', 'ethereum'];
$allowedCurrencies = ['usd', 'jpy', 'eur'];

if (!in_array($coin, $allowedCoins)) {
    $coin = 'bitcoin';
}
if (!in_array($vs_currency, $allowedCurrencies)) {
    $vs_currency = 'usd';
}
if ($days < 1 || $days > 365) {
    $days = 90;
}

$url = "https://api.coingecko.com/api/v3/coins/{$coin}/ohlc?vs_currency={$vs_currency}&days={$days}";

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
    echo json_encode(['error' => 'CoinGecko API error', 'httpCode' => $httpCode]);
    exit;
}

echo $response;
