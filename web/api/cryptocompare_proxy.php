<?php
/**
 * CryptoCompare API Proxy
 * CORSおよびCSPの問題を回避するためのサーバーサイドプロキシ
 * 
 * バックエンド（Python）と同じCryptoCompare APIを使用して
 * 365日分の正確な日足OHLCデータを取得
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Cache-Control: max-age=300'); // 5分キャッシュ

$fsym = isset($_GET['fsym']) ? $_GET['fsym'] : 'BTC';
$tsym = isset($_GET['tsym']) ? $_GET['tsym'] : 'USD';
$limit = isset($_GET['limit']) ? intval($_GET['limit']) : 365;

// パラメータのバリデーション
$allowedFsym = ['BTC', 'ETH'];
$allowedTsym = ['USD', 'JPY'];

if (!in_array($fsym, $allowedFsym)) {
    $fsym = 'BTC';
}
if (!in_array($tsym, $allowedTsym)) {
    $tsym = 'USD';
}
if ($limit < 1 || $limit > 2000) {
    $limit = 365;
}

$url = "https://min-api.cryptocompare.com/data/v2/histoday?fsym={$fsym}&tsym={$tsym}&limit={$limit}";

$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, $url);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_TIMEOUT, 30);
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
    echo json_encode(['error' => 'CryptoCompare API error', 'httpCode' => $httpCode]);
    exit;
}

echo $response;
