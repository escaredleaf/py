<?php
header('Content-Type: application/json; charset=utf-8');

define('ASSETS_DIR', __DIR__ . '/assets');
define('ALLOWED_EXT', ['glb', 'obj', 'mtl', 'jpg', 'jpeg', 'png', 'webp']);

if (!is_dir(ASSETS_DIR)) {
    mkdir(ASSETS_DIR, 0755, true);
}

function jsonResponse(array $data, int $code = 200): void
{
    http_response_code($code);
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

function formatBytes(int $bytes): string
{
    if ($bytes < 1024) return $bytes . ' B';
    if ($bytes < 1048576) return round($bytes / 1024, 1) . ' KB';
    return round($bytes / 1048576, 1) . ' MB';
}

function sanitizeFilename(string $name): string
{
    $name = basename($name);
    $name = preg_replace('/[^a-zA-Z0-9._\-가-힣]/u', '_', $name);
    return $name ?: 'unnamed';
}

function getFileList(): array
{
    $files = [];
    foreach (glob(ASSETS_DIR . '/*') as $path) {
        if (!is_file($path)) continue;
        $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        if (!in_array($ext, ALLOWED_EXT, true)) continue;

        $files[] = [
            'name'     => basename($path),
            'ext'      => $ext,
            'size'     => filesize($path),
            'size_fmt' => formatBytes(filesize($path)),
            'modified' => date('Y-m-d H:i:s', filemtime($path)),
        ];
    }

    usort($files, fn($a, $b) => strcmp($b['modified'], $a['modified']));
    return $files;
}

$action = $_GET['action'] ?? ($_SERVER['REQUEST_METHOD'] === 'POST' ? 'upload' : 'list');

if ($action === 'list') {
    jsonResponse(['ok' => true, 'files' => getFileList()]);
}

if ($action === 'delete' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    $input = json_decode(file_get_contents('php://input'), true);
    $name = sanitizeFilename($input['name'] ?? '');
    $path = ASSETS_DIR . '/' . $name;

    if (!$name || !is_file($path)) {
        jsonResponse(['ok' => false, 'error' => '파일을 찾을 수 없습니다.'], 404);
    }

    if (!unlink($path)) {
        jsonResponse(['ok' => false, 'error' => '파일 삭제에 실패했습니다.'], 500);
    }

    jsonResponse(['ok' => true, 'files' => getFileList()]);
}

if ($action === 'upload' && $_SERVER['REQUEST_METHOD'] === 'POST') {
    if (empty($_FILES['files'])) {
        jsonResponse(['ok' => false, 'error' => '업로드할 파일이 없습니다.'], 400);
    }

    $uploaded = [];
    $errors = [];
    $fileCount = is_array($_FILES['files']['name']) ? count($_FILES['files']['name']) : 1;

    for ($i = 0; $i < $fileCount; $i++) {
        $name = is_array($_FILES['files']['name'])
            ? $_FILES['files']['name'][$i]
            : $_FILES['files']['name'];
        $tmp  = is_array($_FILES['files']['tmp_name'])
            ? $_FILES['files']['tmp_name'][$i]
            : $_FILES['files']['tmp_name'];
        $err  = is_array($_FILES['files']['error'])
            ? $_FILES['files']['error'][$i]
            : $_FILES['files']['error'];

        if ($err !== UPLOAD_ERR_OK) {
            $errors[] = "$name: 업로드 오류 (코드 $err)";
            continue;
        }

        $safeName = sanitizeFilename($name);
        $ext = strtolower(pathinfo($safeName, PATHINFO_EXTENSION));

        if (!in_array($ext, ALLOWED_EXT, true)) {
            $errors[] = "$name: 허용되지 않는 확장자 ($ext)";
            continue;
        }

        $dest = ASSETS_DIR . '/' . $safeName;
        if (!move_uploaded_file($tmp, $dest)) {
            $errors[] = "$name: 저장 실패";
            continue;
        }

        $uploaded[] = $safeName;
    }

    jsonResponse([
        'ok'       => count($uploaded) > 0,
        'uploaded' => $uploaded,
        'errors'   => $errors,
        'files'    => getFileList(),
    ], count($uploaded) > 0 ? 200 : 400);
}

jsonResponse(['ok' => false, 'error' => '잘못된 요청입니다.'], 400);
